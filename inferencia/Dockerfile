FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# curl é usado pelo healthcheck do docker-compose
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY inferencia/requirements.txt /app/inferencia/requirements.txt
RUN pip install --no-cache-dir -r /app/inferencia/requirements.txt

COPY comum/ /app/comum/
COPY inferencia/ /app/inferencia/

# Treino no build: a imagem já sai com o modelo pronto (offline em runtime).
ARG VETOR_DIM=32
RUN python -m inferencia.treino

ENV PYTHONPATH=/app
EXPOSE 8001
CMD ["uvicorn", "inferencia.app:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
