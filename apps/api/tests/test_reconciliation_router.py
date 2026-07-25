"""
routers/reconciliation.py — "Verify Books" on-demand endpoint (task #244).

Drives the real router functions directly against the shared FakeDB (same
e2e_harness pattern as test_tds_return_reconciliation.py / test_gst_return_
reconciliation.py) so client-access scoping (core.authz) and the reconciliation
engine itself both run for real, not mocked.
"""
import pytest
from fastapi import HTTPException

import routers.reconciliation as recon_router
from domain.reporting.model import JournalEntry, JournalLine
from routers.reconciliation import (
    ResolveFindingRequest, VerifyBooksRequest, get_run, list_runs,
    resolve_finding, verify_books,
)
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
CLIENT = "CLI-A"
OTHER_CLIENT = "CLI-B"
PARTNER = {"firm_id": FIRM, "id": "u-partner", "auth_user_id": "auth-1", "email": "p@f.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [recon_router])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    # core.authz AND repositories.client_repository each compute their OWN
    # `_USE_MOCK = not os.environ.get("SUPABASE_URL")` once, at first import
    # — wire_e2e doesn't patch either. In isolation this test's own setenv
    # above happens to land before either module's first import; but if some
    # OTHER test file imports repositories.client_repository first (with
    # SUPABASE_URL still unset), that module's _USE_MOCK freezes True for the
    # rest of the pytest session regardless of what this test does — a
    # pre-existing test-session-only fragility (real prod sets the env var
    # once at process start, before any import, so this can't happen there).
    # Patch both explicitly so this test's outcome never depends on file order.
    monkeypatch.setattr("core.authz._USE_MOCK", False)
    monkeypatch.setattr("repositories.client_repository._USE_MOCK", False)
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM})
    db.seed("clients", {"id": OTHER_CLIENT, "firm_id": "FIRM-OTHER"})
    monkeypatch.setattr(
        "domain.reporting.sources.SupabaseLedgerSource._entries",
        lambda self, firm_id, client_id: {},
    )
    return db


def test_verify_books_runs_and_returns_findings(monkeypatch):
    db = _setup(monkeypatch)
    resp = verify_books(VerifyBooksRequest(client_id=CLIENT), PARTNER)
    assert resp["success"] is True
    assert resp["data"]["status"] == "completed"
    assert resp["data"]["findings_count"] == 0
    assert len(db.rows("reconciliation_runs")) == 1
    assert db.rows("reconciliation_runs")[0]["trigger"] == "manual"
    assert db.rows("reconciliation_runs")[0]["triggered_by"] == "u-partner"


def test_verify_books_rejects_client_in_another_firm(monkeypatch):
    _setup(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        verify_books(VerifyBooksRequest(client_id=OTHER_CLIENT), PARTNER)
    assert exc.value.status_code == 404


def test_list_runs_returns_most_recent_first(monkeypatch):
    db = _setup(monkeypatch)
    verify_books(VerifyBooksRequest(client_id=CLIENT), PARTNER)
    verify_books(VerifyBooksRequest(client_id=CLIENT), PARTNER)
    resp = list_runs(client_id=CLIENT, limit=20, current_user=PARTNER)
    assert resp["success"] is True
    assert len(resp["data"]["runs"]) == 2


def test_list_runs_rejects_client_in_another_firm(monkeypatch):
    _setup(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        list_runs(client_id=OTHER_CLIENT, limit=20, current_user=PARTNER)
    assert exc.value.status_code == 404


def test_get_run_returns_run_and_its_findings(monkeypatch):
    db = _setup(monkeypatch)
    monkeypatch.setattr(
        "domain.reporting.sources.SupabaseLedgerSource._entries",
        lambda self, firm_id, client_id: {
            "e1": JournalEntry(
                id="e1", entry_date="2026-04-05", client_id=CLIENT, firm_id=FIRM, entry_type="Journal",
                lines=(JournalLine("a", 1000, 0), JournalLine("b", 0, 900)),
            ),
        },
    )
    created = verify_books(VerifyBooksRequest(client_id=CLIENT), PARTNER)
    run_id = created["data"]["run_id"]

    resp = get_run(run_id, PARTNER)
    assert resp["success"] is True
    assert resp["data"]["run"]["id"] == run_id
    assert len(resp["data"]["findings"]) == 1
    assert resp["data"]["findings"][0]["check_name"] == "trial_balance"


def test_get_run_404_for_unknown_run(monkeypatch):
    _setup(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        get_run("no-such-run", PARTNER)
    assert exc.value.status_code == 404


def test_resolve_finding_stamps_reviewer_and_note(monkeypatch):
    db = _setup(monkeypatch)
    monkeypatch.setattr(
        "domain.reporting.sources.SupabaseLedgerSource._entries",
        lambda self, firm_id, client_id: {
            "e1": JournalEntry(
                id="e1", entry_date="2026-04-05", client_id=CLIENT, firm_id=FIRM, entry_type="Journal",
                lines=(JournalLine("a", 1000, 0), JournalLine("b", 0, 900)),
            ),
        },
    )
    verify_books(VerifyBooksRequest(client_id=CLIENT), PARTNER)
    finding_id = db.rows("reconciliation_findings")[0]["id"]

    resp = resolve_finding(finding_id, ResolveFindingRequest(resolution_note="Investigated, one-off import glitch."), PARTNER)
    assert resp["success"] is True
    assert resp["data"]["finding"]["resolved_by"] == "u-partner"
    assert resp["data"]["finding"]["resolution_note"] == "Investigated, one-off import glitch."
    assert resp["data"]["finding"]["resolved_at"] is not None


def test_resolve_finding_404_for_unknown_finding(monkeypatch):
    _setup(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        resolve_finding("no-such-finding", ResolveFindingRequest(), PARTNER)
    assert exc.value.status_code == 404
