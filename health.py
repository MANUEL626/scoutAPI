"""
Router — Health Check
"""
from fastapi import APIRouter
from app.cache.redis_client import redis_client
from app.config import settings

router = APIRouter()


@router.get("/health", summary="Health Check")
async def health_check():
    redis_ok = await redis_client.ping()
    return {
        "status": "healthy" if redis_ok else "degraded",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "env": settings.APP_ENV,
        "services": {
            "redis": "ok" if redis_ok else "unreachable",
            "api": "ok",
        },
    }