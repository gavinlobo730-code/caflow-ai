"""
Banking Tier 2.3 + 2.5 — the reconciliation discrepancy check, and reopening a
completed reconciliation.

2.5 REOPEN
    A completed reconciliation is immutable, and that is right — it is a period a
    CA has certified. But immutability with no escape hatch is its own failure
    mode: a period completed against a mistake was previously permanent, and the
    only remedy was to leave the books wrong. The discipline is not in forbidding
    the action but in making it visible: Partner-only, reason required,
    audit-logged, certified snapshot preserved rather than overwritten.

2.3 DISCREPANCY CHECK
    Completing freezes a snapshot of exactly which transactions were reconciled
    and for how much. Nothing stopped the underlying data moving afterwards — and
    the frozen report is precisely what makes the session immune to noticing. The
    check compares each completed session's snapshot against live data.
"""
import pytest
from fastapi import HTTPException

import services.bank_reconciliation_service as brs
from services.bank_reconciliation_service import bank_reconciliation_service as svc
from services.reconciliation_service import check_bank_reconciliation_discrepancies
from models.banking import ReconciliationReopenIn

from tests.test_bank_reconciliation import FakeDB, FIRM, CLIENT, BA, START, END, _txn

GOOD_REASON = "April rent was reconciled into March by mistake"


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(brs.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None, raising=False)
    d = FakeDB()
    d.store["bank_accounts"] = [
        {"id": BA, "firm_id": FIRM, "client_id": CLIENT, "bank_name": "HDFC",
         "account_no": "0001", "coa_account_id": "coa-bank", "opening_balance_paise": 100000},
    ]
    d.store["bank_statements"] = [
        {"id": "stmt-1", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": BA,
         "statement_from": START, "statement_to": END},
    ]
    d.store["bank_transactions"] = [
        _txn("t1", credit=50000), _txn("t2", debit=20000), _txn("t3", credit=30000),
    ]
    d.store["bank_reconciliations"] = []
    return d


def _completed(db):
    """A completed session: 100000 + 50000 + 30000 − 20000 = 160000."""
    sid = svc.create_session(db, FIRM, CLIENT, BA, START, END,
                             opening_balance_paise=100000,
                             closing_balance_paise=160000, actor_id="u1")["id"]
    svc.reconcile(db, FIRM, sid, ["t1", "t2", "t3"], actor_id="u1")
    svc.complete(db, FIRM, sid, actor_id="u1")
    return sid


# ══════════════════════════════════════════════════════════════════════════════
# 2.5 — reopen
# ══════════════════════════════════════════════════════════════════════════════

def test_reopen_returns_the_session_to_in_progress(db):
    sid = _completed(db)
    out = svc.reopen(db, FIRM, sid, GOOD_REASON, actor_id="partner-1")
    assert out["status"] == "in_progress"
    row = db.store["bank_reconciliations"][0]
    assert row["completed_at"] is None and row["completed_by"] is None


def test_reopen_records_who_when_and_why(db):
    sid = _completed(db)
    svc.reopen(db, FIRM, sid, GOOD_REASON, actor_id="partner-1")
    row = db.store["bank_reconciliations"][0]
    assert row["reopen_reason"] == GOOD_REASON
    assert row["reopened_by"] == "partner-1"
    assert row["reopened_at"]
    assert row["reopen_count"] == 1


def test_reopen_preserves_the_certified_snapshot(db):
    """The whole point: completing again overwrites `snapshot`, so the report the
    CA signed off must be carried into reopen_history first."""
    sid = _completed(db)
    certified = db.store["bank_reconciliations"][0]["snapshot"]
    assert certified is not None

    svc.reopen(db, FIRM, sid, GOOD_REASON, actor_id="partner-1")
    history = db.store["bank_reconciliations"][0]["reopen_history"]
    assert len(history) == 1
    assert history[0]["snapshot"] == certified
    assert history[0]["reason"] == GOOD_REASON
    assert history[0]["completed_by"] == "u1", "who certified it must survive too"


def test_a_second_reopen_keeps_both_certifications(db):
    sid = _completed(db)
    svc.reopen(db, FIRM, sid, GOOD_REASON, actor_id="partner-1")
    svc.complete(db, FIRM, sid, actor_id="u2")
    svc.reopen(db, FIRM, sid, "Second correction, bank charge was missed", actor_id="partner-1")

    history = db.store["bank_reconciliations"][0]["reopen_history"]
    assert len(history) == 2
    assert db.store["bank_reconciliations"][0]["reopen_count"] == 2
    assert all(h["snapshot"] is not None for h in history)
    assert history[0]["completed_by"] == "u1" and history[1]["completed_by"] == "u2"


def test_reopen_keeps_transactions_reconciled(db):
    """Reopening is not un-reconciling. It restores the ability to change things;
    the CA then unticks whatever was actually wrong."""
    sid = _completed(db)
    svc.reopen(db, FIRM, sid, GOOD_REASON, actor_id="partner-1")
    still = [t for t in db.store["bank_transactions"] if t.get("reconciliation_id") == sid]
    assert len(still) == 3


def test_a_reopened_session_can_be_edited_again(db):
    """_require_mutable must now let this session through — that is what
    reopening is for."""
    sid = _completed(db)
    svc.reopen(db, FIRM, sid, GOOD_REASON, actor_id="partner-1")
    svc.unreconcile(db, FIRM, sid, ["t3"], actor_id="u1")
    remaining = [t for t in db.store["bank_transactions"] if t.get("reconciliation_id") == sid]
    assert len(remaining) == 2


def test_completing_again_re_runs_both_guards(db):
    """A reopened period is not waved back through. After unreconciling a line
    the statement no longer ties out, so completion is refused exactly as it
    would be for a fresh session."""
    sid = _completed(db)
    svc.reopen(db, FIRM, sid, GOOD_REASON, actor_id="partner-1")
    svc.unreconcile(db, FIRM, sid, ["t3"], actor_id="u1")
    with pytest.raises(HTTPException) as ei:
        svc.complete(db, FIRM, sid, actor_id="u1")
    assert ei.value.status_code == 422


def test_cannot_reopen_a_session_that_is_not_completed(db):
    sid = svc.create_session(db, FIRM, CLIENT, BA, START, END,
                             opening_balance_paise=100000,
                             closing_balance_paise=160000, actor_id="u1")["id"]
    with pytest.raises(HTTPException) as ei:
        svc.reopen(db, FIRM, sid, GOOD_REASON, actor_id="partner-1")
    assert ei.value.status_code == 409


def test_reopen_requires_a_substantive_reason(db):
    sid = _completed(db)
    for bad in ("", "   ", "typo", "too short"):
        with pytest.raises(HTTPException) as ei:
            svc.reopen(db, FIRM, sid, bad, actor_id="partner-1")
        assert ei.value.status_code == 422
    assert db.store["bank_reconciliations"][0]["status"] == "completed"


def test_reopen_is_firm_scoped(db):
    sid = _completed(db)
    with pytest.raises(HTTPException) as ei:
        svc.reopen(db, "other-firm", sid, GOOD_REASON, actor_id="partner-1")
    assert ei.value.status_code == 404


def test_reopen_model_rejects_a_thin_reason():
    with pytest.raises(ValueError):
        ReconciliationReopenIn(reason="oops")
    assert ReconciliationReopenIn(reason=f"  {GOOD_REASON}  ").reason == GOOD_REASON


def test_reopen_is_partner_only():
    """Same gate as posting a journal and setting a year lock."""
    from core.permissions import can
    assert can("Partner", "accounting", "approve")
    assert not can("Manager", "accounting", "approve")
    assert not can("Executive", "accounting", "approve")


# ══════════════════════════════════════════════════════════════════════════════
# 2.3 — discrepancy check
# ══════════════════════════════════════════════════════════════════════════════

class _Entry:
    """Minimal stand-in for domain.reporting.model.JournalEntry."""
    def __init__(self, eid): self.id = eid; self.lines = (); self.reference_no = None


def _entries(*ids):
    return {i: _Entry(i) for i in ids}


ALL_JE = ("je-t1", "je-t2", "je-t3")


def test_a_clean_completed_reconciliation_reports_nothing(db):
    _completed(db)
    assert check_bank_reconciliation_discrepancies(db, FIRM, CLIENT, _entries(*ALL_JE)) == []


def test_detaching_a_reconciled_transaction_is_flagged(db):
    _completed(db)
    for t in db.store["bank_transactions"]:
        if t["id"] == "t3":
            t["reconciliation_id"] = None

    out = check_bank_reconciliation_discrepancies(db, FIRM, CLIENT, _entries(*ALL_JE))
    assert len(out) == 1
    assert out[0]["check_name"] == "bank_reconciliation_discrepancy"
    assert out[0]["severity"] == "critical"
    assert out[0]["details"]["reason"] == "detached"
    assert out[0]["details"]["transaction_id"] == "t3"


def test_changing_a_reconciled_amount_is_flagged(db):
    _completed(db)
    for t in db.store["bank_transactions"]:
        if t["id"] == "t1":
            t["credit_paise"] = 55000          # certified at 50000

    out = check_bank_reconciliation_discrepancies(db, FIRM, CLIENT, _entries(*ALL_JE))
    amount_findings = [f for f in out if f["details"]["reason"] == "amount_changed"]
    assert len(amount_findings) == 1
    assert amount_findings[0]["details"]["snapshot_credit_paise"] == 50000
    assert amount_findings[0]["details"]["live_credit_paise"] == 55000


def test_reversing_the_journal_behind_a_reconciled_line_is_flagged(db):
    """The certified cash movement has been undone in the books — the period
    still claims a tie-out that is no longer true."""
    _completed(db)
    out = check_bank_reconciliation_discrepancies(
        db, FIRM, CLIENT, _entries("je-t1", "je-t2"))   # je-t3 no longer posted

    reversed_findings = [f for f in out if f["details"]["reason"] == "journal_not_posted"]
    assert len(reversed_findings) == 1
    assert reversed_findings[0]["details"]["journal_entry_id"] == "je-t3"
    assert reversed_findings[0]["severity"] == "critical"


def test_an_open_session_is_not_checked(db):
    """Only completed sessions carry a certification to compare against."""
    sid = svc.create_session(db, FIRM, CLIENT, BA, START, END,
                             opening_balance_paise=100000,
                             closing_balance_paise=160000, actor_id="u1")["id"]
    svc.reconcile(db, FIRM, sid, ["t1"], actor_id="u1")
    assert check_bank_reconciliation_discrepancies(db, FIRM, CLIENT, _entries(*ALL_JE)) == []


def test_a_reopened_session_is_not_checked(db):
    """Its snapshot is preserved in reopen_history precisely because it no longer
    describes a current certification. Comparing against it would manufacture
    findings for a period someone is already fixing."""
    sid = _completed(db)
    svc.reopen(db, FIRM, sid, GOOD_REASON, actor_id="partner-1")
    svc.unreconcile(db, FIRM, sid, ["t3"], actor_id="u1")
    assert check_bank_reconciliation_discrepancies(db, FIRM, CLIENT, _entries(*ALL_JE)) == []


def test_the_check_is_client_scoped(db):
    _completed(db)
    for t in db.store["bank_transactions"]:
        if t["id"] == "t3":
            t["reconciliation_id"] = None
    assert check_bank_reconciliation_discrepancies(db, FIRM, "other-client", _entries(*ALL_JE)) == []


def test_a_session_with_no_snapshot_is_skipped(db):
    """Sessions completed before snapshots existed have nothing to compare."""
    _completed(db)
    db.store["bank_reconciliations"][0]["snapshot"] = None
    assert check_bank_reconciliation_discrepancies(db, FIRM, CLIENT, _entries(*ALL_JE)) == []


def test_the_check_is_registered_in_the_engine():
    """A check nobody runs is not a check."""
    from services.reconciliation_service import _CHECKS
    assert check_bank_reconciliation_discrepancies in _CHECKS
