"""
API Gateway — porta de entrada ÚNICA da plataforma.

Cobertura do edital:
  TAREFA 1  autenticação por JWT (/login emite o token; rotas exigem Bearer);
  TAREFA 2  rate limit por cliente por minuto (janela fixa no Redis, funciona
            com N réplicas do gateway);
  item 6    resiliência: tempo-limite, retentativa com espera progressiva e
            circuit breaker ao chamar a inferência; se o caminho síncrono
            não responde, a tarefa é enfileirada e o cliente recebe 202
            (degradação graciosa em vez de erro);
  item 7    rastreamento distribuído (OpenTelemetry -> Jaeger) e métricas.

Rodar (dev): uvicorn gateway.app:app --port 8000
"""
import hmac
import json
import os
import time
import uuid as modulo_uuid
from datetime import datetime, timedelta, timezone

import jwt
import redis
import requests
from opentelemetry import trace
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field

from comum.fila import COLECAO, FILA_PADRAO, enfileirar, filtro_memoria, nova_tarefa
from comum.resiliencia import (
    CircuitBreaker,
    ErroCircuitBreakerAberto,
    chamar_com_resiliencia,
)
from comum.telemetria import configurar

# ---------------------------------------------------------------------------
# Configuração EXTERNA em variáveis de ambiente (o contêiner é portátil).
# ---------------------------------------------------------------------------
URL_INFERENCIA = os.getenv("URL_INFERENCIA", "http://localhost:8001")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
JWT_SEGREDO = os.getenv("JWT_SEGREDO", "troque-este-segredo")
JWT_ALGORITMO = "HS256"
JWT_EXPIRA_MINUTOS = int(os.getenv("JWT_EXPIRA_MINUTOS", "120"))
LIMITE_POR_MINUTO = int(os.getenv("LIMITE_POR_MINUTO", "30"))
FILA = os.getenv("FILA_CHAVE", FILA_PADRAO)
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")


def _usuarios_do_ambiente() -> dict[str, str]:
    """Usuários de demonstração vindos do ambiente: 'usuario:senha,usuario2:senha2'.

    Em produção as senhas ficariam em hash (bcrypt) num banco — aqui o
    ambiente é suficiente porque o foco é a engenharia distribuída.
    """
    usuarios: dict[str, str] = {}
    for par in os.getenv("USUARIOS", "aluno:aluno123").split(","):
        if ":" in par:
            usuario, senha = par.split(":", 1)
            usuarios[usuario.strip()] = senha.strip()
    return usuarios


USUARIOS = _usuarios_do_ambiente()
if os.getenv("AMBIENTE") == "publico" and (
    len(JWT_SEGREDO) < 32 or not USUARIOS or any(len(senha) < 12 for senha in USUARIOS.values())
):
    raise RuntimeError("Configure JWT_SEGREDO (32+ caracteres) e senhas (12+ caracteres)")

db = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=4)
circuito_inferencia = CircuitBreaker(
    "inferencia", limite_falhas=3, tempo_aberto_s=10.0
)

app = FastAPI(
    title="Gateway — Plataforma de IA como Serviço",
    description="Projeto integrador C3.A2 — Sistemas Distribuídos e Computação em Nuvem",
)
tracer = configurar("gateway", app)
Instrumentator().instrument(app).expose(app)


@app.middleware("http")
async def registrar_requisicao(request: Request, call_next):
    """Log de acesso SEM conteúdo do corpo (LGPD: nenhum texto é gravado)."""
    inicio = time.time()
    resposta = await call_next(request)
    ms = (time.time() - inicio) * 1000
    rota = request.scope.get("route")
    print(f"[gateway] {request.method} {getattr(rota, 'path', '?')} "
          f"-> {resposta.status_code} ({ms:.1f}ms)")
    return resposta


@app.exception_handler(RequestValidationError)
async def entrada_invalida(request: Request, erro: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": "entrada inválida"})


@app.exception_handler(redis.RedisError)
async def redis_indisponivel(request: Request, erro: redis.RedisError):
    return JSONResponse(status_code=503, content={"detail": "estado temporariamente indisponível"})


# ---------------------------------------------------------------------------
# Segurança (TAREFA 1)
# ---------------------------------------------------------------------------
class Credenciais(BaseModel):
    usuario: str
    senha: str


class Entrada(BaseModel):
    """Texto de entrada. Limite de tamanho = minimização de dados (LGPD)."""

    texto: str = Field(min_length=1, max_length=2000)


seguranca = HTTPBearer(auto_error=False)


def cliente_atual(
    credenciais: HTTPAuthorizationCredentials | None = Depends(seguranca),
) -> str:
    """Valida o JWT e devolve o cliente ('sub') — usado para rate limit."""
    if credenciais is None:
        raise HTTPException(status_code=401, detail="token ausente: faça login em /login")
    try:
        carga = jwt.decode(
            credenciais.credentials, JWT_SEGREDO, algorithms=[JWT_ALGORITMO],
            options={"require": ["sub", "exp", "iat"]},
        )
        if not isinstance(carga["sub"], str) or carga["sub"] not in USUARIOS:
            raise jwt.InvalidTokenError()
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expirado: refaça o login")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="token inválido")
    return carga["sub"]


def limite_por_cliente(cliente: str) -> None:
    """TAREFA 2 — janela fixa de 1 minuto no Redis (compartilhada entre réplicas)."""
    janela = int(time.time() // 60)
    identificador = hmac.digest(JWT_SEGREDO.encode(), cliente.encode(), "sha256").hex()
    chave = f"rl:{identificador}:{janela}"
    with db.pipeline() as pipe:
        pipe.incr(chave)
        pipe.expire(chave, 70)
        total, _ = pipe.execute()
    if total > LIMITE_POR_MINUTO:
        raise HTTPException(
            status_code=429,
            detail=f"limite de {LIMITE_POR_MINUTO} requisições por minuto excedido",
            headers={"Retry-After": "60"},
        )


@app.post("/login")
def login(cred: Credenciais, request: Request):
    """TAREFA 1 — emite o token JWT válido por JWT_EXPIRA_MINUTOS."""
    # Rate limit também no login (por IP), para travar força bruta.
    ip = request.client.host if request.client else "desconhecido"
    limite_por_cliente(f"ip:{ip}")

    senha_salva = USUARIOS.get(cred.usuario)
    if not senha_salva or not hmac.compare_digest(
        senha_salva.encode(), cred.senha.encode()
    ):
        raise HTTPException(status_code=401, detail="credenciais inválidas")

    agora = datetime.now(timezone.utc)
    expira = agora + timedelta(minutes=JWT_EXPIRA_MINUTOS)
    token = jwt.encode(
        {
            "sub": cred.usuario,
            "iat": int(agora.timestamp()),
            "exp": int(expira.timestamp()),
            "jti": str(modulo_uuid.uuid4()),
        },
        JWT_SEGREDO,
        algorithm=JWT_ALGORITMO,
    )
    with tracer.start_as_current_span("gateway.emitir_token"):
        return {
            "token": token,
            "tipo": "Bearer",
            "expira_em": expira.isoformat(),
        }


# ---------------------------------------------------------------------------
# Caminho SÍNCRONO (baixa latência) com resiliência e fallback para a fila
# ---------------------------------------------------------------------------
def _resposta_fila(texto: str, cliente: str, motivo: str) -> JSONResponse:
    """Enfileira a tarefa e devolve 202 — o sistema degrada em vez de falhar."""
    with tracer.start_as_current_span("fila.publicar", kind=trace.SpanKind.PRODUCER) as span:
        tarefa = nova_tarefa(texto, cliente)
        try:
            enfileirar(db, tarefa, FILA)
        except redis.RedisError:
            span.set_attribute("erro", "fila_indisponivel")
            raise HTTPException(status_code=503, detail="serviço de inferência e fila indisponíveis")
        span.set_attribute("tarefa.id", tarefa["id"])
        span.set_attribute("fallback.motivo", motivo)
        return JSONResponse(
            status_code=202,
            content={
                "status": "enfileirado",
                "id": tarefa["id"],
                "motivo": motivo,
                "consultar": f"/tarefas/{tarefa['id']}",
            },
        )


# ---------------------------------------------------------------------------
# Rotas públicas e protegidas
# ---------------------------------------------------------------------------
@app.get("/saude")
def saude():
    return {"status": "ok", "servico": "gateway"}


@app.get("/")
def raiz():
    return {
        "servico": "gateway",
        "rotas": ["/login", "/predict", "/tarefas", "/tarefas/{id}", "/memoria/busca", "/saude"],
    }


@app.post("/predict")
def predict(entrada: Entrada, cliente: str = Depends(cliente_atual)):
    """Classificação síncrona; se a inferência não responder, cai na fila."""
    limite_por_cliente(cliente)
    with tracer.start_as_current_span("gateway.predict") as span:
        # LGPD: registra apenas o TAMANHO do texto, nunca o conteúdo.
        span.set_attribute("texto.tamanho", len(entrada.texto))
        try:
            resposta = chamar_com_resiliencia(
                circuito_inferencia,
                requests.post,
                f"{URL_INFERENCIA}/predict",
                json=entrada.model_dump(),
                tentativas=3,
                timeout_s=2.0,
            )
            resposta.raise_for_status()
            return resposta.json()
        except ErroCircuitBreakerAberto:
            return _resposta_fila(entrada.texto, cliente, "circuito aberto")
        except requests.RequestException:
            return _resposta_fila(entrada.texto, cliente, "inferência indisponível")


@app.post("/tarefas", status_code=202)
def criar_tarefa(entrada: Entrada, cliente: str = Depends(cliente_atual)):
    """Caminho ASSÍNCRONO explícito: enfileira e devolve onde consultar."""
    limite_por_cliente(cliente)
    return _resposta_fila(entrada.texto, cliente, "solicitação assíncrona")


@app.get("/tarefas/{tarefa_id}")
def consultar_tarefa(tarefa_id: modulo_uuid.UUID, cliente: str = Depends(cliente_atual)):
    """Resultado da tarefa assíncrona: 202 enquanto pendente, 200 quando pronta."""
    limite_por_cliente(cliente)
    bruto = db.get(f"tarefa:{tarefa_id}")
    tarefa = json.loads(bruto) if bruto else {}
    if tarefa.get("dono") != cliente:
        raise HTTPException(status_code=404, detail="tarefa não encontrada")
    if tarefa["status"] == "pendente":
        return JSONResponse(
            status_code=202, content={"status": "pendente", "id": str(tarefa_id)}
        )
    return {"status": tarefa["status"], "id": tarefa["id"], **tarefa.get("resultado", {})}


class Busca(Entrada):
    k: int = Field(default=5, ge=1, le=20)


@app.post("/memoria/busca")
def busca_memoria(
    entrada: Busca,
    cliente: str = Depends(cliente_atual),
):
    """Busca semântica na memória vetorial: vetoriza a consulta (inferência)
    e busca os pontos mais próximos no armazenamento vetorial (Qdrant)."""
    limite_por_cliente(cliente)
    with tracer.start_as_current_span("gateway.busca_memoria") as span:
        try:
            resposta_vetor = chamar_com_resiliencia(
                circuito_inferencia,
                requests.post,
                f"{URL_INFERENCIA}/vetor",
                json={"texto": entrada.texto},
                tentativas=2,
                timeout_s=2.0,
            )
            resposta_vetor.raise_for_status()
            vetor = resposta_vetor.json()["vetor"]
        except (ErroCircuitBreakerAberto, requests.RequestException):
            raise HTTPException(status_code=503, detail="serviço de inferência indisponível")

        try:
            with tracer.start_as_current_span("gateway.busca_vetorial") as span_q:
                span_q.set_attribute("k", entrada.k)
                resposta_q = requests.post(
                    f"{QDRANT_URL}/collections/{COLECAO}/points/search",
                    json={"vector": vetor, "limit": entrada.k, "filter": filtro_memoria(cliente),
                          "with_payload": ["tarefa_id", "rotulo", "confianca"]},
                    timeout=5,
                )
                if resposta_q.status_code == 404:
                    return {"total": 0, "resultados": []}
                resposta_q.raise_for_status()
                resultados = [
                    {"pontuacao": ponto["score"], **(ponto.get("payload") or {})}
                    for ponto in resposta_q.json().get("result", [])
                ]
        except requests.RequestException:
            raise HTTPException(status_code=503, detail="armazenamento vetorial indisponível")
        span.set_attribute("resultados", len(resultados))
        return {"total": len(resultados), "resultados": resultados}
