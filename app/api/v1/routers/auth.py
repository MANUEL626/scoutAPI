from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.auth import (
    ApiKeyCreateRequest,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.auth.dependencies import get_current_user
from app.auth.security import (
    create_api_key,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.config import settings
from app.db.session import get_db
from app.models.user import ApiKey, RefreshToken, User

router = APIRouter(prefix="/auth")


async def _issue_tokens(user: User, db: AsyncSession) -> TokenResponse:
    access_token, expires_in = create_access_token(user.id)
    refresh_token, refresh_expires_at = create_refresh_token(user.id)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh_token),
            expires_at=refresh_expires_at,
        )
    )
    await db.commit()
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )


async def _create_api_key(user: User, db: AsyncSession, name: str) -> ApiKeyCreatedResponse:
    api_key, key_prefix, key_hash = create_api_key()
    stored_key = ApiKey(
        user_id=user.id,
        name=name.strip() or settings.API_KEY_DEFAULT_NAME,
        key_hash=key_hash,
        key_prefix=key_prefix,
    )
    db.add(stored_key)
    await db.commit()
    await db.refresh(stored_key)
    return ApiKeyCreatedResponse(
        id=stored_key.id,
        name=stored_key.name,
        key_prefix=stored_key.key_prefix,
        created_at=stored_key.created_at,
        last_used_at=stored_key.last_used_at,
        revoked_at=stored_key.revoked_at,
        api_key=api_key,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    email = payload.email.lower()
    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    await db.flush()
    return await _issue_tokens(user, db)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")
    return await _issue_tokens(user, db)


@router.post("/login/api-key", response_model=ApiKeyCreatedResponse)
async def login_api_key(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")
    return await _create_api_key(user, db, settings.API_KEY_DEFAULT_NAME)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        decoded = decode_token(payload.refresh_token, "refresh")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    stored = await db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(payload.refresh_token))
    )
    now = datetime.now(timezone.utc)
    if stored is None or stored.revoked_at is not None or stored.expires_at <= now:
        raise HTTPException(status_code=401, detail="Refresh token revoked or expired")

    user = await db.scalar(select(User).where(User.id == decoded["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive or unknown user")

    stored.revoked_at = now
    return await _issue_tokens(user, db)


@router.post("/logout")
async def logout(payload: LogoutRequest, db: AsyncSession = Depends(get_db)):
    stored = await db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(payload.refresh_token))
    )
    if stored and stored.revoked_at is None:
        stored.revoked_at = datetime.now(timezone.utc)
        await db.commit()
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_key(
    payload: ApiKeyCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _create_api_key(current_user, db, payload.name)


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.scalars(
        select(ApiKey)
        .where(ApiKey.user_id == current_user.id, ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at.desc())
    )
    return list(result)


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stored_key = await db.scalar(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.user_id == current_user.id,
            ApiKey.revoked_at.is_(None),
        )
    )
    if stored_key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    stored_key.revoked_at = datetime.now(timezone.utc)
    await db.commit()
