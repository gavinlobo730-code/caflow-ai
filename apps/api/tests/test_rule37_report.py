"""
The Rule 37 report finds the bills that have gone 180 days unpaid.

The arithmetic is tested in test_rule37_itc_reversal.py against the rule. This
is about the query: which bills are picked up, which are correctly left alone,
and whether a large book is read completely.
"""
from __future__ import annotations

import pytest

from services import itc_reversal_service as svc
from tests.e2e_harness import FakeDB

FIRM = "firm-1"
CLIENT = "client-1"
TODAY = "2026-07-15"          # a bill dated 1 Jan 2026 is 195 days old here


@pytest.fixture
def db():
    return FakeDB()


def _bill(db, bill_no, *, bill_date="2026-01-01", status="received",
          total=118_000_00, paid=0, tds=0, cgst=9_000_00, sgst=9_000_00,
          igst=0, client_id=CLIENT):
    return db.seed("purchase_bills", {
        "firm_id": FIRM, "client_id": client_id, "vendor_id": "V1",
        "bill_no": bill_no, "bill_date": bill_date, "status": status,
        "total_paise": total, "paid_paise": paid, "tds_paise": tds,
        "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": igst,
    })


def _report(db, **kw):
    return svc.rule37_report(db, FIRM, CLIENT, as_of=TODAY, **kw)


# ── what gets picked up ──────────────────────────────────────────────────────

def test_an_unpaid_bill_past_180_days_is_reported(db):
    _bill(db, "B-1")

    out = _report(db)

    assert out["bill_count"] == 1
    item = out["bills"][0]
    assert item["bill_no"] == "B-1"
    assert item["days_outstanding"] == 195
    assert item["payment_due_by"] == "2026-06-30"
    assert item["reversal"]["total_paise"] == 18_000_00


def test_the_report_says_which_return_the_reversal_belongs_in(db):
    """Rule 37(1): the period AFTER the one the 180 days expired in. The dates
    do not make that obvious and it is the usual thing to get wrong."""
    _bill(db, "B-1")

    assert _report(db)["bills"][0]["reverse_in_period"] == "072026"


def test_totals_add_up_per_tax_head(db):
    """GSTR-3B table 4(B) reports the heads separately."""
    _bill(db, "B-1", cgst=9_000_00, sgst=9_000_00, igst=0)
    _bill(db, "B-2", cgst=0, sgst=0, igst=18_000_00)

    totals = _report(db)["totals"]

    assert totals["cgst_paise"] == 9_000_00
    assert totals["sgst_paise"] == 9_000_00
    assert totals["igst_paise"] == 18_000_00
    assert totals["total_paise"] == 36_000_00


def test_a_part_paid_bill_reports_only_the_unpaid_proportion(db):
    _bill(db, "B-1", paid=59_000_00)

    item = _report(db)["bills"][0]

    assert item["unpaid_paise"] == 59_000_00
    assert item["reversal"]["total_paise"] == 9_000_00


# ── what is correctly left alone ─────────────────────────────────────────────

def test_a_bill_inside_the_180_days_is_not_reported(db):
    _bill(db, "B-RECENT", bill_date="2026-06-01")

    assert _report(db)["bill_count"] == 0


def test_a_fully_paid_bill_is_not_reported_however_old(db):
    _bill(db, "B-PAID", bill_date="2024-01-01", paid=118_000_00)

    assert _report(db)["bill_count"] == 0


def test_a_bill_settled_by_tds_is_not_reported(db):
    """The interpretation from the domain module, visible at report level: TDS
    is remitted on the supplier's behalf, so this bill is settled."""
    _bill(db, "B-TDS", total=100_000_00, paid=90_000_00, tds=10_000_00)

    assert _report(db)["bill_count"] == 0


def test_a_bill_with_no_input_credit_is_not_reported(db):
    """An exempt or non-GST purchase carries no ITC, so 180 days of non-payment
    changes nothing about the return. Listing it would bury the real findings."""
    _bill(db, "B-NOITC", cgst=0, sgst=0, igst=0)

    assert _report(db)["bill_count"] == 0


@pytest.mark.parametrize("status", ["draft", "cancelled"])
def test_drafts_and_cancelled_bills_carry_no_credit_to_reverse(db, status):
    """A draft was never claimed; a cancelled bill was undone."""
    _bill(db, "B-X", status=status)

    assert _report(db)["bill_count"] == 0


def test_another_clients_bill_is_not_included(db):
    _bill(db, "B-OTHER", client_id="client-2")

    assert _report(db)["bill_count"] == 0


# ── how it reads ─────────────────────────────────────────────────────────────

def test_the_longest_overdue_bill_comes_first(db):
    """That is the one accruing the most §50 interest."""
    _bill(db, "B-NEW", bill_date="2026-01-01")
    _bill(db, "B-OLD", bill_date="2024-01-01")

    assert [b["bill_no"] for b in _report(db)["bills"]] == ["B-OLD", "B-NEW"]


def test_the_report_names_the_rule_it_applies(db):
    _bill(db, "B-1")

    out = _report(db)

    assert "Rule 37" in out["rule"]
    assert out["ca_review_required"] is True, "this reports; it does not post or file"


def test_asking_as_at_an_earlier_date_changes_the_answer(db):
    """The CA asks this at a period end, not on the day they open the screen —
    the reversal belongs in a specific return."""
    _bill(db, "B-1", bill_date="2026-01-01")

    assert svc.rule37_report(db, FIRM, CLIENT, as_of="2026-06-30")["bill_count"] == 0
    assert svc.rule37_report(db, FIRM, CLIENT, as_of="2026-07-01")["bill_count"] == 1


# ── the read itself ──────────────────────────────────────────────────────────

def test_a_book_larger_than_one_page_is_read_completely(db):
    """PostgREST caps a read at db-max-rows and returns the short page without
    complaint — this codebase has hit that six times now. Under-reading here
    under-reports the reversal, which is the direction that costs interest.
    """
    for i in range(svc.PAGE + 25):
        _bill(db, f"B-{i:05d}")

    out = _report(db)

    assert out["bill_count"] == svc.PAGE + 25
    assert out["totals"]["total_paise"] == (svc.PAGE + 25) * 18_000_00
