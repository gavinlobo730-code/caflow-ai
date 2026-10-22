"""Finalising a client's year-end locks that client's year under a request sign-in, and reopening it unlocks it (migration 532,
POST-A-314).

WHAT WAS WRONG
    `routers/year_end.py` and `routers/year_end_reviews.py` write the engagement as `locked` and then call
    `year_lock_service.set_client_lock` with the caller's own database client. With per-user sign-in on, which is the production
    default, the lock table's only policy (migration 289) asked a token claim nobody carries, so the INSERT of the lock row was
    refused after the engagement row had been written: the engagement read "locked" and the client's year stayed open. And the
    period checks (`period_closure_reason`, `period_lock_reason`) are SECURITY INVOKER, so a finalised year read as OPEN to every
    check made under a sign-in: the posting kernel's gate, and the pre-checks of invoices, bills, notes, receipts, fixed assets,
    inventory and the manual journal.

WHAT THIS DRIVES, AND HOW
    The real route functions and the real kernel and period-lock code, against a real database, as the roles production uses:
    the request's client is `tests/_signed_in_postgrest.SignedInDb` running as `authenticated` with a Partner's (or a Manager's)
    token claims, and the privileged client is the same double running as `service_role`. Nothing in the code under test is
    replaced except which client `core.supabase_client.get_supabase` and `core.db_provider.service_db_or_none` hand out, the
    audit writer (recorded, not run) and the client-belongs-to-firm lookup (`core.authz`, covered by its own tests).

    * a Partner's final approval writes the lock row, with the Partner's internal user id, and the checks made as an assigned
      Manager then refuse a posting into that year (the kernel's gate, the document pre-check) while the same Manager can still
      post into another year of the client and into another client's year;
    * the reopen removes the row and the checks answer open again; the generic status route does the same pair;
    * locking an already-locked year and unlocking an open one write nothing and are not audited a second time;
    * CONTROL: with no privileged client (the fallback to the request's own, which is the previous behaviour) the lock insert is
      refused by the database and the engagement is left locked with the year open, the half-way failure the ledger recorded.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

from tests._signed_in_postgrest import SignedInDb, SignedInError

API_ROOT = Path(__file__).resolve().parents[1]
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="the year-end proof requires HARNESS_PG + psql",
)

FIRM = "53201000-0000-0000-0000-000000000001"
CLIENT_A = "53201000-0000-0000-0000-0000000000a1"
CLIENT_B = "53201000-0000-0000-0000-0000000000b2"
PARTNER = {"id": "53201000-0000-0000-0000-00000000000a", "auth_user_id": "53201000-1111-0000-0000-000000000001",
           "role": "Partner", "firm_id": FIRM, "email": "partner@t.in"}
MANAGER = {"id": "53201000-0000-0000-0000-00000000000b", "auth_user_id": "53201000-1111-0000-0000-000000000002",
           "role": "Manager", "firm_id": FIRM, "email": "manager@t.in"}
UNASSIGNED = {"id": "53201000-0000-0000-0000-00000000000c", "auth_user_id": "53201000-1111-0000-0000-000000000003",
              "role": "Manager", "firm_id": FIRM, "email": "unassigned@t.in"}
ENGAGEMENT = "53201000-0000-0000-0000-0000000000e1"
FY = "2025-26"
IN_THE_YEAR = "2025-09-30"
IN_THE_NEXT_YEAR = "2026-06-30"
CLOSED = "is closed for this client"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


@pytest.fixture()
def world(pg_template, monkeypatch):
    """A throwaway database, a Partner and an assigned Manager, one approved year-end engagement for client A, and the
    route modules pointed at the doubles. Yields a namespace the tests drive."""
    admin = _ADMIN.strip()
    name = f"e532b_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{PARTNER["auth_user_id"]}', 'partner@t.in'), ('{MANAGER["auth_user_id"]}', 'manager@t.in'),
                 ('{UNASSIGNED["auth_user_id"]}', 'unassigned@t.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship'), ('{CLIENT_B}', '{FIRM}', 'B', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{PARTNER["id"]}', '{FIRM}', '{PARTNER["auth_user_id"]}', 'partner@t.in', 'P', 'Partner', true),
                        ('{MANAGER["id"]}', '{FIRM}', '{MANAGER["auth_user_id"]}', 'manager@t.in', 'M', 'Manager', true),
                        ('{UNASSIGNED["id"]}', '{FIRM}', '{UNASSIGNED["auth_user_id"]}', 'unassigned@t.in', 'U', 'Manager', true);
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES ('{FIRM}', '{MANAGER["id"]}', '{CLIENT_A}');
            INSERT INTO year_end_engagements (id, firm_id, client_id, financial_year, fy_start, fy_end, status, created_by)
                 VALUES ('{ENGAGEMENT}', '{FIRM}', '{CLIENT_A}', '{FY}', '2025-04-01', '2026-03-31', 'approved', '{PARTNER["id"]}');
            -- neighbours that differ from the target in exactly one of client and year: a lock or an unlock that drops a filter
            -- of the privileged client would act on them, and nothing else in these tests would notice
            INSERT INTO client_year_locks (firm_id, client_id, financial_year, reason)
                 VALUES ('{FIRM}', '{CLIENT_A}', '2024-25', 'neighbour: another year'),
                        ('{FIRM}', '{CLIENT_B}', '{FY}', 'neighbour: another client');
        """)
        assert seed.returncode == 0, seed.stderr

        class World:
            pass

        w = World()
        w.dsn = dsn
        w.partner_db = SignedInDb(dsn, auth_user_id=PARTNER["auth_user_id"])
        w.manager_db = SignedInDb(dsn, auth_user_id=MANAGER["auth_user_id"])
        w.unassigned_db = SignedInDb(dsn, auth_user_id=UNASSIGNED["auth_user_id"])
        w.service_db = SignedInDb(dsn, role="service_role")
        w.audit = []

        import core.authz
        import core.db_provider
        import core.supabase_client
        import routers.year_end
        import routers.year_end_reviews
        import services.year_lock_service

        monkeypatch.setattr(core.supabase_client, "get_supabase", lambda *a, **k: w.partner_db)
        monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: w.service_db)
        monkeypatch.setattr(routers.year_end, "_USE_MOCK", False)
        monkeypatch.setattr(routers.year_end_reviews, "_USE_MOCK", False)
        monkeypatch.setattr(core.authz, "_USE_MOCK", False)
        monkeypatch.setattr(core.authz, "_client_belongs_to_firm", lambda client_id, firm_id: True)
        monkeypatch.setattr(services.year_lock_service, "log_event", lambda *a, **k: w.audit.append((a, k)))
        monkeypatch.setattr(routers.year_end_reviews, "log_event", lambda *a, **k: None)
        yield w
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _locks(w) -> list[list[str]]:
    """The target's lock rows: client A, the financial year under test."""
    return _rows(w.dsn, f"SELECT financial_year, locked_by, reason FROM client_year_locks "
                        f"WHERE client_id = '{CLIENT_A}' AND financial_year = '{FY}'")


def _neighbours(w) -> list[list[str]]:
    """Every other lock row: it must be exactly what the fixture seeded, after every finalise and every reopen."""
    return _rows(w.dsn, f"SELECT client_id, financial_year, reason FROM client_year_locks "
                        f"WHERE NOT (client_id = '{CLIENT_A}' AND financial_year = '{FY}') ORDER BY reason")


NEIGHBOURS = [[CLIENT_B, FY, "neighbour: another client"], [CLIENT_A, "2024-25", "neighbour: another year"]]


def _status(w) -> str:
    return _rows(w.dsn, f"SELECT status FROM year_end_engagements WHERE id = '{ENGAGEMENT}'")[0][0]


def _kernel_post(db, client: str, day: str) -> str:
    from services.phase2_journal_service import Phase2JournalService
    lines = [{"account_id": "a1", "debit_paise": 1000, "credit_paise": 0},
             {"account_id": "a2", "debit_paise": 0, "credit_paise": 1000}]
    return Phase2JournalService()._create_journal(db, FIRM, client, day, "REF-1", "n", "Journal", lines)


def _final_approve(w):
    from routers.year_end_reviews import ReviewActionIn, final_approve
    return final_approve(ENGAGEMENT, ReviewActionIn(comment="approved"), current_user=PARTNER)


def _reopen(w):
    from routers.year_end_reviews import ReviewActionIn, reopen
    return reopen(ENGAGEMENT, ReviewActionIn(comment="a revised interest certificate"), current_user=PARTNER)


def test_a_final_approval_under_a_request_sign_in_locks_the_clients_year_and_the_checks_refuse_a_posting_into_it(world):
    w = world
    assert _locks(w) == [] and _status(w) == "approved" and _neighbours(w) == NEIGHBOURS

    out = _final_approve(w)
    assert out["success"], out
    assert _status(w) == "locked"
    assert _locks(w) == [[FY, PARTNER["id"], "Year-end engagement finalised"]], _locks(w)
    assert [(a[1], a[3]) for a, _k in w.audit] == [("client_year_lock", "lock")], w.audit

    from services import period_lock_service
    # the posting kernel's gate, with the request's own client, as an assigned Manager
    with pytest.raises(ValueError, match=CLOSED):
        _kernel_post(w.manager_db, CLIENT_A, IN_THE_YEAR)
    with pytest.raises(ValueError, match=CLOSED):
        _kernel_post(w.partner_db, CLIENT_A, IN_THE_YEAR)
    # the pre-check a document makes before it is written
    with pytest.raises(HTTPException) as refused:
        period_lock_service.assert_open(w.manager_db, FIRM, CLIENT_A, IN_THE_YEAR)
    assert refused.value.status_code == 422 and CLOSED in refused.value.detail
    # the lock is that client's, that year's: nothing else closed
    assert period_lock_service.closure_reason(w.manager_db, FIRM, CLIENT_A, IN_THE_NEXT_YEAR) is None
    assert period_lock_service.closure_reason(w.partner_db, FIRM, CLIENT_B, IN_THE_NEXT_YEAR) is None
    # a Manager who is not assigned to client A cannot see its lock (and could not post for it: the route's own check comes first)
    assert period_lock_service.closure_reason(w.unassigned_db, FIRM, CLIENT_A, IN_THE_YEAR) is None
    # finalising client A's year touched no neighbouring row
    assert _neighbours(w) == NEIGHBOURS


def test_a_reopen_removes_the_lock_and_the_checks_answer_open_again(world):
    w = world
    _final_approve(w)
    assert len(_locks(w)) == 1

    out = _reopen(w)
    assert out["success"], out
    assert _status(w) == "approved"
    assert _locks(w) == []
    assert _neighbours(w) == NEIGHBOURS, "the reopen unlocked more than the one client's one year"
    from services import period_lock_service
    assert period_lock_service.closure_reason(w.manager_db, FIRM, CLIENT_A, IN_THE_YEAR) is None
    assert [a[3] for a, _k in w.audit] == ["lock", "unlock"], w.audit


def test_the_generic_status_route_locks_and_reopens_the_same_way(world):
    w = world
    from routers.year_end import EngagementStatusIn, update_engagement_status
    out = update_engagement_status(ENGAGEMENT, EngagementStatusIn(status="locked"), current_user=PARTNER)
    assert out["success"], out
    assert _status(w) == "locked" and [r[0] for r in _locks(w)] == [FY]
    from services import period_lock_service
    assert CLOSED in (period_lock_service.closure_reason(w.manager_db, FIRM, CLIENT_A, IN_THE_YEAR) or "")

    out = update_engagement_status(ENGAGEMENT, EngagementStatusIn(status="approved", comment="a §143(1) intimation"), current_user=PARTNER)
    assert out["success"], out
    assert _status(w) == "approved" and _locks(w) == [] and _neighbours(w) == NEIGHBOURS
    assert period_lock_service.closure_reason(w.manager_db, FIRM, CLIENT_A, IN_THE_YEAR) is None


def test_locking_a_locked_year_and_unlocking_an_open_one_write_nothing_and_are_not_audited_twice(world):
    w = world
    from services.year_lock_service import set_client_lock
    kw = dict(actor_id=PARTNER["id"], actor_auth_id=PARTNER["auth_user_id"], actor_email=PARTNER["email"], reason="r")
    assert set_client_lock(w.partner_db, FIRM, CLIENT_A, FY, lock=False, **kw) == {"financial_year": FY, "locked": False}
    assert _locks(w) == [] and w.audit == []
    set_client_lock(w.partner_db, FIRM, CLIENT_A, FY, lock=True, **kw)
    set_client_lock(w.partner_db, FIRM, CLIENT_A, FY, lock=True, **kw)
    assert len(_locks(w)) == 1 and len(w.audit) == 1, (_locks(w), w.audit)
    assert _neighbours(w) == NEIGHBOURS
    set_client_lock(w.partner_db, FIRM, CLIENT_A, FY, lock=False, **kw)
    assert _locks(w) == [] and _neighbours(w) == NEIGHBOURS, "an unlock acted on a row other than the target"


def test_the_lock_is_written_by_the_privileged_client_whatever_the_request_signs_in_as(world):
    """The request's client cannot write the table (532 revoked it); the call works because the write goes to the privileged one."""
    w = world
    with pytest.raises(SignedInError):
        w.partner_db.table("client_year_locks").insert({"firm_id": FIRM, "client_id": CLIENT_A, "financial_year": FY}).execute()
    from services.year_lock_service import set_client_lock
    set_client_lock(w.partner_db, FIRM, CLIENT_A, FY, lock=True, actor_id=PARTNER["id"], actor_auth_id=PARTNER["auth_user_id"])
    assert [r[0] for r in _locks(w)] == [FY]


def test_without_a_privileged_client_the_signed_in_write_is_refused_and_the_engagement_is_left_locked_with_the_year_open(world, monkeypatch):
    """CONTROL: the previous behaviour (the write made with the request's own client) fails at the database, AFTER the engagement
    row was written as locked: the half-way failure the ledger recorded."""
    w = world
    import core.db_provider
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: None)
    with pytest.raises(SignedInError):
        _final_approve(w)
    assert _status(w) == "locked" and _locks(w) == [], "the engagement should be left locked with no lock row"
    from services import period_lock_service
    assert period_lock_service.closure_reason(w.manager_db, FIRM, CLIENT_A, IN_THE_YEAR) is None
