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


# ══════════════════════════════════════════════════════════════════════════════
# Client scope on the ROW-ADDRESSED endpoints (M2 sweep)
# ══════════════════════════════════════════════════════════════════════════════
# `verify_books` and `list_runs` name their client, and the two tests above
# cover those refusals. `get_run` and `resolve_finding` take an id and resolve
# the client from the row — and until these tests, deleting either of those
# `assert_client_access` calls broke nothing in the suite.
#
# WHAT THESE CAN AND CANNOT SHOW. `rbac("accounting", "approve")` admits only
# the Partner (Manager/Executive/Reviewer are all False), and `is_firmwide` is
# True for exactly the Partner — so on this router `can_access_client` only ever
# exercises its TENANCY leg, never its assignment leg. That is worth stating
# rather than implying otherwise: the guards here are defence in depth against
# a cross-firm row and against the RBAC gate later widening, and these tests
# pin them at that. A row carrying this firm's firm_id and another firm's
# client_id should not exist — the guard is what stands there if one ever does.


def _seed_foreign_run(db):
    """A run row wearing THIS firm's firm_id but another firm's client_id.

    Seeded directly, because the service could not create one: it writes the
    pair it was handed after the guard passed. That is the point — this is the
    shape the row-level check exists to catch.
    """
    db.seed("reconciliation_runs", {
        "id": "RUN-FOREIGN", "firm_id": FIRM, "client_id": OTHER_CLIENT,
        "trigger": "manual", "status": "completed", "checks_run": 1,
        "findings_count": 1,
    })
    db.seed("reconciliation_findings", {
        "id": "FIND-FOREIGN", "run_id": "RUN-FOREIGN", "firm_id": FIRM,
        "client_id": OTHER_CLIENT, "check_name": "trial_balance",
        "severity": "critical", "detail": "unbalanced",
    })


def test_get_run_refuses_a_run_whose_client_is_out_of_reach(monkeypatch):
    db = _setup(monkeypatch)
    _seed_foreign_run(db)
    with pytest.raises(HTTPException) as exc:
        get_run("RUN-FOREIGN", PARTNER)
    assert exc.value.status_code == 404


def test_a_refused_run_and_an_unknown_one_are_the_same_404(monkeypatch):
    """The status code must not become an oracle for which run ids are real."""
    db = _setup(monkeypatch)
    _seed_foreign_run(db)
    with pytest.raises(HTTPException) as hidden:
        get_run("RUN-FOREIGN", PARTNER)
    with pytest.raises(HTTPException) as missing:
        get_run("no-such-run", PARTNER)
    assert hidden.value.status_code == missing.value.status_code == 404
    assert hidden.value.detail == missing.value.detail


def test_get_run_refuses_before_it_reads_the_findings(monkeypatch):
    """The findings carry the detail — account names, amounts, what is wrong
    with the books. A refusal that arrives after they are fetched still fetched
    them."""
    db = _setup(monkeypatch)
    _seed_foreign_run(db)
    touched = []
    real_table = db.table
    monkeypatch.setattr(db, "table",
                        lambda name: touched.append(name) or real_table(name))
    with pytest.raises(HTTPException):
        get_run("RUN-FOREIGN", PARTNER)
    assert "reconciliation_findings" not in touched, \
        "the findings were read despite the refusal"
    assert "reconciliation_runs" in touched, "nothing was read at all"


def test_get_run_will_not_hand_over_another_firms_run(monkeypatch):
    """The row-level firm filter is NOT redundant with the client check.

    `can_access_client` verifies the CLIENT belongs to the caller's firm (the
    F1 fix), so for a normal foreign row the two guards agree. They come apart
    on this shape: another firm's run pointing at a client that IS in my firm.
    The client check waves it through; only the firm filter on the query stops
    it. Pathological, and precisely why the filter is there.
    """
    db = _setup(monkeypatch)
    db.seed("reconciliation_runs", {
        "id": "RUN-ALIEN", "firm_id": "FIRM-OTHER", "client_id": CLIENT,
        "trigger": "manual", "status": "completed",
    })
    with pytest.raises(HTTPException) as exc:
        get_run("RUN-ALIEN", PARTNER)
    assert exc.value.status_code == 404


def test_resolve_finding_refuses_a_finding_whose_client_is_out_of_reach(monkeypatch):
    db = _setup(monkeypatch)
    _seed_foreign_run(db)
    with pytest.raises(HTTPException) as exc:
        resolve_finding("FIND-FOREIGN", ResolveFindingRequest(resolution_note="x"),
                        PARTNER)
    assert exc.value.status_code == 404
    row = [f for f in db.rows("reconciliation_findings") if f["id"] == "FIND-FOREIGN"][0]
    assert row.get("resolved_at") is None, "the finding was stamped anyway"


def test_a_refused_finding_and_an_unknown_one_are_the_same_404(monkeypatch):
    db = _setup(monkeypatch)
    _seed_foreign_run(db)
    with pytest.raises(HTTPException) as hidden:
        resolve_finding("FIND-FOREIGN", ResolveFindingRequest(), PARTNER)
    with pytest.raises(HTTPException) as missing:
        resolve_finding("no-such-finding", ResolveFindingRequest(), PARTNER)
    assert hidden.value.status_code == missing.value.status_code == 404
    assert hidden.value.detail == missing.value.detail
