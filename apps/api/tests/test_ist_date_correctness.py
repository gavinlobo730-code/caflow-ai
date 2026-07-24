"""
Phase 1 — Critical Accounting & Financial Date Correctness (backend).

Proves that invoice generation, invoice numbering, online-payment receipt
dates, and financial-year-scoped reporting all resolve "today" via the
shared core.ist_clock helper — not a bare UTC server clock — so a
transaction created between IST 00:00 and 05:29 (UTC 18:30-23:59 the
previous day) posts into the correct financial year instead of silently
falling into the prior one.

Each test freezes core.ist_clock's notion of "now" (see test_ist_clock.py
for the freeze mechanics and direct coverage of the helper itself) and
drives the real production function end-to-end.
"""
import datetime as _datetime_module
from datetime import date, datetime, timezone

import core.ist_clock as ist_clock
import services.invoice_generation_service as invoice_gen
import services.payment_service as payment_service
import domain.reporting.service as reporting_service
from repositories.engagement_repository import engagement_repo
from repositories.invoice_repository import invoice_repo
from tests.e2e_harness import FakeDB, seed_standard_coa

FIRM = "FIRM-IST-TEST"
CLIENT = "CLI-IST-TEST"


def _freeze_utc(monkeypatch, utc_iso: str) -> datetime:
    """Freeze the shared IST clock to a fixed UTC instant (see test_ist_clock.py).
    Patches core.ist_clock's own `datetime` symbol, which every caller of
    ist_today()/ist_now() resolves through regardless of where it's imported —
    one freeze point covers invoice generation, numbering, receipts and FY math."""
    fixed = datetime.fromisoformat(utc_iso).replace(tzinfo=timezone.utc)

    class _FrozenDateTime(_datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz is not None else fixed

    monkeypatch.setattr(ist_clock, "datetime", _FrozenDateTime)
    return fixed


def _engagement(engagement_id, **overrides):
    base = {
        "id": engagement_id,
        "firm_id": FIRM,
        "client_id": CLIENT,
        "fee_paise": 500000,
        "billing_cycle": "Monthly",
    }
    base.update(overrides)
    return base


# ── 1. Invoice generation defaults invoice_date via IST, not UTC ────────────

def test_invoice_from_engagement_defaults_to_ist_date_across_fy_boundary(monkeypatch):
    # 31 Mar 23:59 UTC == 1 Apr 05:29 IST — a CA in India is already working in
    # the new financial year; the invoice must land on 1 April / new FY, not
    # 31 March / old FY.
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    eng_id = "ENG-FY-BOUNDARY"
    monkeypatch.setattr(engagement_repo, "get_or_raise", lambda _id: _engagement(eng_id))

    invoice_id = invoice_gen.generate_invoice_from_engagement(eng_id)
    invoice = invoice_repo.find_by_id(invoice_id)

    assert invoice["invoice_date"] == "2026-04-01"
    assert invoice["due_date"] == "2026-05-01"            # invoice_date + 30-day credit period
    assert invoice["invoice_no"].split("-")[1] == "2026"  # FY 2026-27 (starts 1 Apr), not 2025


def test_invoice_from_engagement_unaffected_mid_year(monkeypatch):
    _freeze_utc(monkeypatch, "2026-07-05T09:00:00")       # 2:30 PM IST, no boundary involved
    eng_id = "ENG-MIDYEAR"
    monkeypatch.setattr(engagement_repo, "get_or_raise", lambda _id: _engagement(eng_id))

    invoice_id = invoice_gen.generate_invoice_from_engagement(eng_id)
    invoice = invoice_repo.find_by_id(invoice_id)

    assert invoice["invoice_date"] == "2026-07-05"


def test_invoice_from_engagement_explicit_month_overrides_default(monkeypatch):
    # Existing functionality preserved: an explicit invoice_month always wins
    # over "today", frozen or not — the fix only changes the *default*.
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    eng_id = "ENG-EXPLICIT"
    monkeypatch.setattr(engagement_repo, "get_or_raise", lambda _id: _engagement(eng_id))

    invoice_id = invoice_gen.generate_invoice_from_engagement(eng_id, invoice_month="2025-12-15")
    invoice = invoice_repo.find_by_id(invoice_id)

    assert invoice["invoice_date"] == "2025-12-15"


def test_invoice_from_time_entries_defaults_to_ist_date(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: FakeDB())
    eng_id = "ENG-TIME-ENTRIES"
    monkeypatch.setattr(engagement_repo, "get_or_raise", lambda _id: _engagement(eng_id))

    invoice_id = invoice_gen.generate_invoice_from_time_entries(eng_id)
    invoice = invoice_repo.find_by_id(invoice_id)

    assert invoice["invoice_date"] == "2026-04-01"


def test_recurring_invoice_first_run_defaults_to_ist_date(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    eng_id = "ENG-RECURRING-FIRST"
    monkeypatch.setattr(engagement_repo, "get_or_raise", lambda _id: _engagement(eng_id))

    invoice_id = invoice_gen.generate_recurring_invoice(eng_id)
    invoice = invoice_repo.find_by_id(invoice_id)

    assert invoice["invoice_date"] == "2026-04-01"


# ── 2. Invoice numbering's own date-fallback also resolves via IST ──────────

def test_invoice_number_fallback_uses_ist_fiscal_year(monkeypatch):
    # generate_next_invoice_number's OWN current_date fallback (independent of
    # the invoice_month default above — triggered when no date is passed at
    # all) must also read the IST calendar date, not the UTC one.
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    invoice_no = invoice_repo.generate_next_invoice_number(firm_id="FIRM-NUMBERING-TEST")
    assert invoice_no.split("-")[1] == "2026"   # FY 2026-27 (starts 1 Apr 2026), not 2025


# ── 3. Online-payment webhook receipt date resolves via IST ─────────────────

def test_payment_webhook_receipt_date_uses_ist_across_fy_boundary(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    monkeypatch.setattr("services.receipt_service.log_event", lambda *a, **k: None)
    monkeypatch.setattr("services.receipt_service._next_receipt_seq", lambda *a, **k: 1)
    monkeypatch.setattr("services.payment_service.log_event", lambda *a, **k: None)
    import services.timeline_service as ts
    monkeypatch.setattr(ts.timeline_service, "log_timeline_event", lambda *a, **k: None)
    import services.period_validation_service as pv
    monkeypatch.setattr(pv.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setenv("MOCK_WEBHOOK_SECRET", "test_mock_secret")

    db = FakeDB()
    seed_standard_coa(db, FIRM, CLIENT)   # receipt settlement posts a real journal via the atomic RPC path
    db.seed("client_sales_invoices", {"id": "INV-IST", "firm_id": FIRM, "client_id": CLIENT,
                                      "customer_id": "CUST-IST", "invoice_no": "SINV-IST",
                                      "total_paise": 100000, "paid_paise": 0, "status": "issued",
                                      "deleted_at": None})
    db.seed("customers", {"id": "CUST-IST", "firm_id": FIRM, "client_id": CLIENT, "name": "Acme",
                          "email": "a@acme.test", "phone": "9", "is_active": True})

    link = payment_service.create_link(db, FIRM, "INV-IST", actor={"auth_user_id": "u1", "email": "ca@f.test"})

    from services.payments.mock import MockProvider
    entity = {"id": "pay-ist-1", "order_id": link.get("provider_order_id"),
              "payment_link_id": link.get("provider_link_id"), "amount": link["amount_paise"]}
    payload = {"id": "evt-ist-1", "event": "payment.captured", "payload": {"payment": {"entity": entity}}}
    headers, body = MockProvider().sign_webhook(payload)

    out = payment_service.process_webhook(db, "mock", headers, body)
    assert out["ok"] and out["status"] == "captured"

    receipt = db.rows("receipts")[0]
    assert receipt["receipt_date"] == "2026-04-01"


# ── 4. Financial-year reporting default resolves via IST ────────────────────

def test_fy_start_defaults_to_ist_fiscal_year(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    assert reporting_service._fy_start() == "2026-04-01"   # FY 2026-27, not FY 2025-26


def test_fy_start_explicit_today_param_still_wins(monkeypatch):
    # Preserve explicit FY parameters: an explicit `today` bypasses ist_today()
    # entirely, regardless of the frozen clock.
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    assert reporting_service._fy_start(date(2025, 6, 15)) == "2025-04-01"
