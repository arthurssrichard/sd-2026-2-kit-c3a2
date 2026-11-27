"""
Biblioteca de resiliência compartilhada pelos serviços da plataforma.

Implementa os três mecanismos exigidos pelo edital (item 6):
  1. tempo-limite (timeout) em toda chamada de rede;
  2. retentativa com espera progressiva (exponencial + jitter);
  3. circuit breaker (fechado -> aberto -> meio-aberto).

Implementação manual (sem dependências externas) de propósito: o
funcionamento fica explícito e não dependemos de bibliotecas que possam
mudar de API entre versões.
"""
from __future__ import annotations

import random
import threading
import time
from typing import Any, Callable, Optional

import requests


class ErroCircuitBreakerAberto(Exception):
    """Chamada recusada porque o circuito está aberto (evita falha em cascata)."""


class CircuitBreaker:
    """Circuit breaker em três estados, por dependência remota.

    - fechado: chamadas passam normalmente; falhas consecutivas contam;
    - aberto: chamadas são recusadas de imediato durante `tempo_aberto_s`;
    - meio-aberto: passado o tempo de espera, uma chamada de teste passa.
      Se falhar, o circuito reabre. Se funcionar, o circuito fecha.
    """

    def __init__(self, nome: str, limite_falhas: int = 3, tempo_aberto_s: float = 10.0):
        self.nome = nome
        self.limite_falhas = limite_falhas
        self.tempo_aberto_s = tempo_aberto_s
        self._lock = threading.Lock()
        self._estado = "fechado"
        self._falhas_consecutivas = 0
        self._aberto_em: Optional[float] = None

    @property
    def estado(self) -> str:
        with self._lock:
            if (
                self._estado == "aberto"
                and (time.monotonic() - self._aberto_em) >= self.tempo_aberto_s
            ):
                self._estado = "meio_aberto"
            return self._estado

    def _registrar_sucesso(self) -> None:
        with self._lock:
            self._estado = "fechado"
            self._falhas_consecutivas = 0
            self._aberto_em = None

    def _registrar_falha(self) -> None:
        with self._lock:
            self._falhas_consecutivas += 1
            if (
                self._estado == "meio_aberto"
                or self._falhas_consecutivas >= self.limite_falhas
            ):
                self._estado = "aberto"
                self._aberto_em = time.monotonic()

    def executar(self, acao: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Executa `acao` sob o controle do circuito."""
        if self.estado == "aberto":
            raise ErroCircuitBreakerAberto(
                f"{self.nome}: circuito aberto, chamada recusada"
            )
        try:
            resultado = acao(*args, **kwargs)
        except Exception:
            self._registrar_falha()
            raise
        self._registrar_sucesso()
        return resultado


def chamar_com_resiliencia(
    circuito: CircuitBreaker,
    funcao_http: Callable[..., requests.Response],
    url: str,
    tentativas: int = 3,
    timeout_s: float = 10.0,
    esperas: Optional[list[float]] = None,
    **kwargs: Any,
) -> requests.Response:
    """Chamada HTTP com timeout + retentativa (exponencial com jitter) + circuit breaker.

    - `funcao_http` normalmente é `requests.post` / `requests.get`;
    - respostas 5xx contam como falha para o circuito (o serviço remoto está
      doente); 4xx são devolvidas ao chamador (erro do cliente, não do sistema);
    - entre tentativas a espera dobra (0.3s, 0.6s, 1.2s...) com jitter de
      50%-100% para não sincronizar clientes; passe `esperas=[0, 0, 0]`
      em testes para zerar a espera.
    """
    if esperas is None:
        esperas = [0.3 * (2 ** i) for i in range(tentativas)]
    ultima_erro: Optional[Exception] = None
    for indice, espera in enumerate(esperas):
        if indice > 0:
            time.sleep(espera * (0.5 + random.random() / 2))
        try:
            resposta = circuito.executar(funcao_http, url, timeout=timeout_s, **kwargs)
            if resposta.status_code >= 500:
                raise requests.HTTPError(
                    f"status {resposta.status_code}", response=resposta
                )
            return resposta
        except ErroCircuitBreakerAberto:
            raise
        except requests.RequestException as erro:
            ultima_erro = erro
    raise ultima_erro  # todas as tentativas falharam
