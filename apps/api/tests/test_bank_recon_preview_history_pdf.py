"""
Banking Tier 2.4 + 2.6 + 2.7 — live tie-out preview, PDF statement, and the
certification history.

2.4  preview()   what the tie-out becomes if a selection were reconciled, so the
                 last few items of a period stop being reconcile → look →
                 unreconcile → try again. Computed by the SAME tie-out the real
                 reconcile uses; a second copy in the browser is exactly the
                 drift this codebase has paid for before.
2.6  PDF         a reconciliation is what a CA signs off and hands to a client
                 or an auditor, and a spreadsheet is not that document. For a
                 completed session it renders the FROZEN snapshot — a PDF that
                 recomputed live would be a different document from the one
                 that was signed off.
2.7  history()   a session can be completed, reopened and completed again; only
                 the newest snapshot lives on the session, the rest in
                 reopen_history. This exposes them.
"""
import pytest
from fastapi import HTTPException

import services.bank_reconciliation_service as brs
from services.bank_reconciliation_service import bank_reconciliation_service as svc

from tests.test_bank_reconciliation import FakeDB, FIRM, CLIENT, BA, START, END, _txn

REASON = "April rent was reconciled into March by mistake"


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


def _open(db, opening=100000, closing=160000):
    return svc.create_session(db, FIRM, CLIENT, BA, START, END,
                              opening_balance_paise=opening,
                              closing_balance_paise=closing, actor_id="u1")["id"]


# ══════════════════════════════════════════════════════════════════════════════
# 2.4 — live tie-out preview
# ══════════════════════════════════════════════════════════════════════════════

def test_preview_projects_the_full_selection_to_a_tie_out(db):
    """100000 + 50000 + 30000 − 20000 = 160000, the statement closing."""
    sid = _open(db)
    out = svc.preview(db, FIRM, sid, ["t1", "t2", "t3"])
    assert out["selected_count"] == 3
    assert out["would_tie_out"] is True
    assert out["projected"]["difference_paise"] == 0


def test_preview_shows_the_remaining_difference(db):
    sid = _open(db)
    out = svc.preview(db, FIRM, sid, ["t1", "t2"])          # t3 (₹300 credit) left out
    assert out["would_tie_out"] is False
    assert out["projected"]["difference_paise"] == 30000


def test_preview_reports_the_current_difference_too(db):
    """'Difference would be X (now Y)' — the comparison is the useful part."""
    sid = _open(db)
    out = svc.preview(db, FIRM, sid, ["t1"])
    assert out["current"]["difference_paise"] == 60000       # nothing reconciled yet
    assert out["projected"]["difference_paise"] == 10000


def test_preview_builds_on_what_is_already_reconciled(db):
    sid = _open(db)
    svc.reconcile(db, FIRM, sid, ["t1", "t2"], actor_id="u1")
    out = svc.preview(db, FIRM, sid, ["t3"])
    assert out["current"]["difference_paise"] == 30000
    assert out["would_tie_out"] is True


def test_preview_writes_nothing(db):
    """Read-only: after previewing everything, nothing is reconciled."""
    sid = _open(db)
    svc.preview(db, FIRM, sid, ["t1", "t2", "t3"])
    assert all(t.get("reconciliation_id") is None for t in db.store["bank_transactions"])
    assert svc.get_session(db, FIRM, sid)["counts"]["reconciled"] == 0


def test_preview_reports_ineligible_ids_rather_than_dropping_them(db):
    """Silently ignoring an id would make the projection quietly wrong."""
    sid = _open(db)
    out = svc.preview(db, FIRM, sid, ["t1", "does-not-exist"])
    assert out["selected_count"] == 1
    assert out["ineligible_ids"] == ["does-not-exist"]


def test_preview_treats_an_already_reconciled_id_as_ineligible(db):
    """It is already counted in `current`; adding it again would double it."""
    sid = _open(db)
    svc.reconcile(db, FIRM, sid, ["t1"], actor_id="u1")
    out = svc.preview(db, FIRM, sid, ["t1", "t2"])
    assert out["ineligible_ids"] == ["t1"]
    assert out["selected_count"] == 1
    assert out["projected"]["deposits_paise"] == 50000       # t1 counted once, not twice


def test_preview_with_an_empty_selection_equals_the_current_state(db):
    sid = _open(db)
    out = svc.preview(db, FIRM, sid, [])
    assert out["projected"] == out["current"]


def test_preview_matches_what_reconciling_actually_produces(db):
    """The claim that matters: preview and reality use the same tie-out."""
    sid = _open(db)
    projected = svc.preview(db, FIRM, sid, ["t1", "t2", "t3"])["projected"]
    svc.reconcile(db, FIRM, sid, ["t1", "t2", "t3"], actor_id="u1")
    actual = svc.get_session(db, FIRM, sid)["summary"]
    assert projected == actual


def test_preview_is_firm_scoped(db):
    sid = _open(db)
    with pytest.raises(HTTPException) as ei:
        svc.preview(db, "other-firm", sid, ["t1"])
    assert ei.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 2.7 — certification history
# ══════════════════════════════════════════════════════════════════════════════

def _complete(db, sid):
    svc.reconcile(db, FIRM, sid, ["t1", "t2", "t3"], actor_id="u1")
    svc.complete(db, FIRM, sid, actor_id="u1")


def test_history_of_a_session_never_completed_is_empty(db):
    sid = _open(db)
    h = svc.history(db, FIRM, sid)
    assert h["current"] is None and h["superseded"] == [] and h["reopen_count"] == 0


def test_history_shows_the_current_certification(db):
    sid = _open(db)
    _complete(db, sid)
    h = svc.history(db, FIRM, sid)
    assert h["current"] is not None
    assert h["current"]["ties_out"] is True
    assert h["current"]["summary"]["statement_closing_balance_paise"] == 160000
    assert h["superseded"] == []


def test_history_keeps_a_superseded_certification(db):
    sid = _open(db)
    _complete(db, sid)
    svc.reopen(db, FIRM, sid, REASON, actor_id="partner-1")

    h = svc.history(db, FIRM, sid)
    assert h["current"] is None, "reopened — there is no certification in force"
    assert len(h["superseded"]) == 1
    old = h["superseded"][0]
    assert old["reason"] == REASON
    assert old["completed_by"] == "u1"
    assert old["superseded_by"] == "partner-1"
    assert old["summary"]["statement_closing_balance_paise"] == 160000


def test_history_returns_superseded_newest_first(db):
    sid = _open(db)
    _complete(db, sid)
    svc.reopen(db, FIRM, sid, "First correction of the April statement", actor_id="p1")
    svc.complete(db, FIRM, sid, actor_id="u2")
    svc.reopen(db, FIRM, sid, "Second correction, bank charge was missed", actor_id="p2")

    h = svc.history(db, FIRM, sid)
    assert h["reopen_count"] == 2
    assert [s["reason"] for s in h["superseded"]] == [
        "Second correction, bank charge was missed",
        "First correction of the April statement",
    ]


def test_history_is_firm_scoped(db):
    sid = _open(db)
    with pytest.raises(HTTPException) as ei:
        svc.history(db, "other-firm", sid)
    assert ei.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 2.6 — PDF
# ══════════════════════════════════════════════════════════════════════════════

def _report(db, sid):
    return svc.report(db, FIRM, sid)


def test_pdf_renders_for_an_open_session(db):
    from services.bank_reconciliation_pdf_service import build_reconciliation_pdf
    sid = _open(db)
    svc.reconcile(db, FIRM, sid, ["t1"], actor_id="u1")
    pdf = build_reconciliation_pdf(_report(db, sid), {"name": "Test & Co"})
    assert pdf.startswith(b"%PDF-"), "not a PDF"
    assert len(pdf) > 1000


def test_pdf_renders_for_a_completed_session(db):
    from services.bank_reconciliation_pdf_service import build_reconciliation_pdf
    sid = _open(db)
    _complete(db, sid)
    pdf = build_reconciliation_pdf(_report(db, sid), {"name": "Test & Co"})
    assert pdf.startswith(b"%PDF-")


def test_pdf_of_a_completed_session_renders_the_frozen_snapshot(db):
    """`report` serves the snapshot for a completed session, so the PDF is the
    document that was signed off — not a live recomputation that could differ."""
    sid = _open(db)
    _complete(db, sid)
    before = _report(db, sid)["summary"]
    # Move the underlying data. The certified report must not follow it.
    for t in db.store["bank_transactions"]:
        t["credit_paise"] = 999999
    assert _report(db, sid)["summary"] == before


def test_pdf_renders_a_reopened_session(db):
    """A reopened period must not produce a PDF indistinguishable from one that
    was certified once and never touched — the header says so."""
    from services.bank_reconciliation_pdf_service import build_reconciliation_pdf
    sid = _open(db)
    _complete(db, sid)
    svc.reopen(db, FIRM, sid, REASON, actor_id="partner-1")
    report = _report(db, sid)
    assert report["reconciliation"]["reopen_count"] == 1
    assert build_reconciliation_pdf(report, {"name": "Test & Co"}).startswith(b"%PDF-")


def test_pdf_survives_a_session_with_no_lines(db):
    from services.bank_reconciliation_pdf_service import build_reconciliation_pdf
    sid = _open(db, opening=0, closing=0)
    pdf = build_reconciliation_pdf(_report(db, sid), {})
    assert pdf.startswith(b"%PDF-")
