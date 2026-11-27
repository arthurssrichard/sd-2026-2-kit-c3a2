"""
Fila de tarefas no Redis com propagação de contexto de rastreamento.

A lista FIFO (LPUSH + BRPOP) guarda apenas IDs. A chave temporária da tarefa
guarda conteúdo, estado e contexto W3C que liga o worker ao trace do gateway.
"""
import json
import os
import time
import uuid

from opentelemetry import propagate, trace

FILA_PADRAO = "fila:tarefas"
TAREFA_TTL = int(os.getenv("TAREFA_TTL_SEGUNDOS", "3600"))
COLECAO = "memoria_v2"


def nova_tarefa(texto: str, dono: str) -> dict:
    """Cria uma tarefa pendente, ainda não publicada."""
    return {
        "id": str(uuid.uuid4()),
        "texto": texto,
        "dono": dono,
        "status": "pendente",
        "criado_em": round(time.time(), 3),
        "tentativas": 0,
        "tracardo": {},
    }


def enfileirar(cliente_redis, tarefa: dict, fila: str = FILA_PADRAO) -> None:
    """Publica a tarefa na fila, capturando o contexto de trace atual."""
    propagate.inject(tarefa["tracardo"])
    with cliente_redis.pipeline() as pipe:
        pipe.set(f"tarefa:{tarefa['id']}", json.dumps(tarefa), ex=TAREFA_TTL)
        pipe.lpush(fila, tarefa["id"])
        pipe.execute()


def desenfileirar(cliente_redis, fila: str = FILA_PADRAO, timeout: int = 2):
    """Consome a próxima tarefa (bloqueia até `timeout` segundos) ou None."""
    item = cliente_redis.brpop(fila, timeout=timeout)
    if item is None:
        return None
    _, tarefa_id = item
    bruto = cliente_redis.get(f"tarefa:{tarefa_id}")
    return json.loads(bruto) if bruto else None


def atualizar(cliente_redis, tarefa: dict, **campos) -> None:
    cliente_redis.set(
        f"tarefa:{tarefa['id']}", json.dumps({**tarefa, **campos}), xx=True, keepttl=True
    )


def filtro_memoria(dono: str) -> dict:
    return {
        "must": [
            {"key": "dono", "match": {"value": dono}},
            {"key": "expira_em", "range": {"gt": time.time()}},
        ]
    }


def contexto_da_tarefa(tarefa: dict):
    """Reconstrói o contexto de rastreamento gravado na mensagem."""
    return propagate.extract(tarefa.get("tracardo") or {})


def id_para_qdrant(tarefa_id: str) -> str:
    """ID determinístico para o ponto vetorial (reprocessar é idempotente)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tarefa:{tarefa_id}"))
