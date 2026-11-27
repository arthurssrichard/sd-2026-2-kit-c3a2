FROM python:3.12-slim

WORKDIR /app

COPY gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY comum/ ./comum/
COPY gateway/ ./gateway/

EXPOSE 8000
CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
