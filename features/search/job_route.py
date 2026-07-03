import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.job import JobResponse, JobStatus
from app.api.v1.schemas.log import JobLogResponse
from app.api.v1.schemas.search import SearchTargetType
from app.auth.dependencies import get_current_user
from app.cache.redis_client import redis_client
from app.db.session import get_db
from app.models.scraping import LeadRecord, PropertyRecord, ScrapeJob, ScrapeJobLog, SignalRecord
from app.models.user import User
from app.queue import enqueue_scraping_job
from app.utils.exceptions import JobNotFoundError

router = APIRouter()


@router.get(
    "/jobs",
    response_model=list[JobResponse],
    summary="Lister les jobs de scraping",
)
async def list_jobs(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(ScrapeJob).where(ScrapeJob.user_id == current_user.id)
    if status:
        query = query.where(ScrapeJob.status == status)
    jobs = (
        await db.scalars(
            query.order_by(ScrapeJob.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return [
        JobResponse(
            job_id=job.id,
            target_type=SearchTargetType(job.request_data.get("target_type", SearchTargetType.LEAD.value)),
            status=JobStatus(job.status),
            progress=job.progress,
            message=job.message,
            total_leads=job.total_leads
            if job.request_data.get("target_type", SearchTargetType.LEAD.value) == SearchTargetType.LEAD.value
            else 0,
            total_properties=job.total_leads
            if job.request_data.get("target_type") == SearchTargetType.PROPERTY.value
            else 0,
            total_signals=job.total_leads
            if job.request_data.get("target_type") == SearchTargetType.SIGNAL.value
            else 0,
            total_results=job.total_leads,
            leads=[],
            properties=[],
            signals=[],
            created_at=job.created_at,
            updated_at=job.updated_at,
            error=job.error,
        )
        for job in jobs
    ]


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="Statut d'un job de scraping",
)
async def get_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    raw = await redis_client.get(f"job:{job_id}")
    if raw:
        data = json.loads(raw)
        if data.get("user_id") and data["user_id"] != current_user.id:
            raise JobNotFoundError(job_id)
        return JobResponse(**data)

    job = await db.get(ScrapeJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise JobNotFoundError(job_id)

    target_type = SearchTargetType(job.request_data.get("target_type", SearchTargetType.LEAD.value))
    leads = []
    properties = []
    signals = []
    if target_type == SearchTargetType.PROPERTY:
        properties = (
            await db.scalars(
                select(PropertyRecord)
                .where(PropertyRecord.job_id == job_id, PropertyRecord.user_id == current_user.id)
                .order_by(PropertyRecord.scraped_at.desc())
            )
        ).all()
    elif target_type == SearchTargetType.SIGNAL:
        signals = (
            await db.scalars(
                select(SignalRecord)
                .where(SignalRecord.job_id == job_id, SignalRecord.user_id == current_user.id)
                .order_by(SignalRecord.scraped_at.desc())
            )
        ).all()
    else:
        leads = (
            await db.scalars(
                select(LeadRecord)
                .where(LeadRecord.job_id == job_id, LeadRecord.user_id == current_user.id)
                .order_by(LeadRecord.scraped_at.desc())
            )
        ).all()
    return JobResponse(
        job_id=job.id,
        target_type=target_type,
        status=JobStatus(job.status),
        progress=job.progress,
        message=job.message,
        total_leads=job.total_leads if target_type == SearchTargetType.LEAD else 0,
        total_properties=job.total_leads if target_type == SearchTargetType.PROPERTY else 0,
        total_signals=job.total_leads if target_type == SearchTargetType.SIGNAL else 0,
        total_results=job.total_leads,
        leads=leads,
        properties=properties,
        signals=signals,
        created_at=job.created_at,
        updated_at=job.updated_at,
        error=job.error,
    )


@router.delete(
    "/jobs/{job_id}",
    summary="Annuler / supprimer un job",
)
async def delete_job(job_id: str, current_user: User = Depends(get_current_user)):
    raw = await redis_client.get(f"job:{job_id}")
    if not raw:
        raise JobNotFoundError(job_id)
    data = json.loads(raw)
    if data.get("user_id") and data["user_id"] != current_user.id:
        raise JobNotFoundError(job_id)
    await redis_client.delete(f"job:{job_id}")
    return {"message": f"Job {job_id} deleted"}


@router.post(
    "/jobs/{job_id}/cancel",
    summary="Demander l'annulation d'un job",
)
async def cancel_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(ScrapeJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise JobNotFoundError(job_id)
    await redis_client.set(f"job:{job_id}:cancel", "1", ttl=3600)
    if job.status in {"pending", "processing"}:
        job.message = "Annulation demandee..."
        await db.commit()
    return {"message": f"Cancel requested for job {job_id}"}


@router.post(
    "/jobs/{job_id}/retry",
    summary="Relancer un job echoue ou termine",
)
async def retry_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(ScrapeJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise JobNotFoundError(job_id)
    await redis_client.delete(f"job:{job_id}:cancel")
    job.status = JobStatus.PENDING.value
    job.progress = 0
    job.message = "Job relance..."
    job.error = None
    await db.commit()
    await enqueue_scraping_job(job.id, current_user.id, job.request_data)
    return {"message": f"Job {job_id} requeued"}


@router.get(
    "/jobs/{job_id}/logs",
    response_model=list[JobLogResponse],
    summary="Logs d'execution d'un job",
)
async def get_job_logs(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(ScrapeJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise JobNotFoundError(job_id)
    return (
        await db.scalars(
            select(ScrapeJobLog)
            .where(ScrapeJobLog.job_id == job_id, ScrapeJobLog.user_id == current_user.id)
            .order_by(ScrapeJobLog.created_at.asc())
        )
    ).all()
