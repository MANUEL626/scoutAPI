from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.signal import Signal, SignalCategory, SignalIntent
from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.scraping import SignalRecord
from app.models.user import User
from app.utils.exceptions import SignalNotFoundError

router = APIRouter()


@router.get("/signals", response_model=List[Signal], summary="Lister les signaux publics")
async def list_signals(
    job_id: Optional[str] = Query(None),
    signal_category: Optional[SignalCategory] = Query(None),
    signal_intent: Optional[SignalIntent] = Query(None),
    source: Optional[str] = Query(None),
    min_confidence: Optional[int] = Query(None, ge=0, le=100),
    has_valid_contact: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(SignalRecord).where(SignalRecord.user_id == current_user.id)
    if job_id:
        query = query.where(SignalRecord.job_id == job_id)
    if signal_category:
        query = query.where(SignalRecord.signal_category == signal_category.value)
    if signal_intent:
        query = query.where(SignalRecord.signal_intent == signal_intent.value)
    if source:
        query = query.where(SignalRecord.source == source.lower())
    if min_confidence is not None:
        query = query.where(SignalRecord.confidence_score >= min_confidence)
    if has_valid_contact is not None:
        query = query.where(SignalRecord.has_valid_contact == has_valid_contact)
    query = query.order_by(SignalRecord.scraped_at.desc()).limit(limit).offset(offset)
    return (await db.scalars(query)).all()


@router.get("/signals/{signal_id}", response_model=Signal, summary="Detail d'un signal public")
async def get_signal(
    signal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    signal = await db.get(SignalRecord, signal_id)
    if signal is None or signal.user_id != current_user.id:
        raise SignalNotFoundError(signal_id)
    return signal
