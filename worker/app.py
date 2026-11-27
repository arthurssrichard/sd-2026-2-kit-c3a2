"""Consome a fila Redis e indexa no Qdrant antes de concluir a tarefa."""
import os
import threading
import time

import redis
import requests
from fastapi import FastAPI
from opentelemetry import context as contexto_otel
from opentelemetry.trace import SpanKind
from prometheus_client import Counter, Gauge
from prometheus_fastapi_instrumentator import Instrumentator
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, PointStruct, Range, VectorParams
from qdrant_client.http.exceptions import UnexpectedResponse

from comum.fila import (
    COLECAO, FILA_PADRAO, TAREFA_TTL, atualizar, contexto_da_tarefa,
    desenfileirar, id_para_qdrant,
)
from comum.resiliencia import (
    CircuitBreaker,
    chamar_com_resiliencia,
)
from comum.telemetria import configurar

URL_INFERENCIA = os.getenv("URL_INFERENCIA", "http://inferencia:8001")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
FILA = os.getenv("FILA_CHAVE", FILA_PADRAO)
VETOR_DIM = int(os.getenv("VETOR_DIM", "32"))
MAX_REENTREGAS = int(os.getenv("MAX_REENTREGAS", "3"))
db = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=4)
qdrant = QdrantClient(url=QDRANT_URL, timeout=5)
circuito_inferencia = CircuitBreaker("inferencia", limite_falhas=3, tempo_aberto_s=10.0)

# Métricas de negócio (extensão "painel de métricas").
TAREFAS_PROCESSADAS = Counter(
    "worker_tarefas_processadas_total", "Tarefas processadas por rótulo", ["rotulo"]
)
TAREFAS_FALHAS = Counter("worker_tarefas_falhas_total", "Falhas de processamento")
FILA_PENDENTES = Gauge("worker_fila_pendentes", "Tarefas aguardando na fila")

app = FastAPI(title="Worker de fila — C3.A2")
tracer = configurar("worker", app)
Instrumentator().instrument(app).expose(app)


# ---------------------------------------------------------------------------
# Armazenamento vetorial (Qdrant)
# ---------------------------------------------------------------------------
def _garantir_colecao() -> None:
    """Cria a coleção 'memoria' se não existir (idempotente)."""
    if not qdrant.collection_exists(COLECAO):
        try:
            qdrant.create_collection(
                collection_name=COLECAO,
                vectors_config=VectorParams(size=VETOR_DIM, distance=Distance.COSINE),
            )
        except UnexpectedResponse as erro:
            if erro.status_code != 409:
                raise


def _salvar_vetor(tarefa: dict, vetor: list[float], resultado: dict) -> None:
    """Grava vetor + metadados no Qdrant (idempotente: id derivado da tarefa)."""
    if len(vetor) != VETOR_DIM:
        raise ValueError("Dimensão incompatível com a coleção")
    _garantir_colecao()
    qdrant.upsert(
        collection_name=COLECAO,
        wait=True,
        points=[
            PointStruct(
                id=id_para_qdrant(tarefa["id"]),
                vector=vetor,
                payload={
                    "dono": tarefa["dono"],
                    "tarefa_id": tarefa["id"],
                    "rotulo": resultado["rotulo"],
                    "confianca": resultado["confianca"],
                    "expira_em": tarefa["criado_em"] + TAREFA_TTL,
                },
            )
        ],
    )


def _limpar_memoria() -> None:
    if qdrant.collection_exists(COLECAO):
        qdrant.delete(
            COLECAO,
            points_selector=Filter(
                must=[FieldCondition(key="expira_em", range=Range(lte=time.time()))]
            ),
        )


# ---------------------------------------------------------------------------
# Processamento
# ---------------------------------------------------------------------------
def _processar(tarefa: dict) -> None:
    ctx = contexto_da_tarefa(tarefa)
    token = contexto_otel.attach(ctx)
    try:
        with tracer.start_as_current_span(
            "worker.processar_tarefa", kind=SpanKind.CONSUMER,
            record_exception=False, set_status_on_exception=False,
        ) as span:
            span.set_attribute("tarefa.id", tarefa["id"])
            span.set_attribute("tarefa.tentativas", tarefa["tentativas"])

            # 1) classificação (com resiliência)
            resposta = chamar_com_resiliencia(
                circuito_inferencia,
                requests.post,
                f"{URL_INFERENCIA}/predict",
                json={"texto": tarefa["texto"]},
                tentativas=3,
                timeout_s=2.0,
            )
            resposta.raise_for_status()
            dados = resposta.json()
            resultado = {
                "id": tarefa["id"],
                "rotulo": dados["rotulo"],
                "confianca": dados["confianca"],
                "tempo_ms": dados["tempo_ms"],
                "processado_em": round(time.time(), 3),
            }

            resposta_vetor = chamar_com_resiliencia(
                circuito_inferencia, requests.post, f"{URL_INFERENCIA}/vetor",
                json={"texto": tarefa["texto"]}, tentativas=2, timeout_s=2.0,
            )
            resposta_vetor.raise_for_status()
            with tracer.start_as_current_span(
                "worker.salvar_vetor", record_exception=False, set_status_on_exception=False,
            ):
                _salvar_vetor(tarefa, resposta_vetor.json()["vetor"], resultado)

            atualizar(db, tarefa, status="concluido", texto=None, resultado=resultado)

            TAREFAS_PROCESSADAS.labels(rotulo=resultado["rotulo"]).inc()
            span.set_attribute("tarefa.rotulo", resultado["rotulo"])
    finally:
        contexto_otel.detach(token)


def _loop_consumo(evento_parada: threading.Event) -> None:
    print(f"[worker] consumindo fila '{FILA}' ...", flush=True)
    proxima_limpeza = 0.0
    while not evento_parada.is_set():
        if time.monotonic() >= proxima_limpeza:
            try:
                _limpar_memoria()
            except Exception as erro:
                print(f"[worker] limpeza indisponível: {type(erro).__name__}", flush=True)
            proxima_limpeza = time.monotonic() + 60
        try:
            FILA_PENDENTES.set(db.llen(FILA))
            tarefa = desenfileirar(db, FILA, timeout=2)
        except redis.RedisError as erro:
            print(f"[worker] redis indisponível: {type(erro).__name__}", flush=True)
            time.sleep(2)
            continue
        if tarefa is None:
            continue
        try:
            _processar(tarefa)
        except Exception as erro:  # noqa: BLE001 — worker não pode morrer
            print(
                f"[worker] falha ao processar {tarefa['id']}: {type(erro).__name__}",
                flush=True,
            )
            TAREFAS_FALHAS.inc()
            # Reentrega limitada: volta pro fim da fila ou é descartada.
            if tarefa.get("tentativas", 0) < MAX_REENTREGAS:
                tentativas = tarefa["tentativas"] + 1
                evento_parada.wait(2 ** tentativas)
                try:
                    atualizar(db, tarefa, tentativas=tentativas)
                    db.lpush(FILA, tarefa["id"])
                except redis.RedisError:
                    print("[worker] Redis indisponível durante reentrega", flush=True)
            else:
                try:
                    atualizar(db, tarefa, status="falhou", texto=None)
                except redis.RedisError:
                    print("[worker] Redis indisponível ao registrar falha", flush=True)


@app.on_event("startup")
def iniciar_loop():
    evento = threading.Event()
    thread = threading.Thread(target=_loop_consumo, args=(evento,), daemon=True)
    thread.start()
    app.state.evento_parada = evento
    app.state.thread_consumo = thread


@app.on_event("shutdown")
def parar_loop():
    evento = getattr(app.state, "evento_parada", None)
    thread = getattr(app.state, "thread_consumo", None)
    if evento is not None:
        evento.set()
    if thread is not None:
        thread.join(timeout=5)


@app.get("/saude")
def saude():
    return {
        "status": "ok",
        "servico": "worker",
        "fila_pendentes": int(FILA_PENDENTES._value.get()),  # noqa: SLF001
    }
