"""
Treino do modelo local — roda no BUILD da imagem (Dockerfile) e é 100% offline.

Produz `modelo.joblib` com:
  - TF-IDF (1-2 grams) + Regressão Logística  -> classificador de sentimento;
  - TF-IDF + TruncatedSVD (LSA)               -> vetores densos para o
    armazenamento vetorial (busca semântica), sem API externa.

O contêiner sai do build com o modelo já pronto: reprodutível, offline e
sem custo de API. A sofisticação do modelo NÃO pontua no edital.
"""
import os
from pathlib import Path

import joblib
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from corpus import base_rotulada

CAMINHO_MODELO = Path(__file__).parent / "modelo.joblib"
VETOR_DIM = int(os.getenv("VETOR_DIM", "32"))


def treinar() -> dict:
    base = base_rotulada()
    textos = [frase for frase, _ in base]
    rotulos = [rotulo for _, rotulo in base]

    # Mesma vetorização alimenta classificador e vetores semânticos (LSA).
    tfidf = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    matriz = tfidf.fit_transform(textos)

    classificador = LogisticRegression(max_iter=1000, C=4.0)
    classificador.fit(matriz, rotulos)
    acuracia_treino = float(classificador.score(matriz, rotulos))

    # SVD exige n_components < n_features (e < n_amostras); escolha segura:
    dim = min(VETOR_DIM, matriz.shape[1] - 1, matriz.shape[0] - 1)
    svd = TruncatedSVD(n_components=dim, random_state=42)
    svd.fit(matriz)

    pacote = {
        "tfidf": tfidf,
        "classificador": classificador,
        "svd": svd,
        "dim": dim,
        "versao": "1.0.0",
    }
    joblib.dump(pacote, CAMINHO_MODELO)
    print(
        f"[treino] amostras={len(textos)} dim_vetor={dim} "
        f"acuracia_treino={acuracia_treino:.3f} -> {CAMINHO_MODELO}"
    )
    return pacote


if __name__ == "__main__":
    treinar()
