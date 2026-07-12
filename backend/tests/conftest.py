"""Integration-test fixtures.

Runs the real FastAPI app against an in-memory SQLite database (a single shared
connection via StaticPool). Postgres-specific types fall back to portable ones
(see app/types.py), so the same routers/services are exercised end to end.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("COOKIE_SECURE", "false")

import tempfile

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import Base, get_db
from app.main import api, app

# A shared temp file (not :memory:) so out-of-band assertion sessions and the
# app's request sessions see the same database. NullPool means each session opens
# its own connection to that file.
_db_fd, _DB_PATH = tempfile.mkstemp(suffix=".sqlite")
os.close(_db_fd)

test_engine = create_async_engine(
    f"sqlite+aiosqlite:///{_DB_PATH}",
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
)


# SQLite disables foreign-key enforcement by default, so ON DELETE CASCADE (which
# Postgres uses in production) would be silently skipped and cascade-delete tests
# would prove nothing. Turn it on for every connection.
@event.listens_for(test_engine.sync_engine, "connect")
def _enable_sqlite_fk(dbapi_conn, _record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestSession = async_sessionmaker(test_engine, expire_on_commit=False)


async def _override_get_db():
    async with TestSession() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def _reset_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def client():
    api.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    api.dependency_overrides.clear()


# --- helpers ---------------------------------------------------------------
CSRF = {"X-Requested-With": "fetch"}


async def register(client: AsyncClient, username: str, password: str = "password123"):
    return await client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password, "password_confirm": password},
        headers=CSRF,
    )


async def login(client: AsyncClient, username: str, password: str = "password123"):
    return await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers=CSRF,
    )


async def logout(client: AsyncClient):
    return await client.post("/api/v1/auth/logout", headers=CSRF)


def sample_poll(title="Favorite color", n_questions=1, n_options=3, required=True):
    return {
        "title": title,
        "closes_at": None,
        "questions": [
            {
                "title": f"Question {qi + 1}",
                "description": None,
                "is_required": required,
                "options": [{"label": f"Opt {oi + 1}"} for oi in range(n_options)],
            }
            for qi in range(n_questions)
        ],
    }
