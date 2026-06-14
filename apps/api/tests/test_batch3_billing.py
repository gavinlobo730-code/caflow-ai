"""
Batch 3 (Amendment v1.1) — Revenue Operations billing, application-layer tests
(mock mode, no DB). Cover recurring generation, duplicate-run protection, GST
correctness (engine reuse), customer-link single (G3), CA-confirm gate, and
partner-only access. DB-level guarantees (unique index, restrictive RLS,
collections lifecycle at the data layer) are in test_batch3_billing_migration.py.
"""
import pytest

from core.permissions import can
import services.billing_service as billing
from routers.sales_invoices import MOCK_SALES_INVOICES, issue_invoice

PARTNER = {"firm_id": "F1", "role": "Partner", "auth_user_id": "p", "email": "p@f"}


@pytest.fixture(autouse=True)
def _clear_mock_stores():
    billing.MOCK_BILLING_SCHEDULES.clear()
    billing.MOCK_CLIENT_LINKS.clear()
    MOCK_SALES_INVOICES.clear()
    yield
    billing.MOCK_BILLING_SCHEDULES.clear()
    billing.MOCK_CLIENT_LINKS.clear()
    MOCK_SALES_INVOICES.clear()


def _make_schedule(amount_paise=100000, cadence="monthly", gst_rate=18.0, next_run_date="2026-06-01"):
    return billing.create_schedule("F1", {
        "client_id": "PRACTICE_CLIENT_1", "arrangement": "retainer",
        "cadence": cadence, "amount_paise": amount_paise, "gst_rate": gst_rate,
        "next_run_date": next_run_date,
    }, created_by="p")


def test_recurring_generation_and_gst_correctness():
    sched = _make_schedule(amount_paise=100000, gst_rate=18.0)
    result = billing.generate_for_schedule("F1", sched, PARTNER)
    assert result["created"] is True and result["idempotent"] is False
    inv = result["invoice"]
    # GST reused from the Sales engine: 18% intra-state -> CGST 9% + SGST 9%.
    assert inv["taxable_amount_paise"] == 100000
    assert inv["cgst_paise"] == 9000
    assert inv["sgst_paise"] == 9000
    assert inv["igst_paise"] == 0
    assert inv["total_paise"] == 118000
    # CA-confirm gate: generated as a DRAFT.
    assert inv["status"] == "draft"
    assert inv["paid_paise"] == 0


def test_traceability_fields():
    sched = _make_schedule()
    inv = billing.generate_for_schedule("F1", sched, PARTNER)["invoice"]
    # invoice -> billing_schedule -> originating practice client; invoice -> linked customer
    assert inv["billing_schedule_id"] == sched["id"]
    assert inv["billing_period"] == "2026-06"
    assert inv["source"] == "billing"
    assert sched["client_id"] == "PRACTICE_CLIENT_1"          # originating practice client
    assert inv["customer_id"]                                  # linked customer in internal books


def test_duplicate_run_protection_idempotent():
    sched = _make_schedule()
    first = billing.generate_for_schedule("F1", sched, PARTNER, period="2026-06")
    # advancing next_run_date would change the derived period, so pin the period:
    second = billing.generate_for_schedule("F1", sched, PARTNER, period="2026-06")
    assert first["created"] is True
    assert second["created"] is False and second["idempotent"] is True
    assert second["invoice"]["id"] == first["invoice"]["id"]
    # exactly one invoice exists for that schedule+period
    matches = [i for i in MOCK_SALES_INVOICES
               if i.get("billing_schedule_id") == sched["id"] and i.get("billing_period") == "2026-06"]
    assert len(matches) == 1


def test_customer_link_single_per_practice_client():
    sched = _make_schedule(cadence="monthly")
    billing.generate_for_schedule("F1", sched, PARTNER, period="2026-06")
    billing.generate_for_schedule("F1", sched, PARTNER, period="2026-07")
    links = [lk for lk in billing.MOCK_CLIENT_LINKS if lk["client_id"] == "PRACTICE_CLIENT_1"]
    assert len(links) == 1, "exactly one customer link per practice client (G3)"


def test_ca_confirm_gate_draft_until_issued():
    sched = _make_schedule()
    inv = billing.generate_for_schedule("F1", sched, PARTNER)["invoice"]
    assert inv["status"] == "draft"
    # CA-confirm = the existing issue transition (reused, partner-gated for internal client)
    issued = issue_invoice(inv["id"], PARTNER)
    assert issued["data"]["status"] == "issued"


def test_preview_run_lists_due_then_idempotent():
    sched = _make_schedule(next_run_date="2026-06-01")
    due = billing.preview_due("F1", as_of="2026-06-15")
    assert len(due) == 1
    assert due[0]["schedule_id"] == sched["id"]
    assert due[0]["period"] == "2026-06"
    assert due[0]["already_generated"] is False


def test_partner_only_access():
    assert can("Partner", "billing", "write") is True
    assert can("Partner", "billing", "read") is True
    assert can("Manager", "billing", "write") is False
    assert can("Manager", "billing", "read") is False
    assert can("Executive", "billing", "read") is False
    assert can("Reviewer", "billing", "read") is False


def test_period_and_cadence_helpers():
    assert billing.period_for("monthly", "2026-06-10") == "2026-06"
    assert billing.period_for("quarterly", "2026-06-10") == "2026-Q2"
    assert billing.period_for("annual", "2026-06-10") == "2026-27"   # Indian FY
    assert billing.period_for("annual", "2026-02-10") == "2025-26"
    assert billing.next_run_after("monthly", "2026-06-01") == "2026-07-01"
    assert billing.next_run_after("one_time", "2026-06-01") is None
