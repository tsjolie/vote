"""SQLAlchemy ORM models — see instructions.md §3."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .types import GUID, JSONType


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(20), nullable=False)
    username_lower: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    polls: Mapped[list["Poll"]] = relationship(back_populates="creator", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # opaque 256-bit token (hex)
    user_id: Mapped[str] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Poll(Base):
    __tablename__ = "polls"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    creator_id: Mapped[str] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    creator: Mapped[User] = relationship(back_populates="polls")
    questions: Mapped[list["Question"]] = relationship(back_populates="poll", cascade="all, delete-orphan", order_by="Question.position")
    bans: Mapped[list["PollBan"]] = relationship(back_populates="poll", cascade="all, delete-orphan")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=_uuid)
    poll_id: Mapped[str] = mapped_column(GUID(), ForeignKey("polls.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    poll: Mapped[Poll] = relationship(back_populates="questions")
    options: Mapped[list["Option"]] = relationship(back_populates="question", cascade="all, delete-orphan", order_by="Option.position")
    ballots: Mapped[list["Ballot"]] = relationship(back_populates="question", cascade="all, delete-orphan")


class Option(Base):
    __tablename__ = "options"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=_uuid)
    question_id: Mapped[str] = mapped_column(GUID(), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    question: Mapped[Question] = relationship(back_populates="options")


class Ballot(Base):
    __tablename__ = "ballots"
    __table_args__ = (UniqueConstraint("question_id", "user_id", name="uq_ballot_question_user"),)

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=_uuid)
    question_id: Mapped[str] = mapped_column(GUID(), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ranking: Mapped[list] = mapped_column(JSONType, nullable=False)  # ordered list of option ids
    is_invalidated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    question: Mapped[Question] = relationship(back_populates="ballots")


class PollBan(Base):
    __tablename__ = "poll_bans"
    __table_args__ = (UniqueConstraint("poll_id", "user_id", name="uq_poll_ban"),)

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=_uuid)
    poll_id: Mapped[str] = mapped_column(GUID(), ForeignKey("polls.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    poll: Mapped[Poll] = relationship(back_populates="bans")


class DisplayOrder(Base):
    __tablename__ = "display_orders"
    __table_args__ = (UniqueConstraint("question_id", "user_id", name="uq_display_order"),)

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=_uuid)
    question_id: Mapped[str] = mapped_column(GUID(), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order: Mapped[list] = mapped_column(JSONType, nullable=False)  # ordered list of option ids
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
