import json
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.v1.schemas.job import JobStatus
from app.api.v1.schemas.search import SearchRequest, SearchResponse, SearchTargetType
from app.auth.dependencies import get_current_user
from app.cache.redis_client import redis_client
from app.db.database import AsyncSessionLocal
from app.models.user import User
from app.queue import enqueue_scraping_job
from app.scrapers.orchestrator import ScrapingOrchestrator
from app.services.quotas import enforce_free_quota
from app.utils.logger import get_logger

logger = get_logger(__name__)
limiter = Limiter(key_func=get_remote_address)
router = APIRouter()


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Lancer une recherche de leads",
    description="Lance un scraping sur les plateformes selectionnees.",
)
async def search_leads(
    request: Request,
    search_request: SearchRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    job_id = str(uuid.uuid4())
    logger.info(
        "Search request received",
        job_id=job_id,
        query=search_request.query,
        platforms=[p.value for p in search_request.platforms],
        user_id=current_user.id,
    )

    job_data = {
        "job_id": job_id,
        "target_type": search_request.target_type.value,
        "status": JobStatus.PENDING.value,
        "progress": 0,
        "message": "Job en attente de traitement...",
        "total_leads": 0,
        "total_properties": 0,
        "total_signals": 0,
        "total_results": 0,
        "leads": [],
        "properties": [],
        "signals": [],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": None,
        "error": None,
        "request": search_request.model_dump(mode="json"),
        "user_id": current_user.id,
    }
    await redis_client.set(f"job:{job_id}", json.dumps(job_data), ttl=3600)

    async with AsyncSessionLocal() as db:
        await enforce_free_quota(db, current_user.id, search_request)
        await ScrapingOrchestrator(db).create_job(job_id, current_user.id, search_request)

    if search_request.async_mode:
        try:
            await enqueue_scraping_job(job_id, current_user.id, search_request.model_dump(mode="json"))
            message = f"Job cree. Suivez la progression via GET /v1/jobs/{job_id}"
        except Exception as exc:
            logger.warning("ARQ enqueue failed, using FastAPI background task", job_id=job_id, error=str(exc))
            background_tasks.add_task(_process_search, job_id, current_user.id, search_request)
            message = f"Job cree en fallback local. Suivez la progression via GET /v1/jobs/{job_id}"
        return SearchResponse(
            job_id=job_id,
            total=0,
            message=message,
            async_mode=True,
        )

    results = await _process_search(job_id, current_user.id, search_request)
    if search_request.target_type == SearchTargetType.PROPERTY:
        return SearchResponse(
            job_id=job_id,
            properties=results,
            total=len(results),
            message="Recherche terminee.",
            async_mode=False,
        )
    if search_request.target_type == SearchTargetType.SIGNAL:
        return SearchResponse(
            job_id=job_id,
            signals=results,
            total=len(results),
            message="Recherche terminee.",
            async_mode=False,
        )
    return SearchResponse(
        job_id=job_id,
        leads=results,
        total=len(results),
        message="Recherche terminee.",
        async_mode=False,
    )


async def _process_search(job_id: str, user_id: str, search_request: SearchRequest):
    logger.info("Background scraping task started", job_id=job_id)
    async with AsyncSessionLocal() as db:
        orchestrator = ScrapingOrchestrator(db)
        records = await orchestrator.run(job_id, user_id, search_request)
        if search_request.target_type == SearchTargetType.PROPERTY:
            return [orchestrator._property_to_dict(record) for record in records]
        if search_request.target_type == SearchTargetType.SIGNAL:
            return [orchestrator._signal_to_dict(record) for record in records]
        return [orchestrator._lead_to_dict(record) for record in records]
