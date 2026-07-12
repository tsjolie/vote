"""Authentication: register, login, logout, session (me). See §2."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user, require_csrf_header
from ..models import Session as SessionModel
from ..models import User
from ..schemas import LoginRequest, MessageOut, RegisterRequest, UserOut
from ..security import (
    hash_password,
    needs_rehash,
    new_session_token,
    session_expiry,
    verify_password,
)

router = APIRouter()
settings = get_settings()
auth_log = logging.getLogger("vote.auth")


def _client_ip(request: Request) -> str:
    """Real client IP, trusting Traefik's X-Forwarded-For (§2, §12)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


async def _create_session(db: AsyncSession, user: User, response: Response) -> None:
    token = new_session_token()
    session = SessionModel(
        id=token,
        user_id=user.id,
        expires_at=session_expiry(settings.session_ttl_days),
    )
    db.add(session)
    await db.commit()
    _set_session_cookie(response, token)


@router.post("/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_csrf_header),
) -> UserOut:
    if payload.password != payload.password_confirm:
        raise HTTPException(status_code=422, detail="Passwords do not match.")
    if payload.password.lower() == payload.username.lower():
        raise HTTPException(status_code=422, detail="Password must not equal the username.")

    username_lower = payload.username.lower()
    existing = await db.execute(select(User.id).where(User.username_lower == username_lower))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Username is taken.")

    user = User(
        username=payload.username,
        username_lower=username_lower,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await _create_session(db, user, response)
    return UserOut(id=user.id, username=user.username, is_admin=user.is_admin, created_at=user.created_at)


@router.post("/auth/login", response_model=UserOut)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_csrf_header),
) -> UserOut:
    result = await db.execute(select(User).where(User.username_lower == payload.username.lower()))
    user = result.scalar_one_or_none()
    # Generic failure; do not reveal whether the username exists (§2).
    if user is None or not verify_password(user.password_hash, payload.password):
        auth_log.warning(
            "auth.login.failure username=%r ip=%s", payload.username, _client_ip(request)
        )
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
        await db.commit()

    await _create_session(db, user, response)  # rotate session on login (§1)
    auth_log.info("auth.login.success user_id=%s ip=%s", user.id, _client_ip(request))
    return UserOut(id=user.id, username=user.username, is_admin=user.is_admin, created_at=user.created_at)


@router.post("/auth/logout", response_model=MessageOut)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_csrf_header),
) -> MessageOut:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        session = await db.get(SessionModel, token)
        if session is not None:
            await db.delete(session)
            await db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    return MessageOut(detail="Logged out.")


@router.get("/auth/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, username=user.username, is_admin=user.is_admin, created_at=user.created_at)
