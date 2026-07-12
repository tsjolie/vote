"""Pydantic request/response schemas and validation helpers."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    username: str
    password: str
    password_confirm: str

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        if not USERNAME_RE.match(v):
            raise ValueError("Username must be 3–20 chars of letters, numbers, or underscore.")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if not (8 <= len(v) <= 128):
            raise ValueError("Password must be 8–128 characters.")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    is_admin: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Poll creation / editing
# ---------------------------------------------------------------------------
class OptionIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)


class QuestionIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=2000)
    is_required: bool = True
    options: list[OptionIn] = Field(max_length=10)

    @field_validator("options")
    @classmethod
    def _options(cls, v: list[OptionIn]) -> list[OptionIn]:
        if not (2 <= len(v) <= 10):
            raise ValueError("Each question needs 2–10 options.")
        return v


class PollCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    closes_at: Optional[datetime] = None
    questions: list[QuestionIn] = Field(max_length=20)

    @field_validator("questions")
    @classmethod
    def _questions(cls, v: list[QuestionIn]) -> list[QuestionIn]:
        if not (1 <= len(v) <= 20):
            raise ValueError("A poll needs 1–20 questions.")
        return v


class PollMetaUpdate(BaseModel):
    """Consequence-free edits: poll title and closes_at (§5)."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    closes_at: Optional[datetime] = None
    clear_closes_at: bool = False


class QuestionMetaUpdate(BaseModel):
    """Description is free; title/options changes invalidate ballots (§5)."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=2000)
    is_required: Optional[bool] = None
    options: Optional[list[OptionIn]] = Field(default=None, max_length=10)  # full replacement set

    @field_validator("options")
    @classmethod
    def _options(cls, v: Optional[list[OptionIn]]) -> Optional[list[OptionIn]]:
        if v is not None and not (2 <= len(v) <= 10):
            raise ValueError("Each question needs 2–10 options.")
        return v


# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------
class BallotSubmit(BaseModel):
    # Full permutation of the question's current option ids. Options are capped at
    # 10 per question, so 25 is a generous bound that rejects absurd arrays before
    # the permutation check runs.
    ranking: list[str] = Field(max_length=25)


class BanRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)


# ---------------------------------------------------------------------------
# Output shapes
# ---------------------------------------------------------------------------
class OptionOut(BaseModel):
    id: str
    label: str
    position: int


class QuestionOut(BaseModel):
    id: str
    position: int
    title: str
    description: Optional[str]
    is_required: bool
    options: list[OptionOut]


class PollSummary(BaseModel):
    id: str
    slug: str
    title: str
    status: str  # "open" | "closed"
    closes_at: Optional[datetime]
    closed_at: Optional[datetime]
    created_at: datetime
    vote_count: int


class MessageOut(BaseModel):
    detail: str
