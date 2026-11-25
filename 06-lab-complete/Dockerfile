# Stage 1: Builder — cài dependencies
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime — image gọn, non-root user
FROM python:3.11-slim AS runtime

RUN groupadd -r appuser && useradd -r -g appuser -m appuser

WORKDIR /app

COPY --from=builder /root/.local /home/appuser/.local
COPY app ./app
COPY utils ./utils

RUN chown -R appuser:appuser /app /home/appuser/.local

USER appuser

ENV PYTHONUSERBASE=/home/appuser/.local \
    PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8000\")}/health')" || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
