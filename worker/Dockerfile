FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# curl é usado pelo healthcheck do docker-compose
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY worker/requirements.txt /app/worker/requirements.txt
RUN pip install --no-cache-dir -r /app/worker/requirements.txt

COPY comum/ /app/comum/
COPY worker/ /app/worker/

ENV PYTHONPATH=/app
EXPOSE 8002
CMD ["uvicorn", "worker.app:app", "--host", "0.0.0.0", "--port", "8002", "--no-access-log"]
