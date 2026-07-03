from app.api.v1.schemas.search import SearchRequest
from app.config import settings
from app.db.database import AsyncSessionLocal
from app.queue import redis_settings
from app.scrapers.orchestrator import ScrapingOrchestrator
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def run_scraping_job(ctx, job_id: str, user_id: str, request_data: dict) -> None:
    logger.info("ARQ scraping job started", job_id=job_id, user_id=user_id)
    request = SearchRequest(**request_data)
    async with AsyncSessionLocal() as db:
        await ScrapingOrchestrator(db).run(job_id, user_id, request)


class WorkerSettings:
    functions = [run_scraping_job]
    redis_settings = redis_settings()
    queue_name = settings.ARQ_QUEUE_NAME
    job_timeout = settings.ARQ_JOB_TIMEOUT_SECONDS
    max_jobs = settings.MAX_CONCURRENT_SCRAPERS
    keep_result = 3600
