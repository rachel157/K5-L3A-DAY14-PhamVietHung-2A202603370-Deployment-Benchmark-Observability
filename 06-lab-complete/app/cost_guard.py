"""
Cost guard — theo dõi và giới hạn chi phí LLM trong Redis.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import get_redis

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_local_daily_cost: dict[str, float] = {}


def _daily_key() -> str:
    return f"cost:daily:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"


def _monthly_key() -> str:
    return f"cost:monthly:{datetime.now(timezone.utc).strftime('%Y-%m')}"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    daily_key = _daily_key()
    monthly_key = _monthly_key()
    client = get_redis()

    if client is not None:
        try:
            daily_spent = float(client.get(daily_key) or 0.0)
            monthly_spent = float(client.get(monthly_key) or 0.0)
        except RedisError as exc:
            raise HTTPException(
                status_code=503,
                detail="Cost guard backend unavailable",
            ) from exc
    else:
        daily_spent = _local_daily_cost.get(daily_key, 0.0)
        monthly_spent = daily_spent

    if daily_spent >= settings.daily_budget_usd or monthly_spent >= settings.monthly_budget_usd:
        raise HTTPException(status_code=402, detail="Budget exceeded")


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000.0) * PRICE_INPUT_PER_1K + (
        output_tokens / 1000.0
    ) * PRICE_OUTPUT_PER_1K
    daily_key = _daily_key()
    monthly_key = _monthly_key()
    client = get_redis()

    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incrbyfloat(daily_key, cost)
            pipe.expire(daily_key, 2 * 86400)
            pipe.incrbyfloat(monthly_key, cost)
            pipe.expire(monthly_key, 32 * 86400)
            pipe.execute()
        except RedisError as exc:
            raise HTTPException(
                status_code=503,
                detail="Cost guard backend unavailable",
            ) from exc
    else:
        _local_daily_cost[daily_key] = _local_daily_cost.get(daily_key, 0.0) + cost

    return cost
