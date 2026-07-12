"""Aggregate results / tallies (§8, §9, §10). Voters and creator only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..services import (
    ensure_poll_closed_if_due,
    get_poll_by_slug,
    is_banned,
    poll_status,
    tabulate_question,
    user_counted_ballot_count,
)

router = APIRouter()


@router.get("/polls/{slug}/results")
async def get_results(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    poll = await get_poll_by_slug(db, slug)
    if poll is None:
        raise HTTPException(status_code=404, detail="Poll not found")
    await ensure_poll_closed_if_due(db, poll)

    is_creator = poll.creator_id == user.id

    # Banned users see nothing (and cannot participate).
    if not is_creator and await is_banned(db, poll.id, user.id):
        raise HTTPException(status_code=403, detail="You cannot participate in this poll.")

    # Voters need >=1 counted ballot; non-voters get no results (§9).
    if not is_creator:
        counted = await user_counted_ballot_count(db, poll.id, user.id)
        if counted == 0:
            raise HTTPException(status_code=403, detail="Vote to see results.")

    questions = []
    for q in sorted(poll.questions, key=lambda x: x.position):
        tally = await tabulate_question(db, poll, q)
        questions.append(
            {
                "question_id": q.id,
                "position": q.position,
                "title": q.title,
                "description": q.description,
                "options": [
                    {"id": o.id, "label": o.label, "position": o.position}
                    for o in sorted(q.options, key=lambda o: o.position)
                ],
                "tally": tally.to_dict(),
            }
        )

    return {
        "poll": {
            "id": poll.id,
            "slug": poll.slug,
            "title": poll.title,
            "status": poll_status(poll),
        },
        "is_creator": is_creator,
        "questions": questions,
    }
