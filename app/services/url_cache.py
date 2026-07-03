import json
from hashlib import sha256

from app.cache.redis_client import redis_client
from app.config import settings


def cache_key(url: str) -> str:
    digest = sha256(url.encode("utf-8")).hexdigest()
    return f"cache:url:{digest}"


async def get_cached_page(url: str) -> tuple[str, dict] | None:
    raw = await redis_client.get(cache_key(url))
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload.get("text", ""), payload.get("structured", {})


async def set_cached_page(url: str, text: str, structured: dict) -> None:
    if not text and not structured:
        return
    payload = json.dumps({"text": text, "structured": structured})
    await redis_client.set(cache_key(url), payload, ttl=settings.URL_CACHE_TTL_SECONDS)
