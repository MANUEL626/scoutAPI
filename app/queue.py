from arq import create_pool
from arq.connections import RedisSettings

from app.config import settings


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.REDIS_URL)


async def enqueue_scraping_job(job_id: str, user_id: str, request_data: dict) -> None:
    redis = await create_pool(redis_settings())
    try:
        await redis.enqueue_job(
            "run_scraping_job",
            job_id,
            user_id,
            request_data,
            _queue_name=settings.ARQ_QUEUE_NAME,
        )
    finally:
        await redis.aclose()
