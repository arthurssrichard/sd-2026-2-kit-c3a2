"""
Worker de fila — consome as tarefas enfileiradas pelo gateway.

Ciclo por tarefa:
  BRPOP fila:tarefas
    -> extrai o contexto de trace gravado na mensagem (o span do worker
       continua o MESMO trace do gateway — rastreamento gateway->fila->worker)
    -> chama a inferência (/predict e /vetor) com timeout/retentativa/circuit
       breaker (item 6 do edital)
    -> grava o resultado no Redis com TTL (GET /tarefas/{id} do gateway lê)
    -> grava o vetor + payload na MEMÓRIA VETORIAL (Qdrant) — item 2 do edital
    -> métricas (Prometheus) e reentrega limitada em caso de falha

O worker também expõe /saude e /metrics: além de healthcheck no compose, é
o que permite publicá-lo como Web Service em plataformas gratuitas (Render)
que esperam um processo com porta HTTP.
"""
import json
import os
import threading
import time
from contextlib import asynccontextmanager

import redis
import requests
from fastapi import FastAPI
from opentelemetry import context as contexto_otel
from opentelemetry import trace
from prometheus_client import Counter, Gauge
from prometheus_fastapi_instrumentator import Instrumentator
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from comum.fila import FILA_PADRAO, contexto_da_tarefa, desenfileirar, id_para_qdrant
from comum.resiliencia import (
    CircuitBreaker,
    chamar_com_resiliencia,
)
from comum.telemetria import configurar

URL_INFERENCIA = os.getenv("URL_INFERENCIA", "http://inferencia:8001")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
FILA = os.getenv("FILA_CHAVE", FILA_PADRAO)
TAREFA_TTL = int(os.getenv("TAREFA_TTL_SEGUNDOS", "3600"))
VETOR_DIM = int(os.getenv("VETOR_DIM", "32"))
MAX_REENTREGAS = int(os.getenv("MAX_REENTREGAS", "3"))
COLECAO = "memoria"

db = redis.Redis.from_url(REDIS_URL, decode_responses=True)
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
_trava_colecao = threading.Lock()
_colecao_pronta = False


def _garantir_colecao(cliente_qdrant: QdrantClient) -> None:
    """Cria a coleção 'memoria' se não existir (idempotente)."""
    global _colecao_pronta
    with _trava_colecao:
        if _colecao_pronta:
            return
        if not cliente_qdrant.collection_exists(COLECAO):
            cliente_qdrant.create_collection(
                collection_name=COLECAO,
                vectors_config=VectorParams(size=VETOR_DIM, distance=Distance.COSINE),
            )
        _colecao_pronta = True


def _salvar_vetor(tarefa: dict, vetor: list[float], resultado: dict) -> None:
    """Grava vetor + metadados no Qdrant (idempotente: id derivado da tarefa)."""
    cliente = QdrantClient(url=QDRANT_URL, timeout=5)
    _garantir_colecao(cliente)
    cliente.upsert(
        collection_name=COLECAO,
        points=[
            PointStruct(
                id=id_para_qdrant(tarefa["id"]),
                vector=vetor,
                payload={
                    "texto": tarefa["texto"],
                    "tarefa_id": tarefa["id"],
                    "rotulo": resultado["rotulo"],
                    "confianca": resultado["confianca"],
                    "criado_em": tarefa["criado_em"],
                },
            )
        ],
    )


# ---------------------------------------------------------------------------
# Processamento
# ---------------------------------------------------------------------------
def _processar(tarefa: dict) -> None:
    ctx = contexto_da_tarefa(tarefa)
    token = contexto_otel.attach(ctx)
    try:
        with tracer.start_as_current_span("worker.processar_tarefa") as span:
            span.set_attribute("tarefa.id", tarefa["id"])
            span.set_attribute("tarefa.tentativas", tarefa["tentativas"])

            # 1) classificação (com resiliência)
            resposta = chamar_com_resiliencia(
                circuito_inferencia,
                requests.post,
                f"{URL_INFERENCIA}/predict",
                json={"texto": tarefa["texto"]},
                tentativas=3,
                timeout_s=10.0,
            )
            dados = resposta.json()
            resultado = {
                "id": tarefa["id"],
                "rotulo": dados["rotulo"],
                "confianca": dados["confianca"],
                "tempo_ms": dados["tempo_ms"],
                "explicacao": dados.get("explicacao", ""),
                "processado_em": round(time.time(), 3),
            }

            # 2) vetorização — se falhar, o resultado ainda é devolvido
            #    (degradação graciosa: só a memória vetorial fica sem o ponto)
            try:
                resposta_vetor = chamar_com_resiliencia(
                    circuito_inferencia,
                    requests.post,
                    f"{URL_INFERENCIA}/vetor",
                    json={"texto": tarefa["texto"]},
                    tentativas=2,
                    timeout_s=10.0,
                )
                vetor = resposta_vetor.json().get("vetor")
            except requests.RequestException:
                vetor = None
                span.set_attribute("vetor.erro", "indisponivel")

            # 3) resultado com TTL (LGPD: expira; NÃO há dado pessoal em metadados)
            db.set(f"resultado:{tarefa['id']}", json.dumps(resultado), ex=TAREFA_TTL)

            # 4) memória vetorial
            if vetor and len(vetor) == VETOR_DIM:
                with tracer.start_as_current_span("worker.salvar_vetor"):
                    _salvar_vetor(tarefa, vetor, resultado)
            elif vetor:
                span.set_attribute("vetor.dim_ilegal", len(vetor))

            TAREFAS_PROCESSADAS.labels(rotulo=resultado["rotulo"]).inc()
            span.set_attribute("tarefa.rotulo", resultado["rotulo"])
    finally:
        contexto_otel.detach(token)


def _loop_consumo(evento_parada: threading.Event) -> None:
    print(f"[worker] consumindo fila '{FILA}' ...", flush=True)
    while not evento_parada.is_set():
        try:
            FILA_PENDENTES.set(db.llen(FILA))
            tarefa = desenfileirar(db, FILA, timeout=2)
        except redis.RedisError as erro:
            print(f"[worker] redis indisponível: {erro}", flush=True)
            time.sleep(2)
            continue
        if tarefa is None:
            continue
        try:
            _processar(tarefa)
        except Exception as erro:  # noqa: BLE001 — worker não pode morrer
            print(
                f"[worker] falha ao processar {tarefa.get('id')}: {erro}",
                flush=True,
            )
            TAREFAS_FALHAS.inc()
            # Reentrega limitada: volta pro fim da fila ou é descartada.
            if tarefa.get("tentativas", 0) < MAX_REENTREGAS:
                tarefa["tentativas"] += 1
                try:
                    db.lpush(FILA, json.dumps(tarefa))
                    print(
                        f"[worker] tarefa {tarefa['id']} reenfileirada "
                        f"(tentativa {tarefa['tentativas']}/{MAX_REENTREGAS})",
                        flush=True,
                    )
                except redis.RedisError:
                    pass
            else:
                print(f"[worker] tarefa {tarefa['id']} descartada após {MAX_REENTREGAS} tentativas", flush=True)


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
