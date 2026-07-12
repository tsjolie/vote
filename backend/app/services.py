"""Shared domain logic: poll status, lazy close, ballot gathering, tabulation."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Ballot, Option, Poll, PollBan, Question
from .tabulator import TallyResult, tabulate


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def ensure_poll_closed_if_due(db: AsyncSession, poll: Poll) -> Poll:
    """Lazy close: set closed_at when closes_at has passed (§4)."""
    if poll.closed_at is None:
        closes_at = _aware(poll.closes_at)
        if closes_at is not None and closes_at <= datetime.now(timezone.utc):
            poll.closed_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(poll)
    return poll


def poll_status(poll: Poll) -> str:
    if poll.closed_at is not None:
        return "closed"
    closes_at = _aware(poll.closes_at)
    if closes_at is not None and closes_at <= datetime.now(timezone.utc):
        return "closed"
    return "open"


def is_poll_open(poll: Poll) -> bool:
    return poll_status(poll) == "open"


async def get_poll_by_slug(db: AsyncSession, slug: str) -> Poll | None:
    result = await db.execute(
        select(Poll)
        .where(Poll.slug == slug)
        .options(
            selectinload(Poll.creator),
            selectinload(Poll.questions).selectinload(Question.options),
        )
    )
    return result.scalar_one_or_none()


async def is_banned(db: AsyncSession, poll_id: str, user_id: str) -> bool:
    result = await db.execute(
        select(PollBan.id).where(
            PollBan.poll_id == poll_id, PollBan.user_id == user_id
        )
    )
    return result.scalar_one_or_none() is not None


async def banned_user_ids(db: AsyncSession, poll_id: str) -> set[str]:
    result = await db.execute(
        select(PollBan.user_id).where(PollBan.poll_id == poll_id)
    )
    return {row[0] for row in result.all()}


async def poll_has_any_ballot(db: AsyncSession, poll_id: str) -> bool:
    result = await db.execute(
        select(Ballot.id)
        .join(Question, Ballot.question_id == Question.id)
        .where(Question.poll_id == poll_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def user_counted_ballot_count(db: AsyncSession, poll_id: str, user_id: str) -> int:
    """How many non-invalidated ballots this user has across the poll."""
    result = await db.execute(
        select(func.count(Ballot.id))
        .join(Question, Ballot.question_id == Question.id)
        .where(
            Question.poll_id == poll_id,
            Ballot.user_id == user_id,
            Ballot.is_invalidated.is_(False),
        )
    )
    return int(result.scalar_one())


async def counted_ballot_count(db: AsyncSession, poll_id: str) -> int:
    """Total counted ballots in the poll, excluding banned users."""
    banned = await banned_user_ids(db, poll_id)
    stmt = (
        select(func.count(Ballot.id))
        .join(Question, Ballot.question_id == Question.id)
        .where(Question.poll_id == poll_id, Ballot.is_invalidated.is_(False))
    )
    if banned:
        stmt = stmt.where(Ballot.user_id.notin_(banned))
    result = await db.execute(stmt)
    return int(result.scalar_one())


async def tabulate_question(db: AsyncSession, poll: Poll, question: Question) -> TallyResult:
    """Gather counted ballots for a question and run the tabulator (§8)."""
    banned = await banned_user_ids(db, poll.id)
    result = await db.execute(
        select(Ballot).where(
            Ballot.question_id == question.id,
            Ballot.is_invalidated.is_(False),
        )
    )
    ballots = [
        b.ranking
        for b in result.scalars().all()
        if b.user_id not in banned
    ]
    option_ids = [o.id for o in question.options]
    # Defensively drop any ballots that are not full permutations of current options
    # (should not happen given the invalidation contract, but keeps tally sane).
    opt_set = set(option_ids)
    clean = [r for r in ballots if isinstance(r, list) and set(r) == opt_set]
    return tabulate(option_ids, clean, poll.id, question.id)
