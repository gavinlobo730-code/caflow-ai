"""Two firms drive the API at the same time and neither ever sees the other (POST-A-012).

WHAT WAS MISSING
    The tenant-isolation tests (the role-by-table matrix, the firm-scope AST guard, the per-route cross-tenant tests) all call one
    caller at a time. The things a second caller can break are the process-wide ones: the 30-second user-lookup cache keyed by auth
    user, the per-request holders the authentication dependency binds the firm and the verified person into, and the thread pool a
    synchronous handler runs in, which hands one request's context to a worker another request used a moment ago. None of those can
    fail in a one-caller test.

WHAT THIS DOES
    The REAL `get_current_user` runs (the token decode is the only thing replaced: it maps a test token to its subject), against the
    real user and firm lookup over the in-memory database double, behind the real request-context middleware. 120 requests from two
    firms, interleaved, go through the ASGI app at once; the synchronous handlers sleep a few milliseconds inside the thread pool so
    they genuinely overlap (the test measures the overlap and fails if it did not happen: a concurrency test that never ran
    concurrently proves nothing).

WHAT IS HELD
    * every request's authenticated user, the firm bound to its request context and the verified person bound to it are ITS OWN,
      whatever else was in flight, in both firms;
    * a list of customers read through a real router holds only the caller's firm's rows, in both firms, every time;
    * a caller who asks for the OTHER firm's client is refused every time, never answered with that firm's data;
    * the user-lookup cache keeps two users apart (a firm is never served from the other's entry), and a cached entry is the
      caller's own on the second request.
    It does not prove the database's row security (the real-Postgres matrix does) or a deployment with several workers.
"""
from __future__ import annotations

import asyncio
import pathlib
import random
import threading
import time

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI, Request

import core.auth as auth
import routers.customers as customers_router
from core.permissions import rbac
from core import request_actor
from core.request_actor import current_auth_user_id
from core.request_context import current_firm_id
from middleware.request_context import RequestContextMiddleware
from tests.e2e_harness import FakeDB

FIRM_A = "aaaaaaaa-0000-4000-8000-00000000000a"
FIRM_B = "bbbbbbbb-0000-4000-8000-00000000000b"
CLIENT_A = "cccccccc-0000-4000-8000-0000000000a1"
CLIENT_B = "cccccccc-0000-4000-8000-0000000000b1"
USERS = {"auth-a": ("user-a", FIRM_A), "auth-b": ("user-b", FIRM_B)}

#: How many requests per firm, and how many of each kind.
PER_FIRM = 60


def _world() -> FakeDB:
    db = FakeDB()
    for firm, client, tag, auth_id in ((FIRM_A, CLIENT_A, "A", "auth-a"), (FIRM_B, CLIENT_B, "B", "auth-b")):
        db.seed("firms", {"id": firm, "is_active": True, "deleted_at": None})
        db.seed("clients", {"id": client, "firm_id": firm, "client_name": f"Client {tag}", "status": "active"})
        db.seed("users", {"id": USERS[auth_id][0], "auth_user_id": auth_id, "firm_id": firm, "role": "Partner",
                          "full_name": f"Partner {tag}", "is_active": True, "sessions_revoked_at": None})
        for i in range(5):
            db.seed("customers", {"id": f"cust-{tag}-{i}", "firm_id": firm, "client_id": client, "name": f"Firm{tag} customer {i}",
                                  "is_active": True})
    return db


class _Overlap:
    """How many handlers were running at the same moment, at most."""

    def __init__(self):
        self._lock = threading.Lock()
        self._now = 0
        self.peak = 0

    def enter(self):
        with self._lock:
            self._now += 1
            self.peak = max(self.peak, self._now)

    def leave(self):
        with self._lock:
            self._now -= 1


@pytest.fixture()
def world(monkeypatch):
    db = _world()
    import core.supabase_client as sc
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    monkeypatch.setattr(sc, "get_service_supabase", lambda: db)
    monkeypatch.setattr(auth, "get_service_supabase", lambda: db)
    monkeypatch.setattr(auth, "decode_supabase_jwt", lambda token: {"sub": token, "iat": 1_900_000_000, "exp": 4_000_000_000})
    monkeypatch.setattr(customers_router, "_USE_MOCK", False)
    auth._user_lookup_cache.clear()
    yield db
    auth._user_lookup_cache.clear()


_CAN_READ_CLIENTS = Depends(rbac("client", "read"))


def _app(overlap: _Overlap) -> FastAPI:
    probe = APIRouter()

    @probe.get("/probe/who")
    def who(current_user: dict = _CAN_READ_CLIENTS):
        overlap.enter()
        try:
            time.sleep(random.uniform(0.005, 0.03))                      # hold the worker so another request's handler runs beside it
            return {"user": current_user["auth_user_id"], "firm": current_user["firm_id"],
                    "bound_firm": current_firm_id(), "bound_actor": current_auth_user_id()}
        finally:
            overlap.leave()

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    # The per-request holder of the verified person is begun by a middleware in main.py (`_carry_user_token`); it is mirrored here
    # because main's app is a process-wide object this test must not add routes to. `test_main_still_begins_the_actor_holder_the_
    # way_this_test_mirrors` fails if main stops doing so.
    @app.middleware("http")
    async def _carry_actor(request: Request, call_next):
        handle = request_actor.begin()
        try:
            return await call_next(request)
        finally:
            request_actor.end(handle)

    app.include_router(probe)
    app.include_router(customers_router.router)
    return app


async def _drive(app: FastAPI, jobs: list[tuple[str, str]]) -> list[tuple[str, str, httpx.Response]]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async def one(token: str, path: str):
            return token, path, await client.get(path, headers={"Authorization": f"Bearer {token}"})
        return list(await asyncio.gather(*(one(t, p) for t, p in jobs)))


def _interleaved(path_for) -> list[tuple[str, str]]:
    jobs = []
    for i in range(PER_FIRM):
        jobs.append(("auth-a", path_for("auth-a", i)))
        jobs.append(("auth-b", path_for("auth-b", i)))
    return jobs


def test_every_request_is_its_own_callers_whatever_else_is_in_flight(world):
    overlap = _Overlap()
    results = asyncio.run(_drive(_app(overlap), _interleaved(lambda token, i: "/probe/who")))
    assert len(results) == 2 * PER_FIRM
    assert overlap.peak >= 4, f"the handlers never overlapped (peak {overlap.peak}); the test proved nothing about concurrency"
    for token, _path, res in results:
        assert res.status_code == 200, res.text
        body = res.json()
        want_user, want_firm = USERS[token]
        assert body["user"] == token and body["firm"] == want_firm
        assert body["bound_firm"] == want_firm, f"a {token} request had firm {body['bound_firm']} bound to its context"
        assert body["bound_actor"] == token, f"a {token} request had {body['bound_actor']} bound as the verified person"


def test_a_customer_list_read_under_load_holds_only_the_callers_firm(world):
    own_client = {"auth-a": CLIENT_A, "auth-b": CLIENT_B}
    results = asyncio.run(_drive(_app(_Overlap()), _interleaved(lambda token, i: f"/api/customers/?client_id={own_client[token]}")))
    for token, _path, res in results:
        assert res.status_code == 200, res.text
        rows = res.json()["data"]
        marker = "FirmA" if token == "auth-a" else "FirmB"
        assert len(rows) == 5, f"{token} was given {len(rows)} customers"
        assert all(r["name"].startswith(marker) and r["firm_id"] == USERS[token][1] for r in rows), rows


def test_asking_for_the_other_firms_client_gets_nothing_of_it_every_time(world):
    """A Partner may act on any client of their OWN firm, so naming another firm's client id is not a refusal at the door: the read
    is confined by the caller's firm, and the answer is an empty list or a refusal, never that firm's customers."""
    other_client = {"auth-a": CLIENT_B, "auth-b": CLIENT_A}
    other_marker = {"auth-a": "FirmB", "auth-b": "FirmA"}
    results = asyncio.run(_drive(_app(_Overlap()), _interleaved(lambda token, i: f"/api/customers/?client_id={other_client[token]}")))
    for token, _path, res in results:
        assert other_marker[token] not in res.text, f"{token} was shown {other_marker[token]}'s data: {res.text}"
        if res.status_code == 200:
            assert res.json()["data"] == [], f"{token} asking for the other firm's client was answered {res.text}"
        else:
            assert res.status_code in (403, 404), res.text


def test_the_user_lookup_cache_keeps_two_users_apart_and_serves_each_their_own(world):
    asyncio.run(_drive(_app(_Overlap()), [("auth-a", "/probe/who"), ("auth-b", "/probe/who")]))
    assert set(auth._user_lookup_cache) == {"auth-a", "auth-b"}
    assert auth._user_lookup_cache["auth-a"][1]["firm_id"] == FIRM_A
    assert auth._user_lookup_cache["auth-b"][1]["firm_id"] == FIRM_B
    # The second round is served from the cache and is still each caller's own.
    again = asyncio.run(_drive(_app(_Overlap()), _interleaved(lambda token, i: "/probe/who")))
    for token, _path, res in again:
        assert res.json()["firm"] == USERS[token][1]


def test_main_still_begins_the_actor_holder_the_way_this_test_mirrors():
    main_source = (pathlib.Path(__file__).resolve().parent.parent / "main.py").read_text()
    assert "actor_handle = request_actor.begin()" in main_source and "request_actor.end(actor_handle)" in main_source, (
        "main.py no longer begins and ends the request actor holder around a request; update the mirror in this test and check "
        "that the holder is still per request")
