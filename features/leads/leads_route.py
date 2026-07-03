from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.lead import Lead, LeadCategory, LeadIntent, QualificationLevel
from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.scraping import LeadRecord
from app.models.user import User
from app.services.exports import leads_to_csv
from app.utils.exceptions import LeadNotFoundError

router = APIRouter()


@router.get(
    "/leads",
    response_model=List[Lead],
    summary="Lister les leads collectes",
)
async def list_leads(
    job_id: Optional[str] = Query(None, description="Filtrer par job"),
    lead_category: Optional[LeadCategory] = Query(None),
    lead_intent: Optional[LeadIntent] = Query(None),
    qualification: Optional[QualificationLevel] = Query(None),
    min_score: Optional[int] = Query(None, ge=0, le=100),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(LeadRecord).where(LeadRecord.user_id == current_user.id)
    if job_id:
        query = query.where(LeadRecord.job_id == job_id)
    if lead_category:
        query = query.where(LeadRecord.lead_category == lead_category.value)
    if lead_intent:
        query = query.where(LeadRecord.lead_intent == lead_intent.value)
    if qualification:
        query = query.where(LeadRecord.qualification == qualification.value)
    if min_score is not None:
        query = query.where(LeadRecord.score >= min_score)
    query = query.order_by(LeadRecord.scraped_at.desc()).limit(limit).offset(offset)
    return (await db.scalars(query)).all()


@router.get(
    "/leads/export",
    summary="Exporter les leads en CSV ou JSON",
)
async def export_leads(
    job_id: Optional[str] = Query(None, description="Filtrer par job"),
    lead_category: Optional[LeadCategory] = Query(None),
    lead_intent: Optional[LeadIntent] = Query(None),
    format: str = Query("csv", pattern="^(csv|json)$"),
    limit: int = Query(1000, ge=1, le=5000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(LeadRecord).where(LeadRecord.user_id == current_user.id)
    if job_id:
        query = query.where(LeadRecord.job_id == job_id)
    if lead_category:
        query = query.where(LeadRecord.lead_category == lead_category.value)
    if lead_intent:
        query = query.where(LeadRecord.lead_intent == lead_intent.value)
    leads = (await db.scalars(query.order_by(LeadRecord.scraped_at.desc()).limit(limit))).all()

    if format == "json":
        return [Lead.model_validate(lead).model_dump(mode="json") for lead in leads]

    csv_data = leads_to_csv(list(leads))
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="scoutapi-leads.csv"'},
    )


@router.get(
    "/leads/{lead_id}",
    response_model=Lead,
    summary="Detail d'un lead",
)
async def get_lead(
    lead_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lead = await db.get(LeadRecord, lead_id)
    if lead is None or lead.user_id != current_user.id:
        raise LeadNotFoundError(lead_id)
    return lead
