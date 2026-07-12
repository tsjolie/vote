"""Security hardening & edge-case tests (path traversal, injection, bounds,
cascades, concurrency, permission matrix)."""

from __future__ import annotations

import os

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.main import add_spa_fallback, resolve_static_file
from app.models import Ballot, DisplayOrder, Option, Poll, PollBan, Question
from app.models import Session as SessionModel
from app.models import User
from tests.conftest import CSRF, TestSession, login, logout, register, sample_poll


# ---------------------------------------------------------------------------
# Path traversal (SPA fallback)
# ---------------------------------------------------------------------------
def test_resolve_static_file_blocks_traversal(tmp_path):
    root = tmp_path / "static"
    root.mkdir()
    (root / "index.html").write_text("INDEX")
    (root / "app.js").write_text("APP")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET")

    # Legitimate files resolve.
    assert resolve_static_file(str(root), "app.js") == os.path.realpath(root / "app.js")
    # Traversal attempts resolve to None (fall back to index).
    assert resolve_static_file(str(root), "../secret.txt") is None
    assert resolve_static_file(str(root), "../../secret.txt") is None
    assert resolve_static_file(str(root), "..") is None
    assert resolve_static_file(str(root), "/etc/passwd") is None
    assert resolve_static_file(str(root), "") is None
    # Nonexistent file inside root -> None (SPA route -> index fallback).
    assert resolve_static_file(str(root), "deep/link/route") is None


async def test_spa_fallback_never_serves_outside_root(tmp_path):
    root = tmp_path / "static"
    root.mkdir()
    (root / "index.html").write_text("INDEX")
    (tmp_path / "secret.txt").write_text("TOP SECRET")

    spa_app = FastAPI()
    add_spa_fallback(spa_app, str(root))
    transport = ASGITransport(app=spa_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for path in [
            "/%2e%2e/secret.txt",
            "/%2e%2e%2f%2e%2e%2fsecret.txt",
            "/static/../secret.txt",
            "/some/spa/route",
        ]:
            r = await c.get(path)
            assert "TOP SECRET" not in r.text, path
        # A deep SPA link returns index.html (history fallback).
        assert (await c.get("/p/abc123")).text == "INDEX"


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------
async def test_security_headers_present(client):
    r = await client.get("/api/v1")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "no-referrer"


# ---------------------------------------------------------------------------
# Body-size limit (unbounded-input / overflow analog)
# ---------------------------------------------------------------------------
async def test_oversized_body_rejected(client):
    huge = "x" * (70 * 1024)  # > 64 KiB cap
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "a", "password": huge},
        headers=CSRF,
    )
    assert r.status_code == 413


# ---------------------------------------------------------------------------
# SQL-injection strings round-trip as inert data
# ---------------------------------------------------------------------------
async def test_sqli_strings_are_inert(client):
    await register(client, "Owner")
    evil_title = "Robert'); DROP TABLE polls;--"
    evil_label = "\" OR 1=1; --"
    payload = {
        "title": evil_title,
        "closes_at": None,
        "questions": [
            {
                "title": "Q",
                "description": None,
                "is_required": True,
                "options": [{"label": evil_label}, {"label": "safe"}],
            }
        ],
    }
    r = await client.post("/api/v1/polls", json=payload, headers=CSRF)
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]

    view = await client.get(f"/api/v1/polls/{slug}")
    assert view.json()["poll"]["title"] == evil_title
    assert view.json()["questions"][0]["options"][0]["label"] == evil_label

    # The polls table still exists and is queryable.
    assert (await client.get("/api/v1/polls/mine")).status_code == 200


# ---------------------------------------------------------------------------
# Boundary values
# ---------------------------------------------------------------------------
async def _try_register(client, username, password):
    return await client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password, "password_confirm": password},
        headers=CSRF,
    )


async def test_username_length_boundaries(client):
    assert (await _try_register(client, "ab", "password123")).status_code == 422
    assert (await _try_register(client, "abc", "password123")).status_code == 201
    await logout(client)
    assert (await _try_register(client, "a" * 20, "password123")).status_code == 201
    await logout(client)
    assert (await _try_register(client, "a" * 21, "password123")).status_code == 422


async def test_password_length_boundaries(client):
    assert (await _try_register(client, "userA", "1234567")).status_code == 422  # 7
    assert (await _try_register(client, "userB", "12345678")).status_code == 201  # 8
    await logout(client)
    assert (await _try_register(client, "userC", "x" * 128)).status_code == 201
    await logout(client)
    assert (await _try_register(client, "userD", "x" * 129)).status_code == 422


async def test_password_equals_username_case_insensitive(client):
    r = await _try_register(client, "SameName", "samename")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Ballot validation edge cases
# ---------------------------------------------------------------------------
async def _make_poll(client, **kw):
    r = await client.post("/api/v1/polls", json=sample_poll(**kw), headers=CSRF)
    assert r.status_code == 201, r.text
    return r.json()["slug"]


async def test_duplicate_and_foreign_ids_rejected(client):
    await register(client, "Owner")
    slug = await _make_poll(client, n_options=3)
    q = (await client.get(f"/api/v1/polls/{slug}")).json()["questions"][0]
    opt_ids = [o["id"] for o in q["options"]]

    # duplicate id
    dup = [opt_ids[0], opt_ids[0], opt_ids[1]]
    r = await client.post(
        f"/api/v1/polls/{slug}/questions/{q['id']}/ballot", json={"ranking": dup}, headers=CSRF
    )
    assert r.status_code == 409

    # foreign id swapped in
    foreign = [opt_ids[0], opt_ids[1], "not-a-real-option"]
    r = await client.post(
        f"/api/v1/polls/{slug}/questions/{q['id']}/ballot", json={"ranking": foreign}, headers=CSRF
    )
    assert r.status_code == 409

    # absurdly long ranking is rejected by the schema cap (422) before logic runs.
    r = await client.post(
        f"/api/v1/polls/{slug}/questions/{q['id']}/ballot",
        json={"ranking": [f"x{i}" for i in range(100)]},
        headers=CSRF,
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# closes_at in the past closes the poll
# ---------------------------------------------------------------------------
async def test_past_closes_at_closes_poll(client):
    await register(client, "Owner")
    payload = sample_poll(n_options=3)
    payload["closes_at"] = "2000-01-01T00:00:00Z"
    r = await client.post("/api/v1/polls", json=payload, headers=CSRF)
    assert r.status_code == 201
    slug = r.json()["slug"]
    view = await client.get(f"/api/v1/polls/{slug}")
    assert view.json()["poll"]["status"] == "closed"

    q = view.json()["questions"][0]
    opt_ids = [o["id"] for o in q["options"]]
    await logout(client)
    await register(client, "Voter")
    r = await client.post(
        f"/api/v1/polls/{slug}/questions/{q['id']}/ballot", json={"ranking": opt_ids}, headers=CSRF
    )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Ban validation
# ---------------------------------------------------------------------------
async def test_ban_requires_real_user(client):
    await register(client, "Owner")
    slug = await _make_poll(client)
    # missing user_id -> schema 422
    r = await client.post(f"/api/v1/polls/{slug}/bans", json={}, headers=CSRF)
    assert r.status_code == 422
    # unknown user_id -> 404
    r = await client.post(
        f"/api/v1/polls/{slug}/bans", json={"user_id": "nobody"}, headers=CSRF
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Cascade deletes (FK pragma on in tests)
# ---------------------------------------------------------------------------
async def _promote_admin(username_lower: str):
    async with TestSession() as s:
        res = await s.execute(select(User).where(User.username_lower == username_lower))
        u = res.scalar_one()
        u.is_admin = True
        await s.commit()


async def _count(model, **filters):
    async with TestSession() as s:
        stmt = select(func.count()).select_from(model)
        res = await s.execute(stmt)
        return int(res.scalar_one())


async def test_delete_poll_cascades(client):
    await register(client, "Owner")
    slug = await _make_poll(client, n_options=3)
    q = (await client.get(f"/api/v1/polls/{slug}")).json()["questions"][0]
    opt_ids = [o["id"] for o in q["options"]]
    await logout(client)

    await register(client, "Voter")
    # generate a display order + a ballot
    await client.get(f"/api/v1/polls/{slug}/questions/{q['id']}/vote")
    await client.post(
        f"/api/v1/polls/{slug}/questions/{q['id']}/ballot", json={"ranking": opt_ids}, headers=CSRF
    )
    await logout(client)

    assert await _count(Ballot) == 1
    assert await _count(DisplayOrder) == 1

    await login(client, "Owner")
    r = await client.delete(f"/api/v1/polls/{slug}", headers=CSRF)
    assert r.status_code == 200

    assert await _count(Poll) == 0
    assert await _count(Question) == 0
    assert await _count(Option) == 0
    assert await _count(Ballot) == 0
    assert await _count(DisplayOrder) == 0


async def test_delete_user_cascades(client):
    # Admin deletes a user; their polls, ballots, sessions cascade away.
    await register(client, "Owner")
    slug = await _make_poll(client, n_options=3)
    q = (await client.get(f"/api/v1/polls/{slug}")).json()["questions"][0]
    opt_ids = [o["id"] for o in q["options"]]
    await logout(client)

    await register(client, "Voter")
    voter_id = (await client.get("/api/v1/auth/me")).json()["id"]
    await client.post(
        f"/api/v1/polls/{slug}/questions/{q['id']}/ballot", json={"ranking": opt_ids}, headers=CSRF
    )
    await logout(client)

    await register(client, "Boss")
    await _promote_admin("boss")
    # re-login to refresh admin session/state
    await logout(client)
    await login(client, "Boss")

    assert await _count(Ballot) == 1
    r = await client.delete(f"/api/v1/admin/users/{voter_id}", headers=CSRF)
    assert r.status_code == 200
    # Voter's ballot and sessions are gone.
    assert await _count(Ballot) == 0
    async with TestSession() as s:
        sess = await s.execute(select(func.count()).select_from(SessionModel).where(SessionModel.user_id == voter_id))
        assert int(sess.scalar_one()) == 0


# ---------------------------------------------------------------------------
# Permission matrix: 401 (no auth) vs 403 (wrong role)
# ---------------------------------------------------------------------------
async def test_401_vs_403(client):
    # No cookie at all -> 401.
    assert (await client.get("/api/v1/polls/mine")).status_code == 401
    assert (await client.get("/api/v1/admin/users")).status_code == 401

    await register(client, "Owner")
    slug = await _make_poll(client)
    await logout(client)

    # Authenticated but wrong role -> 403.
    await register(client, "Rando")
    assert (await client.get(f"/api/v1/polls/{slug}/voters")).status_code == 403
    assert (await client.get("/api/v1/admin/users")).status_code == 403
    assert (await client.post(f"/api/v1/polls/{slug}/close", headers=CSRF)).status_code == 403


# ---------------------------------------------------------------------------
# Concurrency invariant: re-submitting updates the same row (no duplicate)
# ---------------------------------------------------------------------------
async def test_resubmit_updates_single_row(client):
    await register(client, "Owner")
    slug = await _make_poll(client, n_options=3)
    q = (await client.get(f"/api/v1/polls/{slug}")).json()["questions"][0]
    opt_ids = [o["id"] for o in q["options"]]
    await logout(client)

    await register(client, "Voter")
    for ranking in ([opt_ids, list(reversed(opt_ids)), opt_ids]):
        r = await client.post(
            f"/api/v1/polls/{slug}/questions/{q['id']}/ballot",
            json={"ranking": ranking},
            headers=CSRF,
        )
        assert r.status_code == 200
    assert await _count(Ballot) == 1
