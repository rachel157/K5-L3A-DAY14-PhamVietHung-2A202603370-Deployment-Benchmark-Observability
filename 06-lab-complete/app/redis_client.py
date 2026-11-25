"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

App vẫn khởi động được khi Redis chưa sẵn sàng hoặc REDIS_URL trống.
"""
from typing import Optional
import redis

from app.config import settings


def _create_client() -> Optional[redis.Redis]:
    if not settings.redis_url:
        return None
    return redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1.5,
        socket_timeout=1.5,
    )


r: Optional[redis.Redis] = _create_client()


def get_redis() -> Optional[redis.Redis]:
    """Trả về Redis client (tạo lại nếu cần khi chưa khởi tạo)."""
    global r
    if r is None and settings.redis_url:
        r = _create_client()
    return r


def redis_healthy() -> bool:
    """Kiểm tra kết nối Redis cho GET /ready."""
    client = get_redis()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except Exception:
        return False
