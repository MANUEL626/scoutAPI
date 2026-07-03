from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_token, hash_token
from app.config import settings
from app.db.session import get_db
from app.models.user import ApiKey, User

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def _get_user_from_api_key(api_key: str, db: AsyncSession) -> User:
    stored_key = await db.scalar(
        select(ApiKey).where(
            ApiKey.key_hash == hash_token(api_key),
            ApiKey.revoked_at.is_(None),
        )
    )
    if stored_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    user = await db.scalar(select(User).where(User.id == stored_key.user_id))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive or unknown user",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    stored_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_api_key: str | None = Depends(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> User:
    if x_api_key:
        return await _get_user_from_api_key(x_api_key, db)

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token or API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.credentials.startswith(settings.API_KEY_PREFIX):
        return await _get_user_from_api_key(credentials.credentials, db)

    try:
        payload = decode_token(credentials.credentials, "access")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await db.scalar(select(User).where(User.id == payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive or unknown user",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
