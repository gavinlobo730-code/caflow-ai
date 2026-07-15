"""
Phase 4.3 — Recurring Invoices (application-layer tests, mock mode, no DB).

Covers the pure cadence engine (weekly/monthly/quarterly/half-yearly/yearly +
month-end clamping), DRAFT-only generation through the EXISTING invoice engine
(GST reused, never issued, no journal posted), idempotency / catch-up, due-date
(Decision 4), template CRUD + pause/resume/archive, history, preview, and
firm/client isolation. DB-level guarantees (unique index, RLS) live in the
migration; the service mirrors billing_service's proven DB path.
"""
from datetime import date

import pytest

import services.recurring_invoice_service as rec
from routers.sales_invoices import MOCK_SALES_INVOICES, issue_invoice

ACTOR = {"firm_id": "F1", "role": "Partner", "auth_user_id": "u1", "email": "ca@f"}
OTHER = {"firm_id": "F2", "role": "Partner", "auth_user_id": "u2", "email": "ca@f2"}


@pytest.fixture(autouse=True)
def _clear():
    rec.MOCK_RECURRING_TEMPLATES.clear()
    rec.MOCK_RECURRING_RUNS.clear()
    MOCK_SALES_INVOICES.clear()
    yield
    rec.MOCK_RECURRING_TEMPLATES.clear()
    rec.MOCK_RECURRING_RUNS.clear()
    MOCK_SALES_INVOICES.clear()


def _make(firm="F1", client="CL-1", customer="CUST-1", freq="monthly",
          start="2026-06-01", end=None, rate=100000, gst=18.0, title="Monthly bookkeeping"):
    return rec.create_template(firm, {
        "client_id": client, "customer_id": customer, "title": title,
        "frequency": freq, "start_date": start, "end_date": end,
        "lines": [{"service_catalogue_id": "SVC-1", "description": "Bookkeeping fee", "hsn_sac": "998222",
                   "rate_paise": rate, "gst_rate_percent": gst, "is_service": True}],
    }, created_by="u1")


# ── Pure cadence engine ──────────────────────────────────────────────────────

def test_next_occurrence_weekly():
    f = rec.next_occurrence
    assert f("weekly", "2026-06-01", None) == date(2026, 6, 1)        # first run
    assert f("weekly", "2026-06-01", "2026-06-01") == date(2026, 6, 8)  # strictly after
    assert f("weekly", "2026-06-01", "2026-06-05") == date(2026, 6, 8)
    assert f("weekly", "2026-05-01", "2026-04-01") == date(2026, 5, 1)  # before start -> start


def test_next_occurrence_monthly_quarterly_half_yearly_yearly():
    f = rec.next_occurrence
    assert f("monthly", "2026-06-15", "2026-06-15") == date(2026, 7, 15)
    assert f("quarterly", "2026-01-10", "2026-01-10") == date(2026, 4, 10)
    assert f("half_yearly", "2026-01-31", "2026-01-31") == date(2026, 7, 31)
    assert f("yearly", "2026-02-28", "2026-02-28") == date(2027, 2, 28)


def test_occurrence_series_same_anchor_day():
    # quarterly anchored on the 10th
    occ = [rec.occurrence("quarterly", "2026-01-10", n).isoformat() for n in range(4)]
    assert occ == ["2026-01-10", "2026-04-10", "2026-07-10", "2026-10-10"]


def test_month_end_clamping_anchored_to_start():
    # Jan-31 monthly clamps to each month's last day, but stays anchored to start
    occ = [rec.occurrence("monthly", "2026-01-31", n).isoformat() for n in range(5)]
    assert occ == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31"]
    # leap February
    assert rec.occurrence("yearly", "2024-02-29", 1).isoformat() == "2025-02-28"


def test_preview_occurrences_respects_end_date():
    t = _make(freq="monthly", start="2026-06-01", end="2026-08-31")
    assert rec.preview_occurrences(t, count=6) == ["2026-06-01", "2026-07-01", "2026-08-01"]


# ── Due date (Decision 4) ────────────────────────────────────────────────────

def test_due_date_uses_customer_credit_days_then_firm_default():
    assert rec.due_date_for("2026-06-01", {"credit_days": 15}) == "2026-06-16"
    assert rec.due_date_for("2026-06-01", {}) == "2026-07-01"          # firm default 30
    assert rec.due_date_for("2026-06-01", {"credit_days": None}) == "2026-07-01"


# ── DRAFT generation through the existing engine ─────────────────────────────

def test_generation_creates_draft_with_reused_gst():
    t = _make(rate=100000, gst=18.0, start="2026-06-01")
    res = rec.generate_due_recurring_invoices("F1", as_of=date(2026, 6, 1), actor=ACTOR)
    assert res["generated_count"] == 1
    inv = MOCK_SALES_INVOICES[0]
    # GST reused from the sales engine: 18% intra -> CGST 9% + SGST 9%
    assert inv["taxable_amount_paise"] == 100000
    assert inv["cgst_paise"] == 9000 and inv["sgst_paise"] == 9000 and inv["igst_paise"] == 0
    assert inv["total_paise"] == 118000
    # DRAFT only — never issued, no journal
    assert inv["status"] == "draft"
    assert not inv.get("journal_entry_id")
    assert inv["paid_paise"] == 0
    # traceability
    assert inv["source"] == "recurring"
    assert inv["recurring_template_id"] == t["id"]
    assert inv["recurring_occurrence"] == "2026-06-01"
    assert inv["invoice_date"] == "2026-06-01"
    assert inv["due_date"] == "2026-07-01"        # occurrence + firm default 30


def test_generation_posts_no_journal_even_if_poster_would_fire(monkeypatch):
    # Hard proof: if generation ever tried to post a journal, this would raise.
    import services.phase2_journal_service as pjs

    def _boom(*a, **k):
        raise AssertionError("recurring generation must NEVER post a journal")

    monkeypatch.setattr(pjs.phase2_journal_service, "journal_for_sales_invoice", _boom)
    _make(start="2026-06-01")
    res = rec.generate_due_recurring_invoices("F1", as_of=date(2026, 6, 1), actor=ACTOR)
    assert res["generated_count"] == 1
    assert MOCK_SALES_INVOICES[0]["status"] == "draft"


def test_generation_is_idempotent_per_occurrence():
    _make(freq="monthly", start="2026-06-01")
    first = rec.generate_due_recurring_invoices("F1", as_of=date(2026, 6, 15), actor=ACTOR)
    second = rec.generate_due_recurring_invoices("F1", as_of=date(2026, 6, 15), actor=ACTOR)
    assert first["generated_count"] == 1
    assert second["generated_count"] == 0          # nothing new is due
    # exactly one invoice for the June occurrence
    june = [i for i in MOCK_SALES_INVOICES if i.get("recurring_occurrence") == "2026-06-01"]
    assert len(june) == 1


def test_catch_up_generates_each_due_occurrence_once():
    _make(freq="weekly", start="2026-06-01")
    res = rec.generate_due_recurring_invoices("F1", as_of=date(2026, 6, 22), actor=ACTOR)
    occ = sorted(i["recurring_occurrence"] for i in MOCK_SALES_INVOICES)
    assert occ == ["2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22"]
    assert res["generated_count"] == 4
    # re-running is safe — no duplicates
    again = rec.generate_due_recurring_invoices("F1", as_of=date(2026, 6, 22), actor=ACTOR)
    assert again["generated_count"] == 0
    assert len(MOCK_SALES_INVOICES) == 4


def test_end_date_stops_generation():
    _make(freq="monthly", start="2026-06-01", end="2026-07-31")
    rec.generate_due_recurring_invoices("F1", as_of=date(2026, 12, 31), actor=ACTOR)
    occ = sorted(i["recurring_occurrence"] for i in MOCK_SALES_INVOICES)
    assert occ == ["2026-06-01", "2026-07-01"]      # August onward is past end_date


def test_paused_and_archived_templates_do_not_generate():
    t = _make(start="2026-06-01")
    rec.set_status("F1", t["id"], "paused")
    assert rec.generate_due_recurring_invoices("F1", as_of=date(2026, 6, 1), actor=ACTOR)["generated_count"] == 0
    rec.set_status("F1", t["id"], "archived")
    assert rec.generate_due_recurring_invoices("F1", as_of=date(2026, 6, 1), actor=ACTOR)["generated_count"] == 0
    rec.set_status("F1", t["id"], "active")
    assert rec.generate_due_recurring_invoices("F1", as_of=date(2026, 6, 1), actor=ACTOR)["generated_count"] == 1


def test_next_run_date_advances_after_generation():
    t = _make(freq="monthly", start="2026-06-01")
    rec.generate_due_recurring_invoices("F1", as_of=date(2026, 6, 1), actor=ACTOR)
    advanced = rec.get_template("F1", t["id"])
    assert advanced["next_run_date"] == "2026-07-01"


# ── Manual single-template run ───────────────────────────────────────────────

def test_run_for_template_manual():
    t = _make(freq="monthly", start="2026-06-01")
    res = rec.run_for_template("F1", t["id"], as_of=date(2026, 6, 1), actor=ACTOR)
    assert res["generated_count"] == 1
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        rec.run_for_template("F1", "missing", as_of=date(2026, 6, 1), actor=ACTOR)
    assert ei.value.status_code == 404


# ── Generated draft flows into the normal lifecycle when the CA issues it ────

def test_generated_draft_can_be_issued_by_ca():
    _make(start="2026-06-01")
    rec.generate_due_recurring_invoices("F1", as_of=date(2026, 6, 1), actor=ACTOR)
    inv = MOCK_SALES_INVOICES[0]
    assert inv["status"] == "draft"
    issued = issue_invoice(inv["id"], ACTOR)            # existing CA-confirm path
    assert issued["data"]["status"] == "issued"


# ── History + preview via templates ──────────────────────────────────────────

def test_history_records_occurrences_with_invoice():
    t = _make(freq="monthly", start="2026-06-01")
    rec.generate_due_recurring_invoices("F1", as_of=date(2026, 7, 1), actor=ACTOR)
    hist = rec.template_history("F1", t["id"])
    assert len(hist) == 2
    assert {h["occurrence_date"] for h in hist} == {"2026-06-01", "2026-07-01"}
    assert all(h["status"] == "generated" and h["invoice"]["invoice_no"] for h in hist)


# ── CRUD + validation ────────────────────────────────────────────────────────

def test_create_requires_lines_and_valid_frequency():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        rec.create_template("F1", {"client_id": "CL-1", "customer_id": "CUST-1",
                                   "title": "x", "frequency": "monthly",
                                   "start_date": "2026-06-01", "lines": []}, "u1")
    with pytest.raises(HTTPException):
        rec.create_template("F1", {"client_id": "CL-1", "customer_id": "CUST-1",
                                   "title": "x", "frequency": "fortnightly",
                                   "start_date": "2026-06-01",
                                   "lines": [{"description": "f", "rate_paise": 1}]}, "u1")


def test_update_rebases_next_run_on_schedule_change():
    t = _make(freq="monthly", start="2026-06-01")
    updated = rec.update_template("F1", t["id"], {"start_date": "2026-09-15"})
    assert updated["start_date"] == "2026-09-15"
    assert updated["next_run_date"] == "2026-09-15"


def test_update_replaces_lines():
    t = _make(rate=100000)
    rec.update_template("F1", t["id"], {"lines": [
        {"service_catalogue_id": "SVC-1", "description": "GST filing", "rate_paise": 500000, "gst_rate_percent": 18.0, "is_service": True}]})
    rec.generate_due_recurring_invoices("F1", as_of=date(2026, 6, 1), actor=ACTOR)
    assert MOCK_SALES_INVOICES[0]["taxable_amount_paise"] == 500000


# ── Isolation ────────────────────────────────────────────────────────────────

def test_firm_isolation():
    _make(firm="F1", start="2026-06-01")
    # F2 running its own generation sees none of F1's templates
    assert rec.generate_due_recurring_invoices("F2", as_of=date(2026, 6, 1), actor=OTHER)["generated_count"] == 0
    assert MOCK_SALES_INVOICES == []


def test_client_isolation_filter():
    _make(firm="F1", client="CL-1", start="2026-06-01")
    _make(firm="F1", client="CL-2", start="2026-06-01", customer="CUST-2")
    res = rec.generate_due_recurring_invoices("F1", client_id="CL-1", as_of=date(2026, 6, 1), actor=ACTOR)
    assert res["generated_count"] == 1
    assert {i["client_id"] for i in MOCK_SALES_INVOICES} == {"CL-1"}
