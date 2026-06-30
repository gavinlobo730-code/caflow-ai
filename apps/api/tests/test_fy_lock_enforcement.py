"""
Financial-year lock enforcement (multi-year hardening #2).

The audit found locked-year posting could slip through on edit / deferred-posting
paths, and that the validator failed OPEN on DB errors. This verifies:

  A. period_validation_service.validate_posting_date:
       - blocks a locked year, allows an open year, and FAILS CLOSED on RPC error.
  B. Every posting/editing path now enforces the lock and BLOCKS (422):
       invoice edit + issue, purchase-bill edit + receive, credit-note issue,
       journal reversal — and an open-year edit still succeeds.
"""
import pytest
from fastapi import HTTPException

import services.period_validation_service as pvs
from services.period_validation_service import period_validation_service, get_fy_for_date

import routers.sales_invoices as si
import routers.purchase_bills as pb
import routers.credit_notes as cn
import routers.accounting as acct
from models.invoices import SalesInvoiceUpdateIn, PurchaseBillUpdateIn
from models.accounting import JournalReversalIn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}
LOCKED = "2024-06-15"   # pretend FY 2024-25 is locked
OPEN = "2025-06-15"     # FY 2025-26 open


# ── A. The validator itself ──────────────────────────────────────────────────

def _fake_get_supabase(rpc_impl):
    class _RPC:
        def execute(self):
            return type("R", (), {"data": rpc_impl()})()
    class _DB:
        def rpc(self, name, params):
            return _RPC()
    return lambda: _DB()


def test_validator_blocks_locked_year(monkeypatch):
    monkeypatch.setattr(pvs, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", _fake_get_supabase(lambda: [True]))
    with pytest.raises(HTTPException) as e:
        period_validation_service.validate_posting_date(FIRM, LOCKED)
    assert e.value.status_code == 422


def test_validator_allows_open_year(monkeypatch):
    monkeypatch.setattr(pvs, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", _fake_get_supabase(lambda: [False]))
    period_validation_service.validate_posting_date(FIRM, OPEN)   # no raise


def test_validator_fails_closed_on_rpc_error(monkeypatch):
    monkeypatch.setattr(pvs, "_USE_MOCK", False)

    def _boom():
        raise RuntimeError("db unavailable")
    class _DB:
        def rpc(self, *a, **k):
            class _R:
                def execute(self_):
                    _boom()
            return _R()
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: _DB())
    with pytest.raises(HTTPException) as e:
        period_validation_service.validate_posting_date(FIRM, OPEN)
    assert e.value.status_code == 422   # blocked, not silently allowed


def test_validator_allows_on_null_result(monkeypatch):
    # is_fy_locked returns a definitive boolean (coalesce false); a NULL/None result
    # means "not locked" → allow. Only a genuine RPC EXCEPTION is fail-closed.
    monkeypatch.setattr(pvs, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", _fake_get_supabase(lambda: None))
    period_validation_service.validate_posting_date(FIRM, OPEN)   # no raise


# ── B. Enforcement across posting/editing paths ──────────────────────────────

def _block_locked(firm_id, date_str):
    """Stand-in validator: blocks the LOCKED financial year, allows others.
    (wire_e2e neutralises the real one; we re-install this spy afterwards.)"""
    if date_str and get_fy_for_date(date_str) == get_fy_for_date(LOCKED):
        raise HTTPException(status_code=422, detail="Cannot post to a locked financial year")


def _wire(monkeypatch, mods):
    db = FakeDB()
    wire_e2e(monkeypatch, db, mods)
    monkeypatch.setattr(period_validation_service, "validate_posting_date", _block_locked)
    return db


def test_invoice_edit_blocked_in_locked_year(monkeypatch):
    db = _wire(monkeypatch, [si])
    db.seed("client_sales_invoices", {"id": "INV", "firm_id": FIRM, "client_id": "CLI",
                                      "status": "draft", "invoice_date": LOCKED})
    with pytest.raises(HTTPException) as e:
        si.update_invoice("INV", SalesInvoiceUpdateIn(notes="x"), CALLER)
    assert e.value.status_code == 422


def test_invoice_edit_allowed_in_open_year(monkeypatch):
    db = _wire(monkeypatch, [si])
    db.seed("client_sales_invoices", {"id": "INV", "firm_id": FIRM, "client_id": "CLI",
                                      "status": "draft", "invoice_date": OPEN})
    res = si.update_invoice("INV", SalesInvoiceUpdateIn(notes="ok"), CALLER)
    assert res["success"] is True


def test_invoice_edit_blocked_when_moving_into_locked_year(monkeypatch):
    db = _wire(monkeypatch, [si])
    db.seed("client_sales_invoices", {"id": "INV", "firm_id": FIRM, "client_id": "CLI",
                                      "status": "draft", "invoice_date": OPEN})
    with pytest.raises(HTTPException) as e:
        si.update_invoice("INV", SalesInvoiceUpdateIn(invoice_date=LOCKED), CALLER)
    assert e.value.status_code == 422


def test_invoice_issue_blocked_in_locked_year(monkeypatch):
    db = _wire(monkeypatch, [si])
    db.seed("client_sales_invoices", {"id": "INV", "firm_id": FIRM, "client_id": "CLI",
                                      "status": "draft", "invoice_date": LOCKED})
    with pytest.raises(HTTPException) as e:
        si.issue_invoice("INV", CALLER)
    assert e.value.status_code == 422


def test_bill_edit_blocked_in_locked_year(monkeypatch):
    db = _wire(monkeypatch, [pb])
    db.seed("purchase_bills", {"id": "B", "firm_id": FIRM, "client_id": "CLI",
                               "status": "draft", "bill_date": LOCKED})
    with pytest.raises(HTTPException) as e:
        pb.update_purchase_bill("B", PurchaseBillUpdateIn(notes="x"), CALLER)
    assert e.value.status_code == 422


def test_bill_receive_blocked_in_locked_year(monkeypatch):
    db = _wire(monkeypatch, [pb])
    db.seed("purchase_bills", {"id": "B", "firm_id": FIRM, "client_id": "CLI",
                               "status": "draft", "bill_date": LOCKED})
    with pytest.raises(HTTPException) as e:
        pb.receive_purchase_bill("B", CALLER)
    assert e.value.status_code == 422


def test_credit_note_issue_blocked_in_locked_year(monkeypatch):
    db = _wire(monkeypatch, [cn])
    db.seed("credit_notes", {"id": "CN", "firm_id": FIRM, "client_id": "CLI",
                             "status": "draft", "credit_note_date": LOCKED})
    with pytest.raises(HTTPException) as e:
        cn.issue_credit_note("CN", CALLER)
    assert e.value.status_code == 422


def test_journal_reversal_blocked_in_locked_year(monkeypatch):
    db = _wire(monkeypatch, [acct])
    monkeypatch.setenv("SUPABASE_URL", "test://db")   # reverse() gates on this env var
    db.seed("journal_entries", {"id": "JE", "firm_id": FIRM, "client_id": "CLI",
                                "is_posted": True, "reference_no": "R1"})
    with pytest.raises(HTTPException) as e:
        acct.reverse_journal_entry("JE", JournalReversalIn(reversal_date=LOCKED), CALLER)
    assert e.value.status_code == 422
