"""
API Key authentication — kiểm tra header X-API-Key.
"""
import secrets
from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency cho FastAPI — thiếu hoặc sai X-API-Key trả HTTP 401."""
    expected = settings.agent_api_key
    if not expected or not api_key or not secrets.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing X-API-Key",
        )
    return api_key
