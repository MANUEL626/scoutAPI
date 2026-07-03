import asyncio
from urllib.parse import urlparse

from app.cache.redis_client import redis_client
from app.config import settings


def domain_from_url(url: str) -> str:
    return urlparse(url).netloc.replace("www.", "").lower()


def delay_for_domain(domain: str) -> float:
    if "pagesjaunes.fr" in domain:
        return settings.DOMAIN_RATE_LIMIT_PAGESJAUNES_SECONDS
    if "linkedin.com" in domain:
        return settings.DOMAIN_RATE_LIMIT_LINKEDIN_SECONDS
    if "google." in domain:
        return settings.DOMAIN_RATE_LIMIT_GOOGLE_SECONDS
    return settings.DOMAIN_RATE_LIMIT_DEFAULT_SECONDS


async def wait_for_domain(url: str) -> None:
    domain = domain_from_url(url)
    delay = delay_for_domain(domain)
    key = f"rate:domain:{domain}"
    while await redis_client.exists(key):
        ttl = await redis_client.ttl(key)
        await asyncio.sleep(max(0.25, min(float(ttl), delay)))
    await redis_client.set(key, "1", ttl=max(1, int(delay)))
