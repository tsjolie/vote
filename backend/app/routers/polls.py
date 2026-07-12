"""Poll creation, viewing, management, and the invalidation contract (§4, §5, §9)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_db
from ..deps import get_current_user, get_optional_user, require_csrf_header
from ..models import Ballot, DisplayOrder, Option, Poll, PollBan, Question, User
from ..schemas import (
    BanRequest,
    MessageOut,
    PollCreate,
    PollMetaUpdate,
    QuestionMetaUpdate,
)
from ..services import (
    banned_user_ids,
    counted_ballot_count,
    ensure_poll_closed_if_due,
    get_poll_by_slug,
    is_banned,
    is_poll_open,
    poll_has_any_ballot,
    poll_status,
    user_counted_ballot_count,
)
from ..slug import new_slug

router = APIRouter()
log = logging.getLogger("vote.polls")


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------
def _question_public(q: Question) -> dict:
    return {
        "id": q.id,
        "position": q.position,
        "title": q.title,
        "description": q.description,
        "is_required": q.is_required,
        "options": [
            {"id": o.id, "label": o.label, "position": o.position}
            for o in sorted(q.options, key=lambda o: o.position)
        ],
    }


def _poll_meta(poll: Poll) -> dict:
    return {
        "id": poll.id,
        "slug": poll.slug,
        "title": poll.title,
        "status": poll_status(poll),
        "closes_at": poll.closes_at,
        "closed_at": poll.closed_at,
        "created_at": poll.created_at,
        "creator_username": poll.creator.username if poll.creator else None,
    }


async def _load_creator(db: AsyncSession, poll: Poll) -> Poll:
    if poll.creator is None:
        poll.creator = await db.get(User, poll.creator_id)
    return poll


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
@router.post("/polls", status_code=status.HTTP_201_CREATED)
async def create_poll(
    payload: PollCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_csrf_header),
) -> dict:
    # Generate a unique slug (retry on the astronomically-rare collision).
    for _attempt in range(10):
        slug = new_slug()
        exists = await db.execute(select(Poll.id).where(Poll.slug == slug))
        if exists.scalar_one_or_none() is None:
            break
    else:
        raise HTTPException(status_code=500, detail="Could not allocate a slug.")

    closes_at = payload.closes_at
    # A poll created with a past deadline is born closed (consistent with §5's
    # "setting closes_at in the past closes the poll").
    closed_at = None
    if closes_at is not None:
        ca = closes_at if closes_at.tzinfo else closes_at.replace(tzinfo=timezone.utc)
        if ca <= datetime.now(timezone.utc):
            closed_at = datetime.now(timezone.utc)
    poll = Poll(
        slug=slug,
        creator_id=user.id,
        title=payload.title,
        closes_at=closes_at,
        closed_at=closed_at,
    )
    db.add(poll)
    await db.flush()

    for qi, q in enumerate(payload.questions):
        question = Question(
            poll_id=poll.id,
            position=qi,
            title=q.title,
            description=q.description,
            is_required=q.is_required,
        )
        db.add(question)
        await db.flush()
        for oi, opt in enumerate(q.options):
            db.add(Option(question_id=question.id, position=oi, label=opt.label))

    await db.commit()
    await db.refresh(poll)
    return {"slug": poll.slug, "id": poll.id}


# ---------------------------------------------------------------------------
# Dashboard lists
# ---------------------------------------------------------------------------
@router.get("/polls/mine")
async def list_my_polls(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    result = await db.execute(
        select(Poll).where(Poll.creator_id == user.id).order_by(Poll.created_at.desc())
    )
    polls = result.scalars().all()
    out = []
    for poll in polls:
        out.append(
            {
                "id": poll.id,
                "slug": poll.slug,
                "title": poll.title,
                "status": poll_status(poll),
                "closes_at": poll.closes_at,
                "created_at": poll.created_at,
                "vote_count": await counted_ballot_count(db, poll.id),
            }
        )
    return out


@router.get("/polls/voted")
async def list_voted_polls(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    # Distinct polls where the user has at least one counted ballot.
    result = await db.execute(
        select(Poll)
        .join(Question, Question.poll_id == Poll.id)
        .join(Ballot, Ballot.question_id == Question.id)
        .where(Ballot.user_id == user.id, Ballot.is_invalidated.is_(False))
        .distinct()
        .order_by(Poll.created_at.desc())
    )
    polls = result.scalars().all()
    return [
        {
            "id": poll.id,
            "slug": poll.slug,
            "title": poll.title,
            "status": poll_status(poll),
            "created_at": poll.created_at,
        }
        for poll in polls
    ]


# ---------------------------------------------------------------------------
# Poll view (drives /p/{slug} routing in the SPA)
# ---------------------------------------------------------------------------
@router.get("/polls/{slug}")
async def get_poll(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    poll = await get_poll_by_slug(db, slug)
    if poll is None:
        raise HTTPException(status_code=404, detail="Poll not found")
    await ensure_poll_closed_if_due(db, poll)
    await _load_creator(db, poll)

    is_creator = poll.creator_id == user.id
    banned = await is_banned(db, poll.id, user.id)

    if banned and not is_creator:
        return {"poll": _poll_meta(poll), "viewer_role": "banned"}

    # Per-question status for this viewer.
    ballots_res = await db.execute(
        select(Ballot)
        .join(Question, Ballot.question_id == Question.id)
        .where(Question.poll_id == poll.id, Ballot.user_id == user.id)
    )
    my_ballots = {b.question_id: b for b in ballots_res.scalars().all()}

    questions = []
    for q in sorted(poll.questions, key=lambda x: x.position):
        b = my_ballots.get(q.id)
        if b is None:
            qstatus = "none"
        elif b.is_invalidated:
            qstatus = "invalidated"
        else:
            qstatus = "answered"
        questions.append({**_question_public(q), "my_status": qstatus})

    my_counted = sum(1 for q in questions if q["my_status"] == "answered")
    required_remaining = [
        q for q in questions if q["is_required"] and q["my_status"] != "answered"
    ]

    if is_creator:
        role = "creator"
    elif my_counted > 0 and not required_remaining:
        role = "voter"  # done; SPA shows results (can still revisit to change)
    elif my_counted > 0:
        role = "voter_incomplete"
    else:
        role = "non_voter"

    return {
        "poll": _poll_meta(poll),
        "viewer_role": role,
        "is_creator": is_creator,
        "questions": questions,
        "my_counted_ballots": my_counted,
        "questions_locked": await poll_has_any_ballot(db, poll.id),
    }


# ---------------------------------------------------------------------------
# Meta edit (consequence-free): title + closes_at (§5)
# ---------------------------------------------------------------------------
async def _require_creator(db: AsyncSession, slug: str, user: User) -> Poll:
    poll = await get_poll_by_slug(db, slug)
    if poll is None:
        raise HTTPException(status_code=404, detail="Poll not found")
    if poll.creator_id != user.id:
        raise HTTPException(status_code=403, detail="Only the creator can manage this poll.")
    await ensure_poll_closed_if_due(db, poll)
    return poll


@router.put("/polls/{slug}/meta", response_model=MessageOut)
async def update_poll_meta(
    slug: str,
    payload: PollMetaUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_csrf_header),
) -> MessageOut:
    poll = await _require_creator(db, slug, user)
    if poll.closed_at is not None:
        raise HTTPException(status_code=409, detail="Poll is closed.")

    if payload.title is not None:
        poll.title = payload.title
    if payload.clear_closes_at:
        poll.closes_at = None
    elif payload.closes_at is not None:
        poll.closes_at = payload.closes_at
        # Setting closes_at in the past closes the poll (§5).
        ca = payload.closes_at
        if ca.tzinfo is None:
            ca = ca.replace(tzinfo=timezone.utc)
        if ca <= datetime.now(timezone.utc):
            poll.closed_at = datetime.now(timezone.utc)
    await db.commit()
    return MessageOut(detail="Poll updated.")


# ---------------------------------------------------------------------------
# Question edit — the invalidation contract (§5)
# ---------------------------------------------------------------------------
def _labels_ordered(options: list[Option]) -> list[str]:
    return [o.label for o in sorted(options, key=lambda o: o.position)]


@router.put("/polls/{slug}/questions/{question_id}")
async def update_question(
    slug: str,
    question_id: str,
    payload: QuestionMetaUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_csrf_header),
) -> dict:
    poll = await _require_creator(db, slug, user)
    if not is_poll_open(poll):
        raise HTTPException(status_code=409, detail="Poll is closed; questions cannot be edited.")

    question = next((q for q in poll.questions if q.id == question_id), None)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    invalidating = False

    # Title change invalidates.
    if payload.title is not None and payload.title != question.title:
        question.title = payload.title
        invalidating = True

    # Description and is_required are consequence-free.
    if payload.description is not None:
        question.description = payload.description or None
    if payload.is_required is not None:
        question.is_required = payload.is_required

    # Options: full replacement. Any add/remove/rename/reorder invalidates.
    if payload.options is not None:
        new_labels = [o.label for o in payload.options]
        old_labels = _labels_ordered(question.options)
        if new_labels != old_labels:
            invalidating = True
            # Replace option rows entirely.
            await db.execute(delete(Option).where(Option.question_id == question.id))
            for i, opt in enumerate(payload.options):
                db.add(Option(question_id=question.id, position=i, label=opt.label))

    invalidated_count = 0
    if invalidating:
        # Invalidate every ballot on this question and drop stored display orders.
        res = await db.execute(
            select(func.count(Ballot.id)).where(
                Ballot.question_id == question.id, Ballot.is_invalidated.is_(False)
            )
        )
        invalidated_count = int(res.scalar_one())
        await db.execute(
            Ballot.__table__.update()
            .where(Ballot.question_id == question.id)
            .values(is_invalidated=True)
        )
        await db.execute(delete(DisplayOrder).where(DisplayOrder.question_id == question.id))

    await db.commit()
    return {"detail": "Question updated.", "invalidated_ballots": invalidated_count}


@router.get("/polls/{slug}/questions/{question_id}/impact")
async def question_edit_impact(
    slug: str,
    question_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """How many ballots an invalidating edit would affect (drives the warning)."""
    poll = await _require_creator(db, slug, user)
    # Confirm the question belongs to this poll (avoid cross-poll counts).
    if not any(q.id == question_id for q in poll.questions):
        raise HTTPException(status_code=404, detail="Question not found")
    res = await db.execute(
        select(func.count(Ballot.id)).where(
            Ballot.question_id == question_id, Ballot.is_invalidated.is_(False)
        )
    )
    return {"ballots_to_invalidate": int(res.scalar_one())}


# ---------------------------------------------------------------------------
# Close / delete
# ---------------------------------------------------------------------------
@router.post("/polls/{slug}/close", response_model=MessageOut)
async def close_poll(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_csrf_header),
) -> MessageOut:
    poll = await _require_creator(db, slug, user)
    if poll.closed_at is not None:
        raise HTTPException(status_code=409, detail="Poll is already closed.")
    poll.closed_at = datetime.now(timezone.utc)
    await db.commit()
    return MessageOut(detail="Poll closed.")


@router.delete("/polls/{slug}", response_model=MessageOut)
async def delete_poll(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_csrf_header),
) -> MessageOut:
    poll = await _require_creator(db, slug, user)
    await db.delete(poll)  # cascades questions/options/ballots/bans
    await db.commit()
    return MessageOut(detail="Poll deleted.")


# ---------------------------------------------------------------------------
# Creator: voter table, invalidate ballot, ban/unban (§9)
# ---------------------------------------------------------------------------
@router.get("/polls/{slug}/voters")
async def voter_table(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    poll = await _require_creator(db, slug, user)
    banned = await banned_user_ids(db, poll.id)

    rows_res = await db.execute(
        select(Ballot, User.username, Question.position, Question.id)
        .join(Question, Ballot.question_id == Question.id)
        .join(User, Ballot.user_id == User.id)
        .where(Question.poll_id == poll.id)
        .order_by(Question.position, User.username)
    )
    per_question: dict[str, list] = {}
    for ballot, username, qpos, qid in rows_res.all():
        per_question.setdefault(qid, []).append(
            {
                "ballot_id": ballot.id,
                "user_id": ballot.user_id,
                "username": username,
                "ranking": ballot.ranking,
                "is_invalidated": ballot.is_invalidated,
                "is_banned": ballot.user_id in banned,
                "submitted_at": ballot.submitted_at,
            }
        )

    return {
        "banned_user_ids": sorted(banned),
        "questions": [
            {
                "question_id": q.id,
                "position": q.position,
                "title": q.title,
                "options": [
                    {"id": o.id, "label": o.label}
                    for o in sorted(q.options, key=lambda o: o.position)
                ],
                "ballots": per_question.get(q.id, []),
            }
            for q in sorted(poll.questions, key=lambda x: x.position)
        ],
    }


@router.post("/polls/{slug}/ballots/{ballot_id}/invalidate", response_model=MessageOut)
async def invalidate_ballot(
    slug: str,
    ballot_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_csrf_header),
) -> MessageOut:
    poll = await _require_creator(db, slug, user)
    ballot = await db.get(Ballot, ballot_id)
    if ballot is None:
        raise HTTPException(status_code=404, detail="Ballot not found")
    question = await db.get(Question, ballot.question_id)
    if question is None or question.poll_id != poll.id:
        raise HTTPException(status_code=404, detail="Ballot not in this poll")
    ballot.is_invalidated = True
    # Voter may re-vote: drop the stale display order so they get a fresh list.
    await db.execute(
        delete(DisplayOrder).where(
            DisplayOrder.question_id == ballot.question_id,
            DisplayOrder.user_id == ballot.user_id,
        )
    )
    await db.commit()
    return MessageOut(detail="Ballot invalidated.")


@router.post("/polls/{slug}/bans", response_model=MessageOut)
async def ban_user(
    slug: str,
    payload: BanRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_csrf_header),
) -> MessageOut:
    poll = await _require_creator(db, slug, user)
    target_id = payload.user_id
    if target_id == poll.creator_id:
        raise HTTPException(status_code=422, detail="Cannot ban the creator.")
    # The target must be a real user (avoids storing bans for arbitrary strings).
    if await db.get(User, target_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    existing = await db.execute(
        select(PollBan.id).where(PollBan.poll_id == poll.id, PollBan.user_id == target_id)
    )
    if existing.scalar_one_or_none() is None:
        db.add(PollBan(poll_id=poll.id, user_id=target_id))
        await db.commit()
    return MessageOut(detail="User banned from poll.")


@router.delete("/polls/{slug}/bans/{user_id}", response_model=MessageOut)
async def unban_user(
    slug: str,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_csrf_header),
) -> MessageOut:
    poll = await _require_creator(db, slug, user)
    await db.execute(
        delete(PollBan).where(PollBan.poll_id == poll.id, PollBan.user_id == user_id)
    )
    await db.commit()
    return MessageOut(detail="User un-banned.")
