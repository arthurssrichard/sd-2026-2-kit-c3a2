"""
Serviço de inferência — a "carga de trabalho" da plataforma (IA como
biblioteca/API, sem treinar modelos: edital, FAQ).

Rotas:
  /predict  -> rótulo + confiança + tempo + explicação (LLM real ou simulado)
  /vetor    -> vetor denso (LSA) do texto, usado pelo armazenamento vetorial
  /saude    -> healthcheck (compose e plataformas de deploy)

O modelo (modelo.joblib) já vem treinado no BUILD da imagem — ver treino.py.
"""
import os
import threading
import time
from pathlib import Path

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field

from comum.telemetria import configurar
from inferencia import llm

CAMINHO_MODELO = Path(__file__).parent / "modelo.joblib"

app = FastAPI(title="Serviço de inferência — C3.A2")
tracer = configurar("inferencia", app)
Instrumentator().instrument(app).expose(app)

_trava = threading.Lock()
_pacote: dict | None = None


def _modelo() -> dict:
    """Carrega o modelo sob demanda (uma única vez por processo)."""
    global _pacote
    with _trava:
        if _pacote is None:
            if not CAMINHO_MODELO.exists():
                raise HTTPException(
                    status_code=503,
                    detail="modelo ausente: rode 'python treino.py' (o Dockerfile faz isso no build)",
                )
            _pacote = joblib.load(CAMINHO_MODELO)
        return _pacote


class Entrada(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)


@app.get("/saude")
def saude():
    return {"status": "ok", "servico": "inferencia"}


@app.post("/predict")
def predict(entrada: Entrada):
    """Classificação de sentimento. Resposta inclui métricas e explicação."""
    pacote = _modelo()
    inicio = time.perf_counter()
    with tracer.start_as_current_span("inferencia.classificar") as span:
        span.set_attribute("texto.tamanho", len(entrada.texto))  # LGPD: sem conteúdo
        matriz = pacote["tfidf"].transform([entrada.texto])
        rotulo = str(pacote["classificador"].predict(matriz)[0])
        probabilidade = pacote["classificador"].predict_proba(matriz)[0]
        confianca = float(np.max(probabilidade))
        tempo_ms = (time.perf_counter() - inicio) * 1000
        span.set_attribute("rotulo", rotulo)
        span.set_attribute("confianca", confianca)
        return {
            "rotulo": rotulo,
            "confianca": round(confianca, 4),
            "tempo_ms": round(tempo_ms, 2),
            "modelo": pacote["versao"],
            "explicacao": llm.explicar(entrada.texto, rotulo, confianca),
        }


@app.post("/vetor")
def vetor(entrada: Entrada):
    """Vetor denso (LSA) do texto — consumido pelo worker/gateway para o
    armazenamento vetorial (Qdrant). Determinístico e offline."""
    pacote = _modelo()
    with tracer.start_as_current_span("inferencia.vetorizar") as span:
        matriz = pacote["tfidf"].transform([entrada.texto])
        denso = pacote["svd"].transform(matriz)[0]
        span.set_attribute("dim", int(pacote["dim"]))
        return {"dim": int(pacote["dim"]), "vetor": [float(x) for x in denso]}


@app.get("/meta")
def meta():
    pacote = _modelo()
    return {"versao": pacote["versao"], "dim_vetor": int(pacote["dim"])}
