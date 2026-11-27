"""
Autoescalador de workers (extensão do edital): observa o tamanho da fila e
decide quantas réplicas de worker deveriam estar rodando.

- No docker-compose ele atua como RECOMENDADOR: expõe as métricas
  `autoescalador_fila_tamanho` e `autoescalador_escala_recomendada` no
  /metrics e registra a decisão no log (o operador escala com
  `docker compose up -d --scale worker=N`).
- Em Kubernetes o escalonamento é automático via KEDA (k8s/keda-scaledobject.yaml),
  que usa exatamente este critério (comprimento da fila do Redis).

Regra: alvo = min(MAX_WORKERS, ceil(tamanho_fila / LIMIAR_POR_WORKER)), no
mínimo 1. Histéricos simples evitam oscilação: só muda a recomendação quando
o alvo difere da recomendação atual.
"""
import math
import os
import threading
import time

import redis
from fastapi import FastAPI
from prometheus_client import Gauge
from prometheus_fastapi_instrumentator import Instrumentator

from comum.telemetria import configurar

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
FILA = os.getenv("FILA_CHAVE", "fila:tarefas")
LIMIAR_POR_WORKER = int(os.getenv("LIMIAR_FILA_POR_WORKER", "10"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4"))
INTERVALO_S = float(os.getenv("AUTOESCALADOR_INTERVALO_S", "15"))

db = redis.Redis.from_url(REDIS_URL, decode_responses=True)

FILA_TAMANHO = Gauge("autoescalador_fila_tamanho", "Tarefas aguardando na fila")
ESCALA_RECOMENDADA = Gauge(
    "autoescalador_escala_recomendada", "Réplicas de worker recomendadas"
)

app = FastAPI(title="Autoescalador — C3.A2")
configurar("autoescalador", app)
Instrumentator().instrument(app).expose(app)


def alvo_de_escala(tamanho_fila: int) -> int:
    """Réplicas recomendadas para o tamanho atual da fila."""
    if tamanho_fila <= 0:
        return 1
    return max(1, min(MAX_WORKERS, math.ceil(tamanho_fila / LIMIAR_POR_WORKER)))


def _loop_monitor(evento_parada: threading.Event) -> None:
    print(
        f"[autoescalador] monitorando '{FILA}' a cada {INTERVALO_S:.0f}s "
        f"(limiar {LIMIAR_POR_WORKER}/worker, máximo {MAX_WORKERS})",
        flush=True,
    )
    recomendacao_atual = 1
    while not evento_parada.is_set():
        try:
            tamanho = db.llen(FILA)
            alvo = alvo_de_escala(tamanho)
            FILA_TAMANHO.set(tamanho)
            if alvo != recomendacao_atual:
                print(
                    f"[autoescalador] fila={tamanho} -> recomendação de "
                    f"réplicas de worker: {recomendacao_atual} -> {alvo} "
                    f"(em k8s o KEDA aplica; em compose: "
                    f"'docker compose up -d --scale worker={alvo}')",
                    flush=True,
                )
                recomendacao_atual = alvo
            ESCALA_RECOMENDADA.set(recomendacao_atual)
        except redis.RedisError as erro:
            print(f"[autoescalador] redis indisponível: {erro}", flush=True)
        evento_parada.wait(INTERVALO_S)


@app.on_event("startup")
def iniciar_monitor():
    evento = threading.Event()
    thread = threading.Thread(target=_loop_monitor, args=(evento,), daemon=True)
    thread.start()
    app.state.evento_parada = evento
    app.state.thread_monitor = thread


@app.on_event("shutdown")
def parar_monitor():
    evento = getattr(app.state, "evento_parada", None)
    thread = getattr(app.state, "thread_monitor", None)
    if evento is not None:
        evento.set()
    if thread is not None:
        thread.join(timeout=5)


@app.get("/saude")
def saude():
    return {"status": "ok", "servico": "autoescalador"}
