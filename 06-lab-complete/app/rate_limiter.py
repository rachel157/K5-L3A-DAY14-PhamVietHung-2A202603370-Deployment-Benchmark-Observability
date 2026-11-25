"""
Rate limiting (sliding window 60s) lưu state trong Redis.
"""
from collections import defaultdict, deque
import hashlib
import time
import uuid

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import get_redis

_WINDOW_SECONDS = 60
_local_windows: dict[str, deque[float]] = defaultdict(deque)


def check_rate_limit(key: str) -> None:
    """Giới hạn RATE_LIMIT_PER_MINUTE request / 60s cho mỗi API key."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    client = get_redis()

    if client is not None:
        redis_key = f"rl:{key_hash}"
        try:
            pipe = client.pipeline()
            pipe.zremrangebyscore(redis_key, 0, now - _WINDOW_SECONDS)
            pipe.zcard(redis_key)
            _, current_count = pipe.execute()

            if current_count >= limit:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(_WINDOW_SECONDS)},
                )

            pipe2 = client.pipeline()
            pipe2.zadd(redis_key, {f"{now}:{uuid.uuid4().hex}": now})
            pipe2.expire(redis_key, _WINDOW_SECONDS)
            pipe2.execute()
            return
        except HTTPException:
            raise
        except RedisError as exc:
            raise HTTPException(
                status_code=503,
                detail="Rate limiter backend unavailable",
            ) from exc

    # Fallback local chỉ dùng khi chạy không có REDIS_URL
    window = _local_windows[key_hash]
    while window and window[0] < now - _WINDOW_SECONDS:
        window.popleft()
    if len(window) >= limit:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(_WINDOW_SECONDS)},
        )
    window.append(now)
