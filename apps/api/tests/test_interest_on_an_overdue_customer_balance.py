"""Interest a client charges its own customer on an overdue balance (accounting-22).

THE VERIFY LINE, AS A TEST: for a customer with an invoice 40 days overdue at a
stated rate, the preview shows the interest to the paisa under the declared
day-count convention, and creating the draft invoice changes no ledger until it
is issued.

WHAT ELSE IS HELD HERE

  * The convention is a CONSTANT stated on every answer (simple, actual/365, the
    start date not a late day, half a paisa rounds up) — pinned with values that
    separate it from its neighbours: a leap year, a half paisa, a grace period.
  * The base is the document's `outstanding_paise` COLUMN. The test seeds an
    invoice whose `total - paid` differs from the column (a debit note, a credit
    note and a part-payment) so a reader that re-subtracts gets a different
    figure and fails.
  * Three "no figure" states stay apart: no rate on record, a recorded 0 (waived)
    and a rate with nothing late.
  * Interest accrues continuously and is billed in pieces: a second preview
    starts where a standing draft stopped, a deleted or cancelled draft releases
    its period, and an interest invoice is never the base of the next one.
  * A draft is an ORDINARY DRAFT through the sales engine: no journal, the GST
    rate of the invoice it relates to (CGST s.15(2)(d) [S]), and a refusal NAMED
    for each kind of document it cannot reproduce the treatment of.
  * Nothing here posts, issues or emails.
"""
from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

from domain.sales import late_interest as L

API = Path(__file__).resolve().parents[1]

AS_OF = date(2026, 10, 1)


# ═════════════════════════════════════════════════════════════════════════════
# THE RULE (pure)
# ═════════════════════════════════════════════════════════════════════════════

def _one(outstanding, due, terms, as_of=AS_OF, charged_through=None, invoice_date="2026-01-01"):
    return L.document_interest(
        outstanding_paise=outstanding, invoice_date=invoice_date, due_date=due,
        terms=terms, as_of=as_of, charged_through=charged_through)


def test_the_verify_line_forty_days_late_at_a_stated_rate_to_the_paisa():
    # Rs 1,00,000 due 22 August, looked at on 1 October: 40 days. At 18% a year
    # that is 1,00,000 x 0.18 x 40 / 365 = Rs 1,972.60 — to the paisa.
    got = _one(10_000_000, "2026-08-22", L.Terms(rate_bps=1800))
    assert got.status == L.CHARGE
    assert got.days_late == 40 and got.days_charged == 40
    assert got.interest_paise == 197_260
    assert got.counted_from == "2026-08-22"
    assert (got.period_from, got.period_to) == ("2026-08-22", "2026-10-01")


def test_the_due_date_is_not_a_late_day_and_the_as_at_date_is():
    t = L.Terms(rate_bps=1800)
    assert _one(10_000_000, "2026-10-01", t).status == L.NOT_OVERDUE      # due today
    one_day = _one(10_000_000, "2026-09-30", t)                           # due yesterday
    assert one_day.days_late == 1 and one_day.status == L.CHARGE


def test_grace_days_move_where_interest_starts():
    t = L.Terms(rate_bps=1800, grace_days=7)
    got = _one(10_000_000, "2026-08-22", t)
    assert got.days_late == 33 and got.period_from == "2026-08-29"
    # Inside the grace period it is not overdue at all.
    assert _one(10_000_000, "2026-09-28", t).status == L.NOT_OVERDUE


def test_a_year_is_365_days_even_when_a_leap_day_falls_inside_it():
    """actual/365, stated: 28 Feb 2028 to 1 Mar 2028 crosses 29 February and is
    TWO actual days, over a divisor that does not change in a leap year."""
    got = _one(36_500_000, "2028-02-28", L.Terms(rate_bps=1000),
               as_of=date(2028, 3, 1))
    assert got.days_charged == 2
    assert got.interest_paise == L.interest_paise(36_500_000, 1000, 2) == 20_000


def test_a_half_paisa_rounds_up_and_less_does_not():
    # 1,825 paise at 0.01% for 1,000 days is exactly half a paisa.
    assert L.interest_paise(1825, 1, 1000) == 1
    assert L.interest_paise(1825, 1, 999) == 0
    assert L.round_half_up(1, 2) == 1 and L.round_half_up(1, 3) == 0
    assert L.round_half_up(5, 2) == 3 and L.round_half_up(4, 2) == 2


def test_the_figure_is_rounded_once_on_the_whole_product_not_per_day():
    """Rounding each day's interest would drift from the stated convention."""
    out, rate, days = 12_345_678, 2150, 77
    whole = L.interest_paise(out, rate, days)
    per_day = sum(L.interest_paise(out, rate, 1) for _ in range(days))
    assert whole == (2 * out * rate * days + 3_650_000) // 7_300_000
    assert whole != per_day, "the premise: the two methods genuinely differ here"


def test_a_recorded_zero_is_waived_and_is_not_the_same_as_no_rate():
    assert _one(10_000_000, "2026-08-22", L.Terms(rate_bps=0)).status == L.WAIVED
    assert _one(10_000_000, "2026-08-22", L.Terms(rate_bps=None)).status == L.NO_TERMS


def test_a_part_covered_period_starts_the_day_after_what_a_draft_covers():
    t = L.Terms(rate_bps=1800)
    first = _one(10_000_000, "2026-08-22", t, as_of=date(2026, 9, 21))      # 30 days
    second = _one(10_000_000, "2026-08-22", t, as_of=date(2026, 10, 1),
                  charged_through=date(2026, 9, 21))                       # the next 10
    assert (first.days_charged, second.days_charged) == (30, 10)
    assert second.period_from == "2026-09-21"
    # The two pieces are the whole: nothing charged twice, nothing missed.
    whole = _one(10_000_000, "2026-08-22", t)
    assert first.interest_paise + second.interest_paise in (
        whole.interest_paise - 1, whole.interest_paise, whole.interest_paise + 1)
    assert whole.days_charged == 40


def test_a_period_already_covered_through_the_as_at_date_charges_nothing():
    got = _one(10_000_000, "2026-08-22", L.Terms(rate_bps=1800),
               charged_through=AS_OF)
    assert got.status == L.COVERED and got.interest_paise == 0


def test_no_due_date_counts_from_the_invoice_date_and_says_so():
    got = _one(10_000_000, None, L.Terms(rate_bps=1800), invoice_date="2026-08-22")
    assert got.counted_from == "2026-08-22"
    assert "invoice date" in got.start_note


def test_the_basis_can_be_the_invoice_date():
    t = L.Terms(rate_bps=1800, basis=L.FROM_INVOICE_DATE)
    got = _one(10_000_000, "2026-09-30", t, invoice_date="2026-08-22")
    assert got.counted_from == "2026-08-22" and got.days_late == 40


@pytest.mark.parametrize("rate,grace,basis,fragment", [
    (10_001, 0, "due_date", "between 0% and 100%"),
    (-1, 0, "due_date", "between 0% and 100%"),
    (18.5, 0, "due_date", "whole number"),
    (1800, -1, "due_date", "Grace days"),
    (1800, 366, "due_date", "Grace days"),
    (1800, 0, "payment_date", "due_date or the invoice_date"),
])
def test_terms_the_column_would_refuse_are_refused_in_words(rate, grace, basis, fragment):
    assert fragment in (L.terms_problem(rate, grace, basis) or "")


def test_clearing_the_rate_is_valid_and_so_are_the_edges():
    assert L.terms_problem(None, 0, "due_date") is None
    assert L.terms_problem(0, 0, "invoice_date") is None
    assert L.terms_problem(10_000, 365, "due_date") is None


# ── the preview over a customer book ─────────────────────────────────────────

def _doc(i, out=10_000_000, due="2026-08-22", **kw):
    return L.DocInput(invoice_id=f"i{i}", invoice_no=f"INV/{i}", invoice_date="2026-07-01",
                      due_date=due, outstanding_paise=out, **kw)


def _preview(*parties):
    return L.build_preview(parties, AS_OF)


def test_the_convention_is_stated_on_every_answer_and_the_balance_caveat_with_it():
    out = _preview(L.PartyInput("c1", "Beta", L.Terms(1800), (_doc(1),)))
    c = out["convention"]
    assert c["day_count"] == "actual/365" and c["interest"] == "simple"
    assert c["compounding"] == "not offered"
    assert "half a paisa" in c["statement"] and AS_OF.isoformat() in c["statement"]
    assert any("AS IT STANDS TODAY" in cv for cv in out["caveats"])
    assert any("Nothing here is posted" in cv for cv in out["caveats"])
    # The statutory reading is carried, graded, and says it is not the Act's text.
    assert out["statutory_reading"]["section"] == "CGST Act s.15(2)(d)"
    assert out["statutory_reading"]["grade"] == "[S]"


def test_a_party_with_overdue_invoices_and_no_rate_is_named_with_no_figure():
    out = _preview(
        L.PartyInput("c1", "Beta", L.Terms(1800), (_doc(1),)),
        L.PartyInput("c2", "Gamma", L.Terms(None), (_doc(2, out=500_000),)))
    gamma = next(p for p in out["parties"] if p["customer_id"] == "c2")
    assert gamma["terms_set"] is False
    assert gamma["interest_paise"] == 0 and gamma["overdue_outstanding_paise"] == 500_000
    assert gamma["documents"][0]["status"] == L.NO_TERMS
    assert out["totals"]["parties_without_terms"] == 1
    assert any("Gamma" in g and "no interest rate on record" in g for g in out["gaps"])
    # And the total is the one party's figure, not a figure for both.
    assert out["totals"]["interest_paise"] == out["parties"][0]["interest_paise"] == 197_260


def test_a_party_with_nothing_late_is_not_listed_at_all():
    assert _preview(L.PartyInput("c1", "Beta", L.Terms(1800),
                                 (_doc(1, due="2026-10-15"),)))["parties"] == []


def test_an_interest_invoice_is_never_the_base_of_interest():
    out = _preview(L.PartyInput("c1", "Beta", L.Terms(1800), (
        _doc(1), _doc(2, out=99_000_000, is_interest_invoice=True))))
    docs = {d["invoice_id"]: d for d in out["parties"][0]["documents"]}
    assert docs["i2"]["status"] == L.INTEREST_INVOICE and docs["i2"]["interest_paise"] == 0
    assert out["totals"]["interest_paise"] == 197_260


def test_the_longest_overdue_is_listed_first():
    out = _preview(L.PartyInput("c1", "Beta", L.Terms(1800), (
        _doc(1, due="2026-09-20"), _doc(2, due="2026-07-01"), _doc(3, due="2026-08-15"))))
    assert [d["invoice_id"] for d in out["parties"][0]["documents"]] == ["i2", "i3", "i1"]


# ── what a draft may be, and what it may not ─────────────────────────────────

def _chargeable(i, **kw):
    base = dict(invoice_id=f"i{i}", invoice_no=f"INV/{i}", customer_id="c1",
                interest_paise=197_260, period_from="2026-08-22", period_to="2026-10-01",
                days=40, outstanding_paise=10_000_000, interest_rate_bps=1800,
                gst_rate_bps=1800, rate_state="single")
    base.update(kw)
    return L.ChargeableDoc(**base)


def test_documents_with_one_tax_treatment_share_a_draft_and_others_do_not():
    groups, blocked = L.plan_drafts([
        _chargeable(1), _chargeable(2),
        _chargeable(3, gst_rate_bps=500),
        _chargeable(4, is_interstate=True)])
    assert not blocked
    assert [(g.gst_rate_bps, g.is_interstate, len(g.documents)) for g in groups] == [
        (500, False, 1), (1800, False, 2), (1800, True, 1)]


def test_each_document_a_draft_cannot_follow_is_named_with_its_own_reason():
    groups, blocked = L.plan_drafts([
        _chargeable(1),
        _chargeable(2, supply_type="exempt"),
        _chargeable(3, invoice_type="SEZ_with_payment"),
        _chargeable(4, is_reverse_charge=True),
        _chargeable(5, rate_state="mixed", gst_rate_bps=None),
        _chargeable(6, rate_state="none", gst_rate_bps=None)])
    assert [d.invoice_no for g in groups for d in g.documents] == ["INV/1"]
    by_no = {b["invoice_no"]: b["reason_code"] for b in blocked}
    assert by_no == {"INV/2": L.BLOCK_NOT_REGULAR, "INV/3": L.BLOCK_NOT_REGULAR,
                     "INV/4": L.BLOCK_NOT_REGULAR, "INV/5": L.BLOCK_MIXED_RATE,
                     "INV/6": L.BLOCK_NO_RATE}
    # Three DIFFERENT sentences: what a CA does next differs for each.
    reasons = {b["reason_code"]: b["reason"] for b in blocked}
    assert len(set(reasons.values())) == 3
    assert "s.15(2)(d) [S]" in reasons[L.BLOCK_NOT_REGULAR]


def test_a_draft_line_names_the_invoice_the_days_and_the_rate_and_has_no_rupee_sign():
    text = L.line_description(_chargeable(1, interest_rate_bps=1850))
    assert "INV/1" in text and "40 days" in text and "18.5% a year" in text
    assert "Rs.1,00,000.00" in text
    assert "₹" not in text, "this reaches a PDF, whose core fonts have no rupee glyph"
    assert "18% a year" in L.line_description(_chargeable(1))


# ═════════════════════════════════════════════════════════════════════════════
# THE SERVICE, against the e2e double and the REAL sales engine
# ═════════════════════════════════════════════════════════════════════════════

import routers.sales_invoices as si                      # noqa: E402
from services import late_interest_service as svc        # noqa: E402
from tests.e2e_harness import FakeDB, wire_e2e            # noqa: E402

FIRM, CLIENT, CUST = "FIRM-A", "CLI-1", "CUST-1"
CALLER = {"firm_id": FIRM, "id": "u-int-1", "auth_user_id": "auth-1",
          "email": "ca@f.test", "role": "Partner"}


def _book(monkeypatch, *, rate=1800, grace=0, basis="due_date"):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2",
                        "financial_year_start": "2026-04-01"})
    db.seed("customers", {"id": CUST, "firm_id": FIRM, "client_id": CLIENT, "name": "Beta Ltd",
                          "is_active": True, "credit_days": 30, "opening_balance_paise": 0,
                          "late_interest_rate_bps": rate, "late_interest_grace_days": grace,
                          "late_interest_from": basis})
    return db


def _overdue(db, n=1, *, due="2026-08-22", gst_bps=1800, status="issued", **head):
    """An issued invoice whose `total - paid` DIFFERS from its outstanding column:
    total 1,00,000 + debit note 20,000 - paid 30,000 - credited 10,000 = 80,000
    (a reader that re-subtracts gets 70,000)."""
    row = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": CUST,
        "invoice_no": f"INV/2026-27/{n:04d}", "invoice_date": "2026-07-01", "due_date": due,
        "status": status, "total_paise": 10_000_000, "debit_note_paise": 2_000_000,
        "paid_paise": 3_000_000, "credited_paise": 1_000_000,
        "supply_state_code": "27", "is_interstate": False, "supply_type": "taxable",
        "invoice_type": "Regular", "is_reverse_charge": False, **head})
    db.seed("client_sales_invoice_lines", {
        "sales_invoice_id": row["id"], "description": "Goods", "hsn_sac": "998311",
        "gst_rate_bps": gst_bps, "quantity": 1, "rate_paise": 1, "taxable_amount_paise": 1})
    return row


def test_the_preview_reads_the_outstanding_column_not_total_minus_paid(monkeypatch):
    db = _book(monkeypatch)
    _overdue(db)
    out = svc.preview(db, FIRM, CLIENT, AS_OF)
    doc = out["parties"][0]["documents"][0]
    assert doc["outstanding_paise"] == 8_000_000, (
        "the base must be migration 278's generated column "
        "(total + debit notes - paid - credited), not total - paid")
    # 80,000.00 x 18% x 40 / 365 = 1,578.08
    assert doc["interest_paise"] == L.interest_paise(8_000_000, 1800, 40) == 157_808
    assert out["totals"]["interest_paise"] == 157_808


def test_the_preview_filters_settled_cancelled_draft_and_deleted_invoices_out(monkeypatch):
    db = _book(monkeypatch)
    _overdue(db, 1)
    _overdue(db, 2, status="cancelled")
    _overdue(db, 3, status="draft")
    _overdue(db, 4, deleted_at="2026-09-01T00:00:00")
    _overdue(db, 5, paid_paise=10_000_000, credited_paise=0, debit_note_paise=0)   # settled
    docs = svc.preview(db, FIRM, CLIENT, AS_OF)["parties"][0]["documents"]
    assert [d["invoice_no"] for d in docs] == ["INV/2026-27/0001"]


def test_another_clients_customer_is_never_read(monkeypatch):
    db = _book(monkeypatch)
    _overdue(db, 1)
    db.seed("customers", {"id": "CUST-X", "firm_id": FIRM, "client_id": "CLI-OTHER",
                          "name": "Elsewhere", "late_interest_rate_bps": 1800,
                          "late_interest_grace_days": 0, "late_interest_from": "due_date"})
    db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI-OTHER", "customer_id": "CUST-X",
        "invoice_no": "X/1", "invoice_date": "2026-07-01", "due_date": "2026-08-01",
        "status": "issued", "total_paise": 5_000_000, "paid_paise": 0,
        "credited_paise": 0, "debit_note_paise": 0})
    out = svc.preview(db, FIRM, CLIENT, AS_OF)
    assert [p["customer_name"] for p in out["parties"]] == ["Beta Ltd"]


def test_a_draft_is_an_ordinary_draft_and_changes_no_ledger(monkeypatch):
    """THE VERIFY LINE'S SECOND HALF, through the real sales engine."""
    db = _book(monkeypatch)
    _overdue(db, 1)
    before = (len(db.rows("journal_entries")), len(db.rows("journal_lines")))

    out = svc.prepare_drafts(db, FIRM, CLIENT, CUST, AS_OF, CALLER)

    assert (len(db.rows("journal_entries")), len(db.rows("journal_lines"))) == before == (0, 0)
    assert len(out["drafts"]) == 1 and out["not_drafted"] == [] and out["failed"] == []
    draft = next(r for r in db.rows("client_sales_invoices")
                 if r["id"] == out["drafts"][0]["invoice_id"])
    assert draft["status"] == "draft", "never issued"
    assert draft["customer_id"] == CUST and draft["invoice_date"] == AS_OF.isoformat()
    assert draft["invoice_no"].upper().startswith("DRAFT"), (
        "the CA types the real number; a placeholder cannot be issued")
    lines = [ln for ln in db.rows("client_sales_invoice_lines")
             if ln["sales_invoice_id"] == draft["id"]]
    assert len(lines) == 1
    assert lines[0]["rate_paise"] == 157_808, "the interest, exactly as the preview computed it"
    assert lines[0]["gst_rate_bps"] == 1800, "the rate of the invoice it relates to"
    assert lines[0]["hsn_sac"] == "998311"
    assert "40 days" in lines[0]["description"] and "₹" not in lines[0]["description"]
    # The tax is on the interest (s.15(2)(d)): 18% on Rs 1,578.08.
    assert draft["taxable_amount_paise"] == 157_808
    assert draft["total_paise"] == 157_808 + (157_808 * 18) // 100
    # The claim behind it is recorded, and says what it was computed from.
    charge, = db.rows("late_interest_charges")
    assert charge["interest_invoice_id"] == draft["id"]
    assert (charge["period_from"], charge["period_to"], charge["days"]) == (
        "2026-08-22", "2026-10-01", 40)
    assert charge["outstanding_paise"] == 8_000_000 and charge["day_count"] == "actual/365"


def test_the_same_days_are_never_charged_twice(monkeypatch):
    db = _book(monkeypatch)
    _overdue(db, 1)
    svc.prepare_drafts(db, FIRM, CLIENT, CUST, AS_OF, CALLER)
    with pytest.raises(HTTPException) as e:
        svc.prepare_drafts(db, FIRM, CLIENT, CUST, AS_OF, CALLER)
    assert e.value.status_code == 409
    assert "already covers" in e.value.detail
    assert len([r for r in db.rows("client_sales_invoices")
                if r["status"] == "draft"]) == 1, "a second click made no second draft"
    # A LATER date charges only the days since.
    later = date(2026, 10, 11)
    out = svc.preview(db, FIRM, CLIENT, later)
    doc = out["parties"][0]["documents"][0]
    assert doc["days_charged"] == 10 and doc["already_charged_through"] == "2026-10-01"
    assert doc["interest_paise"] == L.interest_paise(8_000_000, 1800, 10)


def test_deleting_the_draft_releases_its_period(monkeypatch):
    db = _book(monkeypatch)
    _overdue(db, 1)
    made = svc.prepare_drafts(db, FIRM, CLIENT, CUST, AS_OF, CALLER)["drafts"][0]
    # The CA throws the draft away. (A hard delete nulls the FK in Postgres.)
    db.table("client_sales_invoice_lines").delete().eq("sales_invoice_id", made["invoice_id"]).execute()
    db.table("client_sales_invoices").delete().eq("id", made["invoice_id"]).execute()
    for r in db.rows("late_interest_charges"):
        r["interest_invoice_id"] = None
    doc = svc.preview(db, FIRM, CLIENT, AS_OF)["parties"][0]["documents"][0]
    assert doc["days_charged"] == 40 and doc["status"] == L.CHARGE
    assert svc.prepare_drafts(db, FIRM, CLIENT, CUST, AS_OF, CALLER)["drafts"]


def test_cancelling_the_draft_releases_its_period_too(monkeypatch):
    db = _book(monkeypatch)
    _overdue(db, 1)
    made = svc.prepare_drafts(db, FIRM, CLIENT, CUST, AS_OF, CALLER)["drafts"][0]
    db.table("client_sales_invoices").update({"status": "cancelled"}).eq(
        "id", made["invoice_id"]).execute()
    doc = svc.preview(db, FIRM, CLIENT, AS_OF)["parties"][0]["documents"][0]
    assert doc["status"] == L.CHARGE and doc["days_charged"] == 40


def test_an_issued_interest_invoice_is_never_charged_interest_itself(monkeypatch):
    db = _book(monkeypatch)
    _overdue(db, 1)
    made = svc.prepare_drafts(db, FIRM, CLIENT, CUST, AS_OF, CALLER)["drafts"][0]
    # It is issued, and itself goes overdue.
    db.table("client_sales_invoices").update({
        "status": "issued", "due_date": "2026-08-01", "invoice_no": "INT/0001",
    }).eq("id", made["invoice_id"]).execute()
    out = svc.preview(db, FIRM, CLIENT, date(2027, 1, 1))
    docs = {d["invoice_no"]: d for d in out["parties"][0]["documents"]}
    assert docs["INT/0001"]["status"] == L.INTEREST_INVOICE
    assert docs["INT/0001"]["interest_paise"] == 0


def test_a_customer_with_no_rate_cannot_be_drafted_and_is_told_why(monkeypatch):
    db = _book(monkeypatch, rate=None)
    _overdue(db, 1)
    with pytest.raises(HTTPException) as e:
        svc.prepare_drafts(db, FIRM, CLIENT, CUST, AS_OF, CALLER)
    assert e.value.status_code == 422 and "no interest rate on record" in e.value.detail
    assert not [r for r in db.rows("client_sales_invoices") if r["status"] == "draft"]


def test_a_customer_with_nothing_overdue_is_a_409_not_an_empty_draft(monkeypatch):
    db = _book(monkeypatch)
    _overdue(db, 1, due="2026-12-01")
    with pytest.raises(HTTPException) as e:
        svc.prepare_drafts(db, FIRM, CLIENT, CUST, AS_OF, CALLER)
    assert e.value.status_code == 409 and "nothing overdue" in e.value.detail


def test_an_invoice_with_several_rates_is_named_and_no_rate_is_guessed(monkeypatch):
    db = _book(monkeypatch)
    inv = _overdue(db, 1)
    db.seed("client_sales_invoice_lines", {
        "sales_invoice_id": inv["id"], "description": "Other", "hsn_sac": "998312",
        "gst_rate_bps": 500, "quantity": 1, "rate_paise": 1, "taxable_amount_paise": 1})
    with pytest.raises(HTTPException) as e:
        svc.prepare_drafts(db, FIRM, CLIENT, CUST, AS_OF, CALLER)
    assert e.value.status_code == 422 and "more than one GST rate" in e.value.detail
    assert not [r for r in db.rows("client_sales_invoices") if r["status"] == "draft"]


def test_an_export_is_named_while_an_ordinary_invoice_beside_it_is_drafted(monkeypatch):
    db = _book(monkeypatch)
    _overdue(db, 1)
    _overdue(db, 2, supply_type="zero_rated", invoice_type="Regular")
    out = svc.prepare_drafts(db, FIRM, CLIENT, CUST, AS_OF, CALLER)
    assert len(out["drafts"]) == 1
    assert [b["reason_code"] for b in out["not_drafted"]] == [L.BLOCK_NOT_REGULAR]
    assert out["drafts"][0]["invoice_nos"] == ["INV/2026-27/0001"]
    assert out["statutory_reading"]["grade"] == "[S]"


def test_every_line_names_a_service_item_created_once_and_never_a_stocked_good(monkeypatch):
    """A sales-invoice line must name a Product/Service. Putting interest under
    one of the client's GOODS would make it a stock movement when the draft is
    issued (`domain/inventory_service` keys on a goods line), so it goes under
    a service of its own, found by name and created once."""
    db = _book(monkeypatch)
    _overdue(db, 1)
    out = svc.prepare_drafts(db, FIRM, CLIENT, CUST, AS_OF, CALLER)
    items = [r for r in db.rows("service_catalogue") if r["client_id"] == CLIENT]
    assert [(i["name"], i["kind"], i["default_rate_paise"]) for i in items] == [
        ("Interest on delayed payment", "service", 0)]
    line = next(ln for ln in db.rows("client_sales_invoice_lines")
                if ln["sales_invoice_id"] == out["drafts"][0]["invoice_id"])
    assert line["service_catalogue_id"] == items[0]["id"]

    # A second round finds it rather than creating another.
    _overdue(db, 2, due="2026-07-01")
    svc.prepare_drafts(db, FIRM, CLIENT, CUST, date(2026, 10, 11), CALLER)
    assert len([r for r in db.rows("service_catalogue") if r["client_id"] == CLIENT]) == 1


def test_a_stocked_good_that_already_has_the_name_is_refused_not_duplicated(monkeypatch):
    db = _book(monkeypatch)
    _overdue(db, 1)
    db.seed("service_catalogue", {"id": "SVC-G", "firm_id": FIRM, "client_id": CLIENT,
                                  "name": "  interest ON delayed payment ", "kind": "good",
                                  "is_active": True})
    with pytest.raises(HTTPException) as e:
        svc.prepare_drafts(db, FIRM, CLIENT, CUST, AS_OF, CALLER)
    assert e.value.status_code == 422 and "stocked product" in e.value.detail
    assert not [r for r in db.rows("client_sales_invoices") if r["status"] == "draft"]


def test_a_figure_is_never_taken_from_the_request():
    """`POST /drafts` carries ids and a date and NO amount — the interest is
    computed from the books on every call."""
    from routers.late_interest import LateInterestDraftIn
    assert set(LateInterestDraftIn.model_fields) == {
        "client_id", "customer_id", "as_of_date", "invoice_ids"}


def test_terms_are_written_by_one_door_and_validated_there(monkeypatch):
    db = _book(monkeypatch, rate=None)
    saved = svc.set_terms(db, FIRM, CLIENT, CUST, rate_bps=1800, grace_days=7,
                          basis="invoice_date", actor=CALLER)
    assert saved["rate_bps"] == 1800 and saved["grace_days"] == 7
    row = db.rows("customers")[0]
    assert (row["late_interest_rate_bps"], row["late_interest_grace_days"],
            row["late_interest_from"]) == (1800, 7, "invoice_date")
    with pytest.raises(HTTPException) as e:
        svc.set_terms(db, FIRM, CLIENT, CUST, rate_bps=18_000, grace_days=0, basis="due_date")
    assert e.value.status_code == 422
    # Another client's customer, and a missing one, read the same.
    for bad in ("CUST-NOPE",):
        with pytest.raises(HTTPException) as e2:
            svc.set_terms(db, FIRM, CLIENT, bad, rate_bps=1800, grace_days=0, basis="due_date")
        assert e2.value.status_code == 404
    with pytest.raises(HTTPException) as e3:
        svc.set_terms(db, FIRM, "CLI-OTHER", CUST, rate_bps=1800, grace_days=0, basis="due_date")
    assert e3.value.status_code == 404
    # Clearing is not the same as zero.
    cleared = svc.set_terms(db, FIRM, CLIENT, CUST, rate_bps=None, grace_days=7, basis="invoice_date")
    assert cleared["rate_bps"] is None


# ═════════════════════════════════════════════════════════════════════════════
# THE DOOR
# ═════════════════════════════════════════════════════════════════════════════

from fastapi import FastAPI                              # noqa: E402
from fastapi.testclient import TestClient                 # noqa: E402

import routers.late_interest as door                      # noqa: E402
from core.auth import get_current_user                    # noqa: E402

REVIEWER = {**CALLER, "role": "Reviewer"}
EXECUTIVE = {**CALLER, "role": "Executive"}


def _http(monkeypatch, user=CALLER, *, db="x"):
    app = FastAPI()
    app.include_router(door.router)
    app.dependency_overrides[get_current_user] = lambda: user
    if db is None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
    else:
        monkeypatch.setenv("SUPABASE_URL", "test://db")
        monkeypatch.setattr("core.supabase_client.get_service_supabase", lambda: db)
    return TestClient(app, raise_server_exceptions=False)


def test_the_preview_route_returns_the_screens_answer(monkeypatch):
    db = _book(monkeypatch)
    _overdue(db, 1)
    r = _http(monkeypatch, db=db).get("/api/late-interest/preview",
                                      params={"client_id": CLIENT, "as_of": "2026-10-01"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["totals"]["interest_paise"] == 157_808
    assert data["convention"]["day_count"] == "actual/365"


def test_a_reviewer_may_not_prepare_a_draft_but_may_not_read_either(monkeypatch):
    """accounting:read is Executive and above, and a draft is accounting:write."""
    db = _book(monkeypatch)
    http = _http(monkeypatch, REVIEWER, db=db)
    assert http.get("/api/late-interest/preview", params={"client_id": CLIENT}).status_code == 403
    assert http.post("/api/late-interest/drafts",
                     json={"client_id": CLIENT, "customer_id": CUST}).status_code == 403


def test_a_bad_term_is_a_422_at_the_door(monkeypatch):
    db = _book(monkeypatch)
    http = _http(monkeypatch, db=db)
    r = http.put("/api/late-interest/terms", json={
        "client_id": CLIENT, "customer_id": CUST, "rate_bps": 18, "grace_days": 400,
        "basis": "due_date"})
    assert r.status_code == 422
    r = http.put("/api/late-interest/terms", json={
        "client_id": CLIENT, "customer_id": CUST, "rate_bps": 1800, "grace_days": 5,
        "basis": "due_date"})
    assert r.status_code == 200 and r.json()["data"]["rate_bps"] == 1800


def test_no_database_is_a_503_not_a_silent_nil(monkeypatch):
    r = _http(monkeypatch, db=None).get("/api/late-interest/preview",
                                        params={"client_id": CLIENT})
    assert r.status_code == 503


def test_a_malformed_date_is_refused_at_the_door(monkeypatch):
    db = _book(monkeypatch)
    http = _http(monkeypatch, db=db)
    assert http.get("/api/late-interest/preview",
                    params={"client_id": CLIENT, "as_of": "01-10-2026"}).status_code == 422
    assert http.post("/api/late-interest/drafts", json={
        "client_id": CLIENT, "customer_id": CUST, "as_of_date": "tomorrow"}).status_code == 422


# ═════════════════════════════════════════════════════════════════════════════
# NOTHING POSTS, ISSUES OR EMAILS — read off the source
# ═════════════════════════════════════════════════════════════════════════════

def _imports_and_calls(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
            imported.update(f"{n.module}.{a.name}" for a in n.names)
        elif isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    called |= {n.func.id for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    return imported, called


@pytest.mark.parametrize("path", [
    API / "services" / "late_interest_service.py",
    API / "routers" / "late_interest.py",
    API / "domain" / "sales" / "late_interest.py",
], ids=lambda p: p.name)
def test_interest_reaches_no_posting_issuing_or_mailing_path(path):
    imported, called = _imports_and_calls(path)
    forbidden_modules = {"services.phase2_journal_service", "services.email_service",
                         "services.reminder_service", "services.journal_posting_service"}
    assert not (imported & forbidden_modules), imported & forbidden_modules
    forbidden_calls = {"_create_journal", "issue_invoice", "send_invoice_email",
                       "post_journal_atomic", "send_payment_reminder"}
    assert not (called & forbidden_calls), called & forbidden_calls


def test_the_draft_goes_through_the_one_sales_engine():
    src = (API / "services" / "late_interest_service.py").read_text()
    assert "from routers.sales_invoices import create_invoice" in src
    # And it does not write an invoice row itself.
    tree = ast.parse(src)
    inserted = {ast.unparse(n.func.value.args[0]) for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "insert" and isinstance(n.func.value, ast.Call)
                and n.func.value.args}
    # The claim, and the one catalogue preset every line must name. NEVER an
    # invoice or a line: those are the engine's to write.
    assert inserted == {"'late_interest_charges'", "'service_catalogue'"}, inserted


def _paise_names_in(node: ast.AST) -> set[str]:
    """Every name, attribute or string key ending `_paise` anywhere under `node`."""
    found: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            found.add(n.id)
        elif isinstance(n, ast.Attribute):
            found.add(n.attr)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            found.add(n.value)
    return {s for s in found if s.endswith("_paise")}


def test_the_base_is_the_generated_column_and_is_never_resubtracted():
    """The rule, not a spelling of it: the service does no SUBTRACTION of money.

    What is owed is migration 278's generated `outstanding_paise`, which already
    carries the CGST s.34 note terms; any `a_paise - b_paise` here is a second
    definition of it, however the operands are spelled (a key, a variable, a
    cast of either)."""
    tree = ast.parse((API / "services" / "late_interest_service.py").read_text())
    offenders = sorted({
        ast.unparse(n) for n in ast.walk(tree)
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Sub) and _paise_names_in(n)})
    assert not offenders, (
        "late_interest_service re-derives what is owed instead of reading "
        f"migration 278's column: {offenders}")
    # And it does read the column, in the projection that feeds the base.
    reads = [n for n in ast.walk(tree) if isinstance(n, ast.Constant)
             and isinstance(n.value, str) and "outstanding_paise" in n.value
             and "invoice_no" in n.value]
    assert reads, "the open-invoice fetch no longer projects outstanding_paise"


def test_the_subtraction_rule_can_actually_fail():
    """A guard that has never failed is a guess: the same rule over a service
    that re-subtracts, spelled three different ways, must name each one."""
    for body in ('x = int(inv.get("total_paise") or 0) - int(inv.get("paid_paise") or 0)',
                 "x = total_paise - paid_paise",
                 'x = row["total_paise"] - 5'):
        tree = ast.parse(body)
        assert [n for n in ast.walk(tree)
                if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Sub) and _paise_names_in(n)], body


def test_interest_is_not_a_statutory_module_and_says_so():
    head = (API / "domain" / "sales" / "late_interest.py").read_text().split('"""')[1]
    assert "NOT A STATUTORY RULE" in head.upper().replace("THIS ONE IS NOT", "NOT A STATUTORY RULE") \
        or "COMMERCIAL" in head
    assert "s.15(2)(d)" in head and "[S]" in head


def test_the_router_is_mounted_behind_the_client_guard():
    src = (API / "main.py").read_text()
    assert re.search(r"include_router\(late_interest_router,\s*dependencies=_CLIENT_GUARD\)", src)


# ═════════════════════════════════════════════════════════════════════════════
# THE BROWSER DECIDES NOTHING — held from this side, because a guard written in
# apps/web would assert the browser against a copy of itself.
# ═════════════════════════════════════════════════════════════════════════════

WEB = API.parent / "web"
_PANEL = WEB / "components" / "sales" / "OverdueInterestPanel.tsx"
_HELPER = WEB / "lib" / "sales" / "lateInterest.ts"


def _code(path: Path) -> str:
    """Source with comments stripped: these files explain the rules in prose."""
    src = path.read_text()
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"(^|[^:])//.*$", r"\1", src, flags=re.M)


@pytest.mark.parametrize("path", [_PANEL, _HELPER], ids=lambda p: p.name)
def test_the_screen_carries_no_interest_arithmetic(path):
    src = _code(path)
    # The day-count basis, a year, a rate times a balance, a rounding: each is
    # the server's, and a second copy is a second answer to "how much".
    for banned in (r"\b365\b", r"\b366\b", r"Math\.(round|floor|ceil|trunc)\(.*(paise|outstanding)",
                   r"parseFloat", r"(paise|outstanding)\w*\s*\*", r"\*\s*(rate|bps)\w*",
                   r"daysBetween|differenceInDays"):
        assert not re.search(banned, src), (path.name, banned)


def test_the_request_carries_a_date_and_ids_never_an_amount():
    src = (WEB / "lib" / "api" / "index.ts").read_text()
    start = src.index("lateInterest: {")
    block = src[start:src.index("\n  },\n", start)]
    assert "interest_paise" not in block and "outstanding_paise" not in block
    assert "amount" not in block.lower()


def test_the_panel_only_prepares_drafts_and_reaches_no_issue_or_send_call():
    src = _code(_PANEL)
    assert "api.lateInterest.prepareDrafts" in src
    # The rule, not a list of forbidden verbs: every call into the api layer
    # from this screen is the interest namespace's own (preview, terms, setTerms,
    # prepareDrafts). The words "issue" and "post" appear in its copy, where they
    # tell the CA what the draft does NOT do.
    calls = set(re.findall(r"\bapi\.(\w+)\.(\w+)\(", src))
    assert calls == {("lateInterest", "preview"), ("lateInterest", "terms"),
                     ("lateInterest", "setTerms"), ("lateInterest", "prepareDrafts")}, calls
    assert not re.search(r"\bfetch\(|\.from\(|supabase", src), "no side door around the api layer"


def test_the_screen_is_reachable_from_the_client_sales_page():
    page = (WEB / "app" / "clients" / "[id]" / "sales" / "page.tsx").read_text()
    assert re.search(r'\{ id: "interest", label: "Overdue Interest" \}', page)
    assert re.search(r'tab === "interest" && \(', page)
    assert "<OverdueInterestPanel clientId={clientId}" in page
