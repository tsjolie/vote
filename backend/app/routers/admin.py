"""Admin panel: list/delete users and polls, with structured audit logs (§11)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import require_admin, require_csrf_header
from ..models import Ballot, Poll, Question, User
from ..schemas import MessageOut
from ..services import counted_ballot_count, poll_status

router = APIRouter()
audit = logging.getLogger("vote.admin")


@router.get("/admin/users")
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    total = int((await db.execute(select(func.count(User.id)))).scalar_one())
    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    users = result.scalars().all()
    rows = []
    for u in users:
        poll_count = int(
            (await db.execute(select(func.count(Poll.id)).where(Poll.creator_id == u.id))).scalar_one()
        )
        rows.append(
            {
                "id": u.id,
                "username": u.username,
                "created_at": u.created_at,
                "poll_count": poll_count,
                "is_admin": u.is_admin,
            }
        )
    return {"total": total, "page": page, "per_page": per_page, "users": rows}


@router.get("/admin/polls")
async def list_polls(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    total = int((await db.execute(select(func.count(Poll.id)))).scalar_one())
    result = await db.execute(
        select(Poll).order_by(Poll.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    polls = result.scalars().all()
    rows = []
    for p in polls:
        creator = await db.get(User, p.creator_id)
        rows.append(
            {
                "id": p.id,
                "slug": p.slug,
                "title": p.title,
                "creator": creator.username if creator else None,
                "status": poll_status(p),
                "ballot_count": await counted_ballot_count(db, p.id),
            }
        )
    return {"total": total, "page": page, "per_page": per_page, "polls": rows}


@router.delete("/admin/polls/{poll_id}", response_model=MessageOut)
async def delete_poll(
    poll_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
    _: None = Depends(require_csrf_header),
) -> MessageOut:
    poll = await db.get(Poll, poll_id)
    if poll is None:
        raise HTTPException(status_code=404, detail="Poll not found")
    await db.delete(poll)
    await db.commit()
    audit.info("admin.delete_poll admin_id=%s target_poll_id=%s", admin.id, poll_id)
    return MessageOut(detail="Poll deleted.")


@router.delete("/admin/users/{user_id}", response_model=MessageOut)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
    _: None = Depends(require_csrf_header),
) -> MessageOut:
    if user_id == admin.id:
        raise HTTPException(status_code=422, detail="Admins cannot delete themselves here.")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)  # cascades polls, ballots, sessions
    await db.commit()
    audit.info("admin.delete_user admin_id=%s target_user_id=%s", admin.id, user_id)
    return MessageOut(detail="User deleted.")
