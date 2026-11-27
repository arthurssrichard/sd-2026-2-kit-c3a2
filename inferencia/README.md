# Inferência

API FastAPI interna. `/predict` classifica sentimento e `/vetor` gera o vetor LSA. `treino.py` gera o artefato no build a partir de `corpus.py`, sem baixar dados ou chamar APIs de IA. `/saude` confirma que o modelo pode ser carregado.

Fora do Docker, na raiz do repo e com as dependências instaladas, gere o modelo com `python -m inferencia.treino`.
