"""API integration tests (instructions.md §13)."""

from __future__ import annotations

import pytest

from tests.conftest import CSRF, login, logout, register, sample_poll


# ---------------------------------------------------------------------------
# Auth flow
# ---------------------------------------------------------------------------
async def test_register_login_logout_me(client):
    r = await register(client, "Alice")
    assert r.status_code == 201, r.text
    assert r.json()["username"] == "Alice"

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "Alice"

    assert (await logout(client)).status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 401

    # case-insensitive login
    assert (await login(client, "alice")).status_code == 200


async def test_register_rejects_duplicate_username_case_insensitive(client):
    assert (await register(client, "Bob")).status_code == 201
    await logout(client)
    dup = await register(client, "bob")
    assert dup.status_code == 409


async def test_register_password_equals_username_rejected(client):
    r = await client.post(
        "/api/v1/auth/register",
        json={"username": "charlie", "password": "charlie", "password_confirm": "charlie"},
        headers=CSRF,
    )
    # username min length is fine (7 chars); rejected because password == username.
    assert r.status_code == 422


async def test_login_generic_error(client):
    r = await login(client, "ghost")
    assert r.status_code == 401
    assert "Invalid username or password" in r.json()["detail"]


async def test_csrf_header_required(client):
    # No X-Requested-With header -> blocked.
    r = await client.post(
        "/api/v1/auth/register",
        json={"username": "dave", "password": "password123", "password_confirm": "password123"},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Poll creation limits
# ---------------------------------------------------------------------------
async def test_create_poll_and_limits(client):
    await register(client, "Creator")

    # too many options
    bad = sample_poll(n_options=11)
    assert (await client.post("/api/v1/polls", json=bad, headers=CSRF)).status_code == 422

    # too few options
    bad = sample_poll(n_options=1)
    assert (await client.post("/api/v1/polls", json=bad, headers=CSRF)).status_code == 422

    # zero questions
    bad = sample_poll(n_questions=0)
    assert (await client.post("/api/v1/polls", json=bad, headers=CSRF)).status_code == 422

    # 21 questions
    bad = sample_poll(n_questions=21)
    assert (await client.post("/api/v1/polls", json=bad, headers=CSRF)).status_code == 422

    ok = await client.post("/api/v1/polls", json=sample_poll(), headers=CSRF)
    assert ok.status_code == 201
    assert len(ok.json()["slug"]) == 8


async def _make_poll(client, **kw):
    r = await client.post("/api/v1/polls", json=sample_poll(**kw), headers=CSRF)
    assert r.status_code == 201, r.text
    return r.json()["slug"]


async def _first_question(client, slug):
    poll = await client.get(f"/api/v1/polls/{slug}")
    return poll.json()["questions"][0]


# ---------------------------------------------------------------------------
# Voting + stale-ballot rejection
# ---------------------------------------------------------------------------
async def test_vote_and_results_visibility(client):
    await register(client, "Owner")
    slug = await _make_poll(client, n_options=3)
    await logout(client)

    await register(client, "Voter1")
    q = await _first_question(client, slug)
    opt_ids = [o["id"] for o in q["options"]]

    # non-voter cannot see results
    assert (await client.get(f"/api/v1/polls/{slug}/results")).status_code == 403

    r = await client.post(
        f"/api/v1/polls/{slug}/questions/{q['id']}/ballot",
        json={"ranking": opt_ids},
        headers=CSRF,
    )
    assert r.status_code == 200, r.text

    res = await client.get(f"/api/v1/polls/{slug}/results")
    assert res.status_code == 200
    tally = res.json()["questions"][0]["tally"]
    assert tally["total_ballots"] == 1
    assert tally["winner_option_id"] == opt_ids[0]


async def test_stale_ballot_rejected(client):
    await register(client, "Owner")
    slug = await _make_poll(client, n_options=3)
    q = await _first_question(client, slug)
    bad_ranking = ["nonexistent-a", "nonexistent-b", "nonexistent-c"]
    r = await client.post(
        f"/api/v1/polls/{slug}/questions/{q['id']}/ballot",
        json={"ranking": bad_ranking},
        headers=CSRF,
    )
    assert r.status_code == 409
    assert "re-rank" in r.json()["detail"]

    # partial permutation rejected too
    opt_ids = [o["id"] for o in q["options"]]
    r = await client.post(
        f"/api/v1/polls/{slug}/questions/{q['id']}/ballot",
        json={"ranking": opt_ids[:2]},
        headers=CSRF,
    )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Invalidating-edit contract (§5)
# ---------------------------------------------------------------------------
async def test_invalidating_edit_invalidates_ballots(client):
    await register(client, "Owner")
    slug = await _make_poll(client, n_options=3)
    q = await _first_question(client, slug)
    opt_ids = [o["id"] for o in q["options"]]
    await logout(client)

    await register(client, "Val1")
    await client.post(
        f"/api/v1/polls/{slug}/questions/{q['id']}/ballot",
        json={"ranking": opt_ids},
        headers=CSRF,
    )
    await logout(client)

    # Owner renames an option -> invalidates the 1 ballot.
    await login(client, "Owner")
    impact = await client.get(f"/api/v1/polls/{slug}/questions/{q['id']}/impact")
    assert impact.json()["ballots_to_invalidate"] == 1

    new_options = [{"label": "Renamed"}, {"label": "Opt 2"}, {"label": "Opt 3"}]
    edit = await client.put(
        f"/api/v1/polls/{slug}/questions/{q['id']}",
        json={"options": new_options},
        headers=CSRF,
    )
    assert edit.status_code == 200
    assert edit.json()["invalidated_ballots"] == 1

    # The tally now excludes the invalidated ballot.
    res = await client.get(f"/api/v1/polls/{slug}/results")
    assert res.json()["questions"][0]["tally"]["total_ballots"] == 0


async def test_description_edit_is_free(client):
    await register(client, "Owner")
    slug = await _make_poll(client, n_options=3)
    q = await _first_question(client, slug)
    opt_ids = [o["id"] for o in q["options"]]
    await logout(client)

    await register(client, "Val1")
    await client.post(
        f"/api/v1/polls/{slug}/questions/{q['id']}/ballot",
        json={"ranking": opt_ids},
        headers=CSRF,
    )
    await logout(client)

    await login(client, "Owner")
    edit = await client.put(
        f"/api/v1/polls/{slug}/questions/{q['id']}",
        json={"description": "New description, no consequences"},
        headers=CSRF,
    )
    assert edit.json()["invalidated_ballots"] == 0
    res = await client.get(f"/api/v1/polls/{slug}/results")
    assert res.json()["questions"][0]["tally"]["total_ballots"] == 1


# ---------------------------------------------------------------------------
# Permission matrix + ban (§9)
# ---------------------------------------------------------------------------
async def test_ban_excludes_and_blocks(client):
    await register(client, "Owner")
    slug = await _make_poll(client, n_options=3)
    q = await _first_question(client, slug)
    opt_ids = [o["id"] for o in q["options"]]
    await logout(client)

    await register(client, "Baddie")
    me = await client.get("/api/v1/auth/me")
    baddie_id = me.json()["id"]
    await client.post(
        f"/api/v1/polls/{slug}/questions/{q['id']}/ballot",
        json={"ranking": opt_ids},
        headers=CSRF,
    )
    await logout(client)

    # Owner bans the voter.
    await login(client, "Owner")
    ban = await client.post(
        f"/api/v1/polls/{slug}/bans", json={"user_id": baddie_id}, headers=CSRF
    )
    assert ban.status_code == 200
    # Ballot now excluded from tally.
    res = await client.get(f"/api/v1/polls/{slug}/results")
    assert res.json()["questions"][0]["tally"]["total_ballots"] == 0
    await logout(client)

    # Banned user is blocked and cannot vote.
    await login(client, "Baddie")
    view = await client.get(f"/api/v1/polls/{slug}")
    assert view.json()["viewer_role"] == "banned"
    revote = await client.post(
        f"/api/v1/polls/{slug}/questions/{q['id']}/ballot",
        json={"ranking": opt_ids},
        headers=CSRF,
    )
    assert revote.status_code == 403


async def test_non_creator_cannot_manage(client):
    await register(client, "Owner")
    slug = await _make_poll(client)
    await logout(client)

    await register(client, "Rando")
    assert (await client.post(f"/api/v1/polls/{slug}/close", headers=CSRF)).status_code == 403
    assert (await client.get(f"/api/v1/polls/{slug}/voters")).status_code == 403
    assert (await client.delete(f"/api/v1/polls/{slug}", headers=CSRF)).status_code == 403


async def test_admin_required(client):
    await register(client, "Plebian")
    assert (await client.get("/api/v1/admin/users")).status_code == 403


async def test_closed_poll_rejects_votes(client):
    await register(client, "Owner")
    slug = await _make_poll(client, n_options=3)
    q = await _first_question(client, slug)
    opt_ids = [o["id"] for o in q["options"]]
    close = await client.post(f"/api/v1/polls/{slug}/close", headers=CSRF)
    assert close.status_code == 200
    await logout(client)

    await register(client, "LateVoter")
    r = await client.post(
        f"/api/v1/polls/{slug}/questions/{q['id']}/ballot",
        json={"ranking": opt_ids},
        headers=CSRF,
    )
    assert r.status_code == 409


async def test_display_order_is_stable_before_voting(client):
    await register(client, "Owner")
    slug = await _make_poll(client, n_options=5)
    q = await _first_question(client, slug)
    await logout(client)

    await register(client, "Peeker")
    v1 = await client.get(f"/api/v1/polls/{slug}/questions/{q['id']}/vote")
    order1 = [o["id"] for o in v1.json()["order"]]
    v2 = await client.get(f"/api/v1/polls/{slug}/questions/{q['id']}/vote")
    order2 = [o["id"] for o in v2.json()["order"]]
    assert order1 == order2  # persisted, reused across views


async def test_optional_question_skip_but_required_cannot(client):
    await register(client, "Owner")
    slug = await _make_poll(client, n_questions=1, n_options=3, required=True)
    q = await _first_question(client, slug)
    await logout(client)

    await register(client, "Skipper")
    r = await client.post(
        f"/api/v1/polls/{slug}/questions/{q['id']}/skip", headers=CSRF
    )
    assert r.status_code == 422  # required cannot be skipped
