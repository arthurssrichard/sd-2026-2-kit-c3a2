FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY autoescalador/requirements.txt /app/autoescalador/requirements.txt
RUN pip install --no-cache-dir -r /app/autoescalador/requirements.txt

COPY comum/ /app/comum/
COPY autoescalador/ /app/autoescalador/

ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "autoescalador.app:app", "--host", "0.0.0.0", "--port", "8000"]
