"""
Testes unitários do esquema de autenticação JWT (TAREFA 1).
Roda com:  pytest -q
"""
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest

SEGREDO = "segredo-de-teste"
ALGORITMO = "HS256"


def emite(sub="aluno", minutos=30):
    agora = datetime.now(timezone.utc)
    return pyjwt.encode(
        {
            "sub": sub,
            "iat": int(agora.timestamp()),
            "exp": int((agora + timedelta(minutes=minutos)).timestamp()),
        },
        SEGREDO,
        algorithm=ALGORITMO,
    )


def test_token_valido_decodifica():
    carga = pyjwt.decode(emite(), SEGREDO, algorithms=[ALGORITMO])
    assert carga["sub"] == "aluno"


def test_token_expirado_rejeitado():
    token = emite(minutos=-1)
    with pytest.raises(pyjwt.ExpiredSignatureError):
        pyjwt.decode(token, SEGREDO, algorithms=[ALGORITMO])


def test_token_assinado_com_outro_segredo_rejeitado():
    with pytest.raises(pyjwt.InvalidTokenError):
        pyjwt.decode(emite(), "segredo-diferente", algorithms=[ALGORITMO])


def test_token_com_algoritmo_diferente_rejeitado():
    token = pyjwt.encode({"sub": "aluno"}, None, algorithm="none")
    with pytest.raises(pyjwt.InvalidTokenError):
        pyjwt.decode(token, SEGREDO, algorithms=["HS256"])
