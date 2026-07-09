FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.lock.txt


FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
