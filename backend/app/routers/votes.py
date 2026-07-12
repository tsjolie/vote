"""Voting flow: randomized presentation order, ballot submit, skip (§6, §7)."""

from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_user, require_csrf_header
from ..models import Ballot, DisplayOrder, Option, Poll, Question, User
from ..schemas import BallotSubmit, MessageOut
from ..services import (
    ensure_poll_closed_if_due,
    get_poll_by_slug,
    is_banned,
    is_poll_open,
)

router = APIRouter()


async def _load_question(db: AsyncSession, slug: str, question_id: str) -> tuple[Poll, Question]:
    poll = await get_poll_by_slug(db, slug)
    if poll is None:
        raise HTTPException(status_code=404, detail="Poll not found")
    await ensure_poll_closed_if_due(db, poll)
    question = next((q for q in poll.questions if q.id == question_id), None)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return poll, question


@router.get("/polls/{slug}/questions/{question_id}/vote")
async def get_vote_view(
    slug: str,
    question_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    poll, question = await _load_question(db, slug, question_id)
    if await is_banned(db, poll.id, user.id) and poll.creator_id != user.id:
        raise HTTPException(status_code=403, detail="You cannot participate in this poll.")

    options = {o.id: o for o in question.options}
    option_ids = [o.id for o in sorted(question.options, key=lambda o: o.position)]

    # Existing (valid) ballot -> show the voter's own submitted ranking (§7).
    ballot_res = await db.execute(
        select(Ballot).where(
            Ballot.question_id == question.id, Ballot.user_id == user.id
        )
    )
    ballot = ballot_res.scalar_one_or_none()
    if ballot is not None and not ballot.is_invalidated:
        # Guard against any drift between ranking and current options.
        if set(ballot.ranking) == set(option_ids):
            order = ballot.ranking
        else:
            order = option_ids
        return {
            "question": _q(question),
            "order": [_opt(options[o]) for o in order],
            "my_status": "answered",
        }

    # First unvoted view -> generate & persist a random permutation (§7).
    do_res = await db.execute(
        select(DisplayOrder).where(
            DisplayOrder.question_id == question.id, DisplayOrder.user_id == user.id
        )
    )
    display = do_res.scalar_one_or_none()
    if display is None or set(display.order) != set(option_ids):
        shuffled = option_ids[:]
        random.shuffle(shuffled)
        if display is not None:
            await db.delete(display)
            await db.flush()
        db.add(DisplayOrder(question_id=question.id, user_id=user.id, order=shuffled))
        try:
            await db.commit()
            order = shuffled
        except IntegrityError:
            # A concurrent first-view already persisted an order; reuse it (§7's
            # "consistent across refreshes and devices").
            await db.rollback()
            do_res = await db.execute(
                select(DisplayOrder).where(
                    DisplayOrder.question_id == question.id,
                    DisplayOrder.user_id == user.id,
                )
            )
            display = do_res.scalar_one_or_none()
            order = display.order if display is not None else shuffled
    else:
        order = display.order

    return {
        "question": _q(question),
        "order": [_opt(options[o]) for o in order],
        "my_status": "invalidated" if ballot is not None else "none",
    }


@router.post("/polls/{slug}/questions/{question_id}/ballot", response_model=MessageOut)
async def submit_ballot(
    slug: str,
    question_id: str,
    payload: BallotSubmit,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_csrf_header),
) -> MessageOut:
    poll, question = await _load_question(db, slug, question_id)

    if not is_poll_open(poll):
        raise HTTPException(status_code=409, detail="This poll is closed.")
    if await is_banned(db, poll.id, user.id):
        raise HTTPException(status_code=403, detail="You cannot participate in this poll.")

    option_ids = {o.id for o in question.options}
    ranking = payload.ranking
    # Must be a full permutation of exactly the current option ids (§6).
    if (
        len(ranking) != len(option_ids)
        or len(set(ranking)) != len(ranking)
        or set(ranking) != option_ids
    ):
        raise HTTPException(
            status_code=409,
            detail="This question changed, please re-rank.",
        )

    existing = await db.execute(
        select(Ballot).where(
            Ballot.question_id == question.id, Ballot.user_id == user.id
        )
    )
    ballot = existing.scalar_one_or_none()
    if ballot is None:
        db.add(Ballot(question_id=question.id, user_id=user.id, ranking=ranking))
        try:
            await db.commit()
        except IntegrityError:
            # Concurrent first submit for the same (question, user); fall back to
            # updating the row that won the race so the request still succeeds.
            await db.rollback()
            existing = await db.execute(
                select(Ballot).where(
                    Ballot.question_id == question.id, Ballot.user_id == user.id
                )
            )
            ballot = existing.scalar_one_or_none()
            if ballot is None:
                raise HTTPException(status_code=409, detail="Please retry.")
            ballot.ranking = ranking
            ballot.is_invalidated = False
            await db.commit()
    else:
        ballot.ranking = ranking
        ballot.is_invalidated = False  # re-voting clears invalidation (§6)
        await db.commit()
    return MessageOut(detail="Ballot recorded.")


@router.post("/polls/{slug}/questions/{question_id}/skip", response_model=MessageOut)
async def skip_question(
    slug: str,
    question_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_csrf_header),
) -> MessageOut:
    poll, question = await _load_question(db, slug, question_id)
    if question.is_required:
        raise HTTPException(status_code=422, detail="Required questions cannot be skipped.")
    # Skipping leaves no ballot row (§6). Nothing to persist.
    return MessageOut(detail="Question skipped.")


# --- small serializers -----------------------------------------------------
def _opt(o: Option) -> dict:
    return {"id": o.id, "label": o.label, "position": o.position}


def _q(q: Question) -> dict:
    return {
        "id": q.id,
        "position": q.position,
        "title": q.title,
        "description": q.description,
        "is_required": q.is_required,
        "option_count": len(q.options),
    }
