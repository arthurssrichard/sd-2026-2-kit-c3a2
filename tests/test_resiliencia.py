"""
Testes unitários da biblioteca de resiliência (comum/resiliencia.py).
Roda com:  pytest -q
"""
import requests

from comum.resiliencia import (
    CircuitBreaker,
    ErroCircuitBreakerAberto,
    chamar_com_resiliencia,
)


class Resposta:
    def __init__(self, status_code: int):
        self.status_code = status_code


def test_circuit_breaker_abre_apos_limite_de_falhas():
    circuito = CircuitBreaker("teste", limite_falhas=3, tempo_aberto_s=60)

    def acao_falha():
        raise requests.ConnectionError("serviço caiu")

    for _ in range(3):
        try:
            circuito.executar(acao_falha)
        except requests.ConnectionError:
            pass
    assert circuito.estado == "aberto"
    try:
        circuito.executar(acao_falha)
        assert False, "deveria ter recusado a chamada"
    except ErroCircuitBreakerAberto:
        pass


def test_circuit_breaker_meio_aberto_recupera():
    circuito = CircuitBreaker("teste", limite_falhas=1, tempo_aberto_s=0)

    def falha():
        raise requests.Timeout("timeout")

    def sucesso():
        return "ok"

    try:
        circuito.executar(falha)
    except requests.Timeout:
        pass
    assert circuito.estado in ("meio_aberto", "aberto")
    assert circuito.executar(sucesso) == "ok"
    assert circuito.estado == "fechado"


def test_chamar_com_resiliencia_retenta_e_sucesso():
    circuito = CircuitBreaker("teste", limite_falhas=100)
    chamadas = {"contagem": 0}

    def http_quarta_certo(url, timeout=None, **kwargs):
        chamadas["contagem"] += 1
        if chamadas["contagem"] < 3:
            raise requests.ConnectionError("indisponível")
        return Resposta(200)

    resposta = chamar_com_resiliencia(
        circuito, http_quarta_certo, "http://x", tentativas=3, esperas=[0, 0, 0]
    )
    assert resposta.status_code == 200
    assert chamadas["contagem"] == 3


def test_chamar_com_resiliencia_5xx_considera_falha():
    circuito = CircuitBreaker("teste", limite_falhas=100)

    def http_erro_interno(url, timeout=None, **kwargs):
        return Resposta(500)

    try:
        chamar_com_resiliencia(
            circuito, http_erro_interno, "http://x", tentativas=2, esperas=[0, 0]
        )
        assert False, "deveria ter falhado"
    except requests.HTTPError:
        pass
