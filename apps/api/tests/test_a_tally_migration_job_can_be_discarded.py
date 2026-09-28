"""
sweep-clients-admin-04 — a Tally migration job could never be left, once
started, without finishing it.

WHAT WAS WRONG
    Once a CA left the New Import wizard, a job's id lived only in the
    browser's React state (apps/web/app/migration/page.tsx) and the backend
    had no DELETE on /api/tally-migration/jobs/{id} at all — so a job that
    was abandoned mid-way (a wrong file uploaded, a mapping the CA changed
    their mind about) stayed in the list forever with no way to remove it,
    and there was nothing to wire a "Discard" button to.

WHAT THIS TEST HOLDS
    DELETE /api/tally-migration/jobs/{id}: firm-scoped through the existing
    _assert_job_scope helper (so a hidden client's job 404s exactly like
    every other job-addressed endpoint), refused with 409 once the job is
    'completed' (real customer/vendor rows already exist — rollback is the
    remedy, not discard) or 'importing' (a background task is writing to the
    row right now), and otherwise deletes the job and its staged items.
"""
import pytest
from fastapi import HTTPException

import routers.tally_migration as tm
import domain.tally.migration_service as svc

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "e@f.test", "role": "Manager"}


@pytest.fixture(autouse=True)
def _clear_mock_store():
    svc._MOCK_JOBS.clear()
    svc._MOCK_ITEMS.clear()


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow the rest (including client_id=None) — same shape
    as test_tally_migration_client_scope.py's fixture."""
    def _can(user, client_id):
        return client_id != THEIRS
    monkeypatch.setattr(tm, "can_access_client", _can)


def _job(client_id, job_id, status="uploaded", **extra):
    row = {
        "id": job_id, "firm_id": FIRM, "client_id": client_id,
        "import_types": ["ledgers"], "status": status, **extra,
    }
    svc._MOCK_JOBS[job_id] = row
    svc._MOCK_ITEMS[job_id] = [{"id": "item-1", "firm_id": FIRM, "job_id": job_id}]
    return row


@pytest.mark.parametrize("status", [
    "uploaded", "parsing", "parsed", "mapping", "validating",
    "previewing", "error", "rolled_back",
])
def test_a_non_terminal_job_can_be_discarded(deny, status):
    _job(MINE, "J1", status=status)
    resp = tm.discard_job("J1", current_user=USER)
    assert resp["success"] is True
    assert resp["data"]["deleted"] is True
    assert "J1" not in svc._MOCK_JOBS
    assert "J1" not in svc._MOCK_ITEMS


@pytest.mark.parametrize("status", ["completed", "importing"])
def test_a_completed_or_importing_job_is_refused(deny, status):
    _job(MINE, "J1", status=status)
    with pytest.raises(HTTPException) as exc:
        tm.discard_job("J1", current_user=USER)
    assert exc.value.status_code == 409
    # Refused, not deleted — the job and its items are untouched.
    assert svc._MOCK_JOBS["J1"]["status"] == status
    assert svc._MOCK_ITEMS["J1"] != []


def test_discarding_a_hidden_clients_job_is_refused(deny):
    _job(THEIRS, "J1")
    with pytest.raises(HTTPException) as exc:
        tm.discard_job("J1", current_user=USER)
    assert exc.value.status_code == 404
    # Refused before the domain layer ever ran — nothing was touched.
    assert "J1" in svc._MOCK_JOBS


def test_discarding_a_missing_job_404s(deny):
    with pytest.raises(HTTPException) as exc:
        tm.discard_job("does-not-exist", current_user=USER)
    assert exc.value.status_code == 404


def test_discarding_a_firm_level_job_is_allowed(deny):
    """can_access_client(user, None) is always True — a client-less
    (ledgers/journals) job is unaffected by client scope."""
    _job(None, "J1")
    resp = tm.discard_job("J1", current_user=USER)
    assert resp["success"] is True
