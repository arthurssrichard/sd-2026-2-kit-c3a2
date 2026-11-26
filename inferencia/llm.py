"""
Cliente de LLM opcional para EXPLICAR a classificação (camada de API).

- Sem LLM_API_KEY definida: modo SIMULADO (offline) — explicação heurística
  local, sem nenhuma chamada externa.
- Com LLM_API_KEY: chamada a uma API compatível com OpenAI
  (POST {LLM_BASE_URL}/chat/completions), com timeout curto e retorno ao
  modo simulado em caso de falha (o serviço nunca fica dependente da API).

Todo contato com IA neste trabalho é chamada de biblioteca/API — nada de
treinar modelos (edital, FAQ).
"""
import os

import requests

CHAVE = os.getenv("LLM_API_KEY", "").strip()
BASE = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
MODELO = os.getenv("LLM_MODELO", "gpt-4o-mini")
TIMEOUT_S = 5.0


def explicar(texto: str, rotulo: str, confianca: float) -> str:
    """Explicação do resultado: LLM real se houver chave; simulado caso contrário."""
    if CHAVE:
        try:
            resposta = requests.post(
                f"{BASE}/chat/completions",
                headers={"Authorization": f"Bearer {CHAVE}"},
                json={
                    "model": MODELO,
                    "max_tokens": 80,
                    "temperature": 0.2,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Explique em UMA frase curta, em português, por que o "
                                "texto a seguir foi classificado como sentimento "
                                "informado. Seja objetivo."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Texto: {texto}\nClassificação: {rotulo} ({confianca:.0%})",
                        },
                    ],
                },
                timeout=TIMEOUT_S,
            )
            resposta.raise_for_status()
            conteudo = resposta.json()["choices"][0]["message"]["content"].strip()
            if conteudo:
                return conteudo
        except requests.RequestException:
            pass  # degrada para o modo simulado
    return _simular(texto, rotulo, confianca)


def _simular(texto: str, rotulo: str, confianca: float) -> str:
    """Heurística local: cita os termos mais longos como sinais principais."""
    sinais = sorted(
        {palavra for palavra in texto.lower().split() if len(palavra) > 4},
        key=len,
        reverse=True,
    )[:4]
    detalhe = ", ".join(sinais) if sinais else "estrutura geral do texto"
    return (
        f"Classificado como {rotulo} com {confianca:.0%} de confiança "
        f"(modo simulado, sem chave de LLM). Sinais: {detalhe}."
    )
