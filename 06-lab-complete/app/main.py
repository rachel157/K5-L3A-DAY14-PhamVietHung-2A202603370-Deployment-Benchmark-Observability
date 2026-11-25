"""
Production AI Agent — Part 6 Final Project.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import signal
import time
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Định dạng mỗi dòng log thành một JSON object hợp lệ."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        return json.dumps(payload, ensure_ascii=False)


logger = logging.getLogger("production_agent")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(JsonFormatter())
    logger.addHandler(_handler)


def _log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"extra_fields": {"event": event, **fields}})


_in_flight_requests = 0

_previous_sigterm = signal.getsignal(signal.SIGTERM)


def _handle_sigterm(signum, frame):
    _log_event("sigterm", signal=signum)
    if callable(_previous_sigterm):
        _previous_sigterm(signum, frame)


signal.signal(signal.SIGTERM, _handle_sigterm)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log_event(
        "startup",
        environment=settings.environment,
        port=settings.port,
        redis_configured=bool(settings.redis_url),
    )
    yield
    _log_event("shutdown_initiated", in_flight=_in_flight_requests)
    deadline = time.monotonic() + 5.0
    while _in_flight_requests > 0 and time.monotonic() < deadline:
        time.sleep(0.05)
    _log_event("shutdown_complete", in_flight=_in_flight_requests)


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    global _in_flight_requests
    _in_flight_requests += 1
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        _in_flight_requests -= 1
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        _log_event(
            "request",
            method=request.method,
            path=request.url.path,
            status=status_code,
            ms=elapsed_ms,
        )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    _log_event(
        "unhandled_error",
        level=logging.ERROR,
        path=request.url.path,
        error_type=type(exc).__name__,
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[str] = Field(default=None, max_length=128)


@app.get("/health")
def health():
    """Liveness probe — luôn trả 200 khi process còn chạy."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness probe — 200 khi Redis sẵn sàng, 503 khi mất kết nối."""
    if not redis_healthy():
        raise HTTPException(
            status_code=503,
            detail={"status": "not ready", "redis": "unavailable"},
        )
    return {"status": "ready"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)
    input_tokens = max(1, len(body.question) // 4)
    output_tokens = max(1, len(answer) // 4)
    cost_usd = record_cost(input_tokens, output_tokens)

    return {
        "question": body.question,
        "answer": answer,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 8),
        },
    }
