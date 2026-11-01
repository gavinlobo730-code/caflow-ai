"""POST-A-265 (the wall clock) — the earlier filed periods of an amendment build are rebuilt several at a time, and the answer is the sequential one.

WHAT WAS WRONG
    The main GSTR-1 build carries the amendments the period owes, which asks `gstr1_exceptions` once per earlier filed period, and each
    answer rebuilds that period's GSTR-1 from the books: about a second apiece from a host a continent from its database. They ran one
    after another, so a February build waited on ten rebuilds and a build late in a year on up to nineteen, against a browser that
    gives up at forty-five seconds and never retries.

WHAT THIS PINS
    EVERY PERIOD  each earlier filed period is asked for exactly once;
    SAME ANSWER   built from a seeded client with filed months that have since drifted, the outstanding amendments are identical whether the
                  rebuilds run one at a time or four at a time, and the case is not vacuous (several periods really do propose amendments);
    ORDER         the reports come back in the order of the periods asked for, whichever finishes first, so the lists are built oldest first;
    BOUND         several run at once, never more than the ceiling, and a single period or a ceiling of one runs inline;
    FAILURE       a period that raises raises from the build, and the FIRST failing period in order is the one reported;
    CONTEXT       the caller's context (request id, error scope) is visible inside each rebuild.

WHAT IT DOES NOT DO
    It does not reduce the reads: each period is still rebuilt once per build, which is the remainder of POST-A-265 (read the books once and
    compare every filed payload in one pass).
"""
from __future__ import annotations

import contextvars
import threading
import time

import pytest

import routers.gst_workspace as gw
import services.gst_amendment_service as svc
import services.gst_return_service as grs
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM, CLIENT, GSTIN = "FIRM-A", "CLI", "27AAAAA0000A1Z2"


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [gw, grs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "gstin": GSTIN, "financial_year_start": "2025-04-01", "state_code": "27"})
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT, "name": "Acme", "gstin": "27BBBBB1111B1ZN",
                         "state_code": "27", "is_active": True})
    seed_standard_coa(d, FIRM, CLIENT)
    return d


def _invoice(db, invoice_no, invoice_date, taxable):
    cgst = sgst = taxable * 9 // 100
    return db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": "CUST", "invoice_no": invoice_no, "invoice_date": invoice_date,
        "status": "issued", "taxable_amount_paise": taxable, "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": 0,
        "total_paise": taxable + cgst + sgst, "is_interstate": False, "supply_state_code": "27", "supply_type": "taxable",
        "invoice_type": "Regular", "is_reverse_charge": False, "deleted_at": None})


def _file(db, period):
    payload = grs.gstr1_from_books(db, FIRM, CLIENT, period, GSTIN)["payload"]
    db.seed("gstr1_returns", {"firm_id": FIRM, "client_id": CLIENT, "period": period, "gstin": GSTIN, "status": "submitted",
                              "payload_json": payload, "submitted_at": "2025-12-01T00:00:00Z", "arn": f"ARN{period}"})


def _drifted_year(db):
    """Six months filed; then May and July's invoices are edited and a new invoice lands in June, so three periods have drifted."""
    rows = {}
    for m in range(4, 10):
        rows[m] = _invoice(db, f"INV-{m:02d}", f"2025-{m:02d}-10", 1_00_000_00)
    for m in range(4, 10):
        _file(db, f"{m:02d}2025")
    for m in (5, 7):
        for r in db.rows("client_sales_invoices"):
            if r["invoice_no"] == f"INV-{m:02d}":
                r["taxable_amount_paise"] = 1_20_000_00
                r["cgst_paise"] = r["sgst_paise"] = 1_20_000_00 * 9 // 100
                r["total_paise"] = r["taxable_amount_paise"] + r["cgst_paise"] + r["sgst_paise"]
    _invoice(db, "INV-06-LATE", "2025-06-20", 50_000_00)


# ── the answer is the sequential one ─────────────────────────────────────────────────────────────────────────────────────

def test_the_outstanding_amendments_are_the_same_one_at_a_time_and_four_at_a_time(db, monkeypatch):
    _drifted_year(db)
    monkeypatch.setattr(svc, "_MAX_PARALLEL_REBUILDS", 1)
    one_by_one = svc.outstanding_amendments(db, FIRM, CLIENT, "102025")
    monkeypatch.setattr(svc, "_MAX_PARALLEL_REBUILDS", 4)
    four_at_once = svc.outstanding_amendments(db, FIRM, CLIENT, "102025")
    assert len(one_by_one["source_periods"]) >= 3, "the case proposed nothing, so the comparison proves nothing"
    assert one_by_one["source_periods"] == sorted(one_by_one["source_periods"], key=svc._sort_key)
    assert four_at_once == one_by_one


def test_every_earlier_filed_period_is_asked_for_exactly_once(db, monkeypatch):
    _drifted_year(db)
    asked = []
    real = svc.gstr1_exceptions
    monkeypatch.setattr(svc, "gstr1_exceptions", lambda *a: asked.append(a[3]) or real(*a))
    svc.outstanding_amendments(db, FIRM, CLIENT, "102025")
    assert sorted(asked, key=svc._sort_key) == [f"{m:02d}2025" for m in range(4, 10)], "a period was skipped or asked for twice"


# ── order, bound, failure, context ───────────────────────────────────────────────────────────────────────────────────────

PERIODS = [f"{m:02d}2025" for m in range(4, 13)]


def test_the_reports_come_back_in_the_order_asked_for_whichever_finishes_first(monkeypatch):
    def slow_early(db, firm, client, period):
        time.sleep(0.04 * (len(PERIODS) - PERIODS.index(period)))      # the earliest period finishes last
        return {"status": "ok", "period": period}
    monkeypatch.setattr(svc, "gstr1_exceptions", slow_early)
    got = svc._exception_reports(None, FIRM, CLIENT, PERIODS)
    assert [r["period"] for r in got] == PERIODS


def test_several_run_at_once_and_never_more_than_the_ceiling(monkeypatch):
    live, peak, lock = 0, 0, threading.Lock()

    def counted(db, firm, client, period):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.05)
        with lock:
            live -= 1
        return {"status": "ok", "period": period}
    monkeypatch.setattr(svc, "gstr1_exceptions", counted)
    svc._exception_reports(None, FIRM, CLIENT, PERIODS)
    assert 2 <= peak <= svc._MAX_PARALLEL_REBUILDS, f"{peak} ran at once"


def test_one_period_or_a_ceiling_of_one_runs_inline_on_the_callers_thread(monkeypatch):
    seen = []
    monkeypatch.setattr(svc, "gstr1_exceptions", lambda db, f, c, p: seen.append(threading.current_thread()) or {"status": "ok", "period": p})
    svc._exception_reports(None, FIRM, CLIENT, PERIODS[:1])
    monkeypatch.setattr(svc, "_MAX_PARALLEL_REBUILDS", 1)
    svc._exception_reports(None, FIRM, CLIENT, PERIODS)
    assert set(seen) == {threading.current_thread()}
    assert svc._exception_reports(None, FIRM, CLIENT, []) == []


def test_the_first_failing_period_in_order_is_the_one_raised(monkeypatch):
    def failing(db, firm, client, period):
        if period == PERIODS[3]:
            time.sleep(0.1)                                             # the earlier failure is the slower one
            raise ValueError("first")
        if period == PERIODS[5]:
            raise KeyError("second")
        return {"status": "ok", "period": period}
    monkeypatch.setattr(svc, "gstr1_exceptions", failing)
    with pytest.raises(ValueError, match="first"):
        svc._exception_reports(None, FIRM, CLIENT, PERIODS)


def test_the_callers_context_is_visible_inside_each_rebuild(monkeypatch):
    var = contextvars.ContextVar("request_id", default="none")
    var.set("req-123")
    monkeypatch.setattr(svc, "gstr1_exceptions", lambda db, f, c, p: {"status": "ok", "period": p, "request_id": var.get()})
    got = svc._exception_reports(None, FIRM, CLIENT, PERIODS)
    assert {r["request_id"] for r in got} == {"req-123"}
