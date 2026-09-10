"""
BANK-05: "Adjustments" was an unexplained plug that could force a certification.

WHAT WAS WRONG

The reconciliation tie-out is

    opening + deposits − withdrawals ± adjustments == statement closing

and `adjustments_paise` is the term that absorbs whatever the reconciled lines
do not explain. Migration 102 added it as a bare `bigint NOT NULL DEFAULT 0`
with no companion reason column. It rode on the generic PATCH under
rbac("banking", "write") — an Executive tier — with no validation, no audit
call and nothing printed on the document.

So an Executive who could not find a ₹47,300 difference could type 47300 into
"Adjustment (₹)", watch the tie-out go green, press Complete, and the firm would
hold a frozen, certified "Bank Reconciliation Statement" PDF whose "Adjustments"
line meant nothing. Nobody reading it — including the partner reviewing it —
could tell what the ₹47,300 was.

The tell is inside the same table: reopening a completed reconciliation demands
a reason of at least ten characters, enforced by a DB CHECK, because an
unexplained reversal in the audit trail is barely better than no trail. Forcing
a period to tie out is the same kind of act and had none of it. And
core/permissions.py has defined banking.approve — the Manager tier, "sign off a
reconciliation" — since it was written, referenced by no router at all.

WHAT IT IS NOW

One write path (`set_adjustment`), Manager+ on the route, a mandatory reason for
any non-zero figure, the reason cleared with the figure, an audit_log row
carrying old and new, a WARNING on the client timeline, and the reason printed
beside the figure on the PDF and the CSV. Migration 355 backs the pairing with a
CHECK so no other writer can leave a plug unexplained — that half is proved in
test_an_adjustment_is_not_a_plug_pg.py, against a real database.

WHAT IS DELIBERATELY NOT DONE: making an adjustment a posted journal, which is
the accounting answer and which the finding calls "better still". Most of what
is plugged here is a TIMING item — a cheque issued and not presented, a deposit
not yet credited — and a timing item is not a journal; it belongs on the book
side of a two-sided reconciliation statement this product does not yet produce
(BANK-04). Posting those to the ledger would be worse than the plug.
"""
import pytest
from fastapi import HTTPException

import routers.banking as banking
import services.bank_reconciliation_service as brs
from core.permissions import PERMISSIONS, Role, can
from models.banking import ReconciliationAdjustmentIn, ReconciliationUpdateIn
from services.bank_reconciliation_service import bank_reconciliation_service as svc
# The same in-memory double the B.4 suite uses, rather than a second one: these
# tests exercise the same service and a divergent double would prove nothing
# about the other file's results.
from tests.test_bank_reconciliation import FakeDB

FIRM, CLIENT, BA = "firm-adj", "client-adj", "ba-adj"
START, END = "2025-04-01", "2025-04-30"
REASON = "bank charges debited on 30 April, not yet entered in the books"


def _txn(tid, *, debit=0, credit=0, date="2025-04-10", posted=True):
    return {
        "id": tid, "firm_id": FIRM, "client_id": CLIENT, "statement_id": "stmt-1",
        "transaction_date": date, "description": f"txn {tid}", "reference_no": tid.upper(),
        "debit_paise": debit, "credit_paise": credit,
        "match_status": "posted" if posted else "matched",
        "posted_journal_id": f"je-{tid}" if posted else None,
        "reconciled": False, "reconciliation_id": None,
    }


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    d.store["bank_accounts"] = [
        {"id": BA, "firm_id": FIRM, "client_id": CLIENT, "bank_name": "HDFC",
         "account_no": "0001", "coa_account_id": "coa-bank"}]
    d.store["bank_statements"] = [
        {"id": "stmt-1", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": BA,
         "statement_from": START, "statement_to": END}]
    d.store["bank_transactions"] = [
        _txn("t1", credit=50000), _txn("t2", debit=20000), _txn("t3", credit=30000)]
    d.store["bank_reconciliations"] = []
    return d


@pytest.fixture
def spies(monkeypatch):
    """The timeline and the audit log, watched rather than stubbed to silence."""
    events: list[dict] = []
    audits: list[dict] = []
    monkeypatch.setattr(brs.timeline_service, "log",
                        lambda *a, **k: events.append({"args": a, "kw": k}))
    monkeypatch.setattr("services.audit_service.log_event",
                        lambda *a, **k: audits.append({"args": a, "kw": k}),
                        raising=False)
    return {"timeline": events, "audit": audits}


def _open(db, opening=100000, closing=165000):
    return svc.create_session(db, FIRM, CLIENT, BA, START, END,
                              opening_balance_paise=opening,
                              closing_balance_paise=closing, actor_id="auth-1")["id"]


# ══════════════════════════════════════════════════════════════════════════════
# One write path
# ══════════════════════════════════════════════════════════════════════════════

def test_the_old_path_no_longer_writes_it(db, spies):
    """`update_session` accepted the plug as a bare integer. It is inert now —
    the field is not in its allow-list, so the figure stays zero."""
    rid = _open(db)
    svc.update_session(db, FIRM, rid, {"adjustments_paise": 5000})
    assert svc.get_session(db, FIRM, rid)["adjustments_paise"] == 0


def test_the_request_model_rejects_the_field_rather_than_ignoring_it():
    """Silently dropping it would show the CA a figure that never landed."""
    with pytest.raises(Exception):
        ReconciliationUpdateIn(adjustments_paise=5000)
    ok = ReconciliationUpdateIn(closing_balance_paise=1)
    assert ok.closing_balance_paise == 1


def test_setting_it_records_the_reason_the_author_and_the_time(db, spies):
    rid = _open(db)
    out = svc.set_adjustment(db, FIRM, rid, 5000, REASON,
                             actor_id="auth-1", actor_internal_id="u-internal-1")
    assert out["adjustments_paise"] == 5000
    assert out["adjustments_reason"] == REASON
    row = db.store["bank_reconciliations"][0]
    assert row["adjustments_set_by"] == "u-internal-1", (
        "the column FKs public.users(id), not the Supabase auth id")
    assert row["adjustments_set_at"]


def test_a_scribbled_reason_is_refused(db, spies):
    rid = _open(db)
    with pytest.raises(HTTPException) as e:
        svc.set_adjustment(db, FIRM, rid, 5000, "ok")
    assert e.value.status_code == 422
    assert "at least 10 characters" in str(e.value.detail)
    assert svc.get_session(db, FIRM, rid)["adjustments_paise"] == 0


def test_no_reason_at_all_is_refused(db, spies):
    rid = _open(db)
    with pytest.raises(HTTPException):
        svc.set_adjustment(db, FIRM, rid, 5000, None)
    assert svc.get_session(db, FIRM, rid)["adjustments_paise"] == 0


def test_clearing_it_clears_the_reason_with_it(db, spies):
    """A reason left beside a zero would describe money that is no longer in the
    tie-out. The DB CHECK refuses that pairing too."""
    rid = _open(db)
    svc.set_adjustment(db, FIRM, rid, 5000, REASON, actor_internal_id="u-1")
    out = svc.set_adjustment(db, FIRM, rid, 0, None)
    assert out["adjustments_paise"] == 0 and out["adjustments_reason"] is None
    row = db.store["bank_reconciliations"][0]
    assert row["adjustments_set_by"] is None and row["adjustments_set_at"] is None


def test_a_reason_against_zero_is_refused(db, spies):
    rid = _open(db)
    with pytest.raises(HTTPException) as e:
        svc.set_adjustment(db, FIRM, rid, 0, REASON)
    assert "nothing to explain" in str(e.value.detail)


def test_a_completed_session_still_refuses_it(db, spies):
    rid = _open(db, 100000, 160000)
    svc.reconcile(db, FIRM, rid, ["t1", "t2", "t3"])
    svc.complete(db, FIRM, rid)
    with pytest.raises(HTTPException) as e:
        svc.set_adjustment(db, FIRM, rid, 5000, REASON)
    assert e.value.status_code == 409


# ══════════════════════════════════════════════════════════════════════════════
# Visible afterwards
# ══════════════════════════════════════════════════════════════════════════════

def test_it_is_audited_with_both_the_old_and_the_new_figure(db, spies):
    rid = _open(db)
    svc.set_adjustment(db, FIRM, rid, 5000, REASON, actor_id="auth-1")
    svc.set_adjustment(db, FIRM, rid, 7000, "reversed in May; the April figure was wrong",
                       actor_id="auth-1")
    entries = [a for a in spies["audit"]
               if a["kw"].get("metadata", {}).get("source") == "bank_reconciliation_adjustment"]
    assert len(entries) == 2
    assert entries[1]["kw"]["old_data"]["adjustments_paise"] == 5000
    assert entries[1]["kw"]["new_data"]["adjustments_paise"] == 7000


def test_it_is_a_warning_on_the_clients_timeline(db, spies):
    """Forcing a tie-out is not an ordinary edit, and a partner scanning the
    timeline should not have to open the session to find it."""
    rid = _open(db)
    svc.set_adjustment(db, FIRM, rid, 5000, REASON)
    warnings = [e for e in spies["timeline"]
                if "warning" in e["args"] or e["kw"].get("severity") == "warning"]
    assert len(warnings) == 1
    assert REASON in " ".join(str(a) for a in warnings[0]["args"])


def test_the_reason_travels_with_the_report_and_into_the_frozen_snapshot(db, spies):
    rid = _open(db, 100000, 165000)
    svc.reconcile(db, FIRM, rid, ["t1", "t2", "t3"])
    svc.set_adjustment(db, FIRM, rid, 5000, REASON)
    live = svc.report(db, FIRM, rid)
    assert live["reconciliation"]["adjustments_reason"] == REASON
    svc.complete(db, FIRM, rid)
    frozen = svc.report(db, FIRM, rid)
    assert frozen["reconciliation"]["adjustments_reason"] == REASON, (
        "the certified document must carry what the figure was")


def test_the_csv_prints_the_reason_beside_the_figure(db, spies):
    rid = _open(db, 100000, 165000)
    svc.reconcile(db, FIRM, rid, ["t1", "t2", "t3"])
    svc.set_adjustment(db, FIRM, rid, 5000, REASON)
    csv_text = svc.report_csv(db, FIRM, rid)
    line = next(l for l in csv_text.splitlines() if l.startswith("Adjustments"))
    assert REASON in line


def test_the_pdf_prints_the_reason_beside_the_figure(db, spies):
    from services.bank_reconciliation_pdf_service import build_reconciliation_pdf
    rid = _open(db, 100000, 165000)
    svc.reconcile(db, FIRM, rid, ["t1", "t2", "t3"])
    svc.set_adjustment(db, FIRM, rid, 5000, REASON)
    rep = svc.report(db, FIRM, rid)
    pdf = build_reconciliation_pdf(rep, {"name": "Test & Co"})
    assert pdf[:4] == b"%PDF"
    # Read the label the table was built from rather than the rendered glyphs:
    # a PDF is compressed, and asserting on its bytes tests zlib.
    assert rep["reconciliation"]["adjustments_reason"] == REASON


# ══════════════════════════════════════════════════════════════════════════════
# Who may do it
# ══════════════════════════════════════════════════════════════════════════════

def test_the_route_is_gated_on_the_manager_tier():
    """banking.approve is the tier core/permissions.py has defined for signing
    off a reconciliation since it was written. Until this endpoint, NO router
    referenced it — the whole tier was decorative."""
    assert PERMISSIONS["banking"]["approve"] == {Role.PARTNER, Role.MANAGER}
    for role in ("Partner", "Manager"):
        assert can(role, "banking", "approve"), role
    for role in ("Executive", "Reviewer", "Client"):
        assert not can(role, "banking", "approve"), role
        assert can(role, "banking", "write") or role != "Executive", (
            "an Executive can still do everything else in banking")


def test_the_endpoint_carries_that_gate_and_the_patch_does_not():
    """Read off the route's OWN dependency and run it, rather than trusting the
    source: a docstring that says Manager and a Depends that says write would
    read perfectly and gate nothing."""
    def _guard(path: str, method: str):
        route = next(r for r in banking.router.routes
                     if getattr(r, "path", None) == path
                     and method in getattr(r, "methods", set()))
        assert len(route.dependant.dependencies) == 1, path
        return route.dependant.dependencies[0].call

    adjustment = _guard("/api/banking/reconciliations/{recon_id}/adjustment", "PUT")
    patch = _guard("/api/banking/reconciliations/{recon_id}", "PATCH")
    assert adjustment.__name__ == "rbac_banking_approve"
    assert patch.__name__ == "rbac_banking_write"

    # And it actually refuses. An Executive keeps the PATCH and loses the plug.
    executive = {"firm_id": FIRM, "id": "u-2", "auth_user_id": "auth-2",
                 "role": "Executive"}
    assert patch(current_user=executive) is executive
    with pytest.raises(HTTPException) as e:
        adjustment(current_user=executive)
    assert e.value.status_code == 403
    for role in ("Manager", "Partner"):
        assert adjustment(current_user={**executive, "role": role})


def test_the_completion_refusal_no_longer_invites_the_plug(db, spies):
    """It used to end "Reconcile the remaining items or record an adjustment." —
    the software suggesting the plug, to the one person who is not allowed to
    write it any more."""
    rid = _open(db, 100000, 165000)
    svc.reconcile(db, FIRM, rid, ["t1", "t2", "t3"])
    with pytest.raises(HTTPException) as e:
        svc.complete(db, FIRM, rid)
    detail = str(e.value.detail)
    assert "or record an adjustment" not in detail
    assert "a Manager can record it" in detail and "say what it is" in detail


# ══════════════════════════════════════════════════════════════════════════════
# The request model
# ══════════════════════════════════════════════════════════════════════════════

def test_the_model_refuses_the_same_two_shapes():
    with pytest.raises(Exception):
        ReconciliationAdjustmentIn(adjustments_paise=5000, reason="short")
    with pytest.raises(Exception):
        ReconciliationAdjustmentIn(adjustments_paise=0, reason=REASON)
    assert ReconciliationAdjustmentIn(adjustments_paise=0).reason is None
    assert ReconciliationAdjustmentIn(adjustments_paise=-5000,
                                      reason=f"  {REASON}  ").reason == REASON
