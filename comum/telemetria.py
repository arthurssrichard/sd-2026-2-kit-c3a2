"""
Configuração de rastreamento distribuído (OpenTelemetry -> Jaeger).

Cada serviço chama `configurar(nome_do_servico, app)` no início. A propagação
do contexto usa o padrão W3C tracecontext, o que faz UM ÚNICO trace atravessar
gateway -> fila (Redis) -> worker -> inferência/Qdrant — exatamente o que o
edital (item 6/7) exige do rastreamento distribuído.

Endpoint de exportação configurável por OTEL_EXPORTER_OTLP_ENDPOINT
(padrão http://localhost:4318, protocolo OTLP/HTTP).
"""
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configurar(nome_servico: str, app=None) -> trace.Tracer:
    """Liga o provedor de traces do processo e instrumenta HTTP/Redis.

    - cria um TracerProvider com o nome do serviço (aparece no Jaeger);
    - exporta os spans via OTLP/HTTP para o coletor (Jaeger no compose);
    - instrumenta automaticamente `requests` e `redis` (spans de rede);
    - se `app` (FastAPI) for passado, instrumenta o servidor HTTP.
    Devolve um tracer para spans manuais.
    """
    recurso = Resource.create({"service.name": nome_servico})
    provedor = TracerProvider(resource=recurso)

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    endpoint = endpoint.rstrip("/")
    if not endpoint.endswith("/v1/traces"):
        endpoint += "/v1/traces"
    provedor.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))

    trace.set_tracer_provider(provedor)

    # Instrumentação automática de bibliotecas: cada chamada HTTP saída
    # (requests) e cada comando Redis (fila) vira um span filho, sem código
    # extra nos pontos de chamada.
    RequestsInstrumentor().instrument()
    RedisInstrumentor().instrument()
    if app is not None:
        FastAPIInstrumentor.instrument_app(app)

    return trace.get_tracer(nome_servico)
