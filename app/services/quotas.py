from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.search import SearchRequest
from app.config import settings
from app.models.scraping import ScrapeJob


ACTIVE_STATUSES = {"pending", "processing"}


async def enforce_free_quota(db: AsyncSession, user_id: str, request: SearchRequest) -> None:
    if request.max_results > settings.FREE_MAX_RESULTS_PER_JOB:
        raise HTTPException(
            status_code=422,
            detail=f"max_results cannot exceed {settings.FREE_MAX_RESULTS_PER_JOB} on the free test plan",
        )

    active_jobs = await db.scalar(
        select(func.count())
        .select_from(ScrapeJob)
        .where(ScrapeJob.user_id == user_id, ScrapeJob.status.in_(ACTIVE_STATUSES))
    )
    if active_jobs and active_jobs >= settings.FREE_MAX_ACTIVE_JOBS_PER_USER:
        raise HTTPException(status_code=429, detail="Too many active jobs for this user")

    since = datetime.now(timezone.utc) - timedelta(days=1)
    jobs_today = await db.scalar(
        select(func.count())
        .select_from(ScrapeJob)
        .where(ScrapeJob.user_id == user_id, ScrapeJob.created_at >= since)
    )
    if jobs_today and jobs_today >= settings.FREE_MAX_JOBS_PER_DAY:
        raise HTTPException(status_code=429, detail="Daily job quota exceeded")
