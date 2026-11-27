"""
Fila de tarefas no Redis com propagação de contexto de rastreamento.

A mensagem carrega um campo `tracardo` (carrier do padrão W3C tracecontext):
o gateway injeta o contexto do span corrente ao enfileirar e o worker extrai
ao consumir — o processamento continua o MESMO trace do requisito original.
É assim que o trace cobre gateway, fila e worker (item 7 do edital).

Protocolo da fila (LPUSH + BRPOP = FIFO):
  {"id": "<uuid>", "texto": "...", "criado_em": 1712..., "tentativas": 0,
   "tracardo": {"traceparent": "..."}}
"""
import json
import time
import uuid

from opentelemetry import propagate, trace

FILA_PADRAO = "fila:tarefas"


def nova_tarefa(texto: str) -> dict:
    """Cria a mensagem de tarefa (id único; sem dados pessoais)."""
    return {
        "id": str(uuid.uuid4()),
        "texto": texto,
        "criado_em": round(time.time(), 3),
        "tentativas": 0,
        "tracardo": {},
    }


def enfileirar(cliente_redis, tarefa: dict, fila: str = FILA_PADRAO) -> None:
    """Publica a tarefa na fila, capturando o contexto de trace atual."""
    propagate.inject(tarefa["tracardo"])
    cliente_redis.lpush(fila, json.dumps(tarefa))


def desenfileirar(cliente_redis, fila: str = FILA_PADRAO, timeout: int = 2):
    """Consome a próxima tarefa (bloqueia até `timeout` segundos) ou None."""
    item = cliente_redis.brpop(fila, timeout=timeout)
    if item is None:
        return None
    _, bruto = item
    return json.loads(bruto)


def contexto_da_tarefa(tarefa: dict):
    """Reconstrói o contexto de rastreamento gravado na mensagem."""
    return propagate.extract(tarefa.get("tracardo") or {})


def id_para_qdrant(tarefa_id: str) -> str:
    """ID determinístico para o ponto vetorial (reprocessar é idempotente)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tarefa:{tarefa_id}"))
