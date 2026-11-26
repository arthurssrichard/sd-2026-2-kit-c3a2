# Serviço de inferência

A "carga de trabalho" da plataforma: classificação de sentimento com modelo
**scikit-learn treinado localmente** (no build da imagem — 100% offline) e
explicação opcional via LLM (modo simulado sem chave de API).

| Rota     | O que faz                                                          |
|----------|--------------------------------------------------------------------|
| `/saude` | healthcheck                                                        |
| `/predict` | `{"texto": "..."}` → rótulo, confiança, tempo, explicação         |
| `/vetor` | `{"texto": "..."}` → vetor denso (LSA) para o armazenamento vetorial |
| `/meta`  | versão do modelo e dimensão do vetor                               |

Arquivos:

- `treino.py` — treina TF-IDF + Regressão Logística e SVD (roda no build);
- `corpus.py` — base de frases em português gerada de forma determinística;
- `app.py` — API FastAPI;
- `llm.py` — cliente de LLM opcional (compatível OpenAI; simulado sem chave).
