from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.property import Property, PropertyType, TransactionType
from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.scraping import PropertyRecord
from app.models.user import User
from app.services.exports import properties_to_csv
from app.utils.exceptions import PropertyNotFoundError

router = APIRouter()


@router.get(
    "/properties",
    response_model=List[Property],
    summary="Lister les biens collectes",
)
async def list_properties(
    job_id: Optional[str] = Query(None, description="Filtrer par job"),
    property_type: Optional[PropertyType] = Query(None),
    transaction_type: Optional[TransactionType] = Query(None),
    min_score: Optional[int] = Query(None, ge=0, le=100),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(PropertyRecord).where(PropertyRecord.user_id == current_user.id)
    if job_id:
        query = query.where(PropertyRecord.job_id == job_id)
    if property_type:
        query = query.where(PropertyRecord.property_type == property_type.value)
    if transaction_type:
        query = query.where(PropertyRecord.transaction_type == transaction_type.value)
    if min_score is not None:
        query = query.where(PropertyRecord.score >= min_score)
    query = query.order_by(PropertyRecord.scraped_at.desc()).limit(limit).offset(offset)
    return (await db.scalars(query)).all()


@router.get(
    "/properties/export",
    summary="Exporter les biens en CSV ou JSON",
)
async def export_properties(
    job_id: Optional[str] = Query(None, description="Filtrer par job"),
    format: str = Query("csv", pattern="^(csv|json)$"),
    limit: int = Query(1000, ge=1, le=5000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(PropertyRecord).where(PropertyRecord.user_id == current_user.id)
    if job_id:
        query = query.where(PropertyRecord.job_id == job_id)
    properties = (await db.scalars(query.order_by(PropertyRecord.scraped_at.desc()).limit(limit))).all()

    if format == "json":
        return [Property.model_validate(item).model_dump(mode="json") for item in properties]

    csv_data = properties_to_csv(list(properties))
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="scoutapi-properties.csv"'},
    )


@router.get(
    "/properties/{property_id}",
    response_model=Property,
    summary="Detail d'un bien",
)
async def get_property(
    property_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(PropertyRecord, property_id)
    if item is None or item.user_id != current_user.id:
        raise PropertyNotFoundError(property_id)
    return item
