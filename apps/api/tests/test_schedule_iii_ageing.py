"""
The Schedule III ageing schedules — the rule, without a database.

The SQL half is proved equal to this one by
tests/test_schedule_iii_ageing_parity_pg.py, which needs Postgres. This file is
the statutory reading itself, and runs in the mock suite: which row a document
belongs in, which column, and the three things the platform refuses to guess.

MCA Notification G.S.R. 207(E) of 24 March 2021 amended Schedule III to the
Companies Act 2013 with effect from 1 April 2021. These are the Division I
tables — Division II (Ind AS) splits the doubtful receivables row in two.
"""
from datetime import date

import pytest

from domain.reporting import ageing
from domain.reporting.ageing import Payable, Receivable

AS_OF = date(2026, 3, 31)
TODAY = date(2026, 3, 31)


def _build(receivables=(), payables=(), as_of=AS_OF, today=TODAY):
    return ageing.build(list(receivables), list(payables), as_of, today)


def _row(table, key):
    return next(r for r in table["rows"] if r["key"] == key)


# ── The two tables are different shapes ──────────────────────────────────────

def test_receivables_have_five_prescribed_columns_from_six_months():
    doc = _build()
    prescribed = [b["label"] for b in doc["receivables"]["buckets"] if b["prescribed"]]
    assert prescribed == ["Less than 6 months", "6 months - 1 year",
                          "1-2 years", "2-3 years", "More than 3 years"]


def test_payables_have_four_prescribed_columns_from_one_year():
    """Not five, and not starting at six months. Giving the payables table the
    receivables' columns is the easy mistake and it is a wrong disclosure."""
    doc = _build()
    prescribed = [b["label"] for b in doc["payables"]["buckets"] if b["prescribed"]]
    assert prescribed == ["Less than 1 year", "1-2 years", "2-3 years",
                          "More than 3 years"]


def test_the_two_row_sets_are_the_prescribed_ones():
    doc = _build()
    assert [r["key"] for r in doc["receivables"]["rows"]] == [
        "undisputed_good", "undisputed_doubtful", "disputed_good", "disputed_doubtful"]
    assert [r["key"] for r in doc["payables"]["rows"]] == [
        "msme", "others", "disputed_msme", "disputed_others"]


def test_not_due_is_marked_as_an_additional_column():
    """The prescribed table has no Not due column. Returning it separately lets
    a filer present either shape from one answer; marking it `prescribed: false`
    is what stops it being mistaken for a statutory one."""
    for table in ("receivables", "payables"):
        first = _build()[table]["buckets"][0]
        assert first["key"] == "not_due"
        assert first["prescribed"] is False


# ── Buckets ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("due,bucket", [
    ("2026-04-01", "not_due"),     # after the reporting date
    ("2026-03-31", "lt_6m"),       # due today: outstanding for nothing yet
    ("2025-10-01", "lt_6m"),
    ("2025-09-30", "m6_y1"),       # EXACTLY six months — not "less than"
    ("2025-04-01", "m6_y1"),
    ("2025-03-31", "y1_y2"),       # exactly one year
    ("2024-04-01", "y1_y2"),
    ("2024-03-31", "y2_y3"),
    ("2023-04-01", "y2_y3"),
    ("2023-03-31", "gt_y3"),       # exactly three years
    ("2019-01-01", "gt_y3"),
])
def test_receivable_buckets(due, bucket):
    assert ageing.receivable_bucket(date.fromisoformat(due), AS_OF) == bucket


@pytest.mark.parametrize("due,bucket", [
    ("2026-04-01", "not_due"),
    ("2025-04-01", "lt_y1"),
    ("2025-03-31", "y1_y2"),       # exactly one year
    ("2024-03-31", "y2_y3"),
    ("2023-03-31", "gt_y3"),
])
def test_payable_buckets(due, bucket):
    assert ageing.payable_bucket(date.fromisoformat(due), AS_OF) == bucket


def test_a_document_with_no_due_date_ages_from_the_transaction_date():
    """Schedule III ages from the due date of payment; where none is specified
    the ageing runs from the date of the transaction. The caller passes the
    already-resolved reference date, so what this pins is that a genuinely
    undated document lands in the youngest prescribed bucket rather than
    vanishing or landing in the oldest."""
    assert ageing.receivable_bucket(None, AS_OF) == "lt_6m"
    assert ageing.payable_bucket(None, AS_OF) == "lt_y1"


def test_six_months_is_calendar_months_not_180_days():
    """2026-03-31 less six calendar months is 2025-09-30, and less 180 days is
    2025-10-02. A document due on 2025-10-01 is inside six months by the
    statute's reckoning and outside it by the day count."""
    assert ageing.minus_months(AS_OF, 6) == date(2025, 9, 30)
    assert ageing.receivable_bucket(date(2025, 10, 1), AS_OF) == "lt_6m"


def test_month_subtraction_clamps_to_a_real_date():
    assert ageing.minus_months(date(2026, 8, 31), 6) == date(2026, 2, 28)
    assert ageing.minus_months(date(2024, 2, 29), 12) == date(2023, 2, 28)
    assert ageing.minus_months(date(2026, 1, 31), 1) == date(2025, 12, 31)


# ── Rows ─────────────────────────────────────────────────────────────────────

def test_every_receivable_row_is_reachable():
    docs = [
        Receivable(100, date(2025, 12, 1)),
        Receivable(200, date(2025, 12, 1), doubtful=True),
        Receivable(400, date(2025, 12, 1), disputed=True),
        Receivable(800, date(2025, 12, 1), disputed=True, doubtful=True),
    ]
    t = _build(receivables=docs)["receivables"]
    assert _row(t, "undisputed_good")["total_paise"] == 100
    assert _row(t, "undisputed_doubtful")["total_paise"] == 200
    assert _row(t, "disputed_good")["total_paise"] == 400
    assert _row(t, "disputed_doubtful")["total_paise"] == 800
    assert t["total_paise"] == 1500


def test_medium_enterprises_are_others_not_msme():
    """Row (i) "MSME" is read with the balance-sheet line item Schedule III
    prescribes — total outstanding dues of MICRO and SMALL enterprises — which
    comes from MSMED s.22 and stops at small. s.15, and so IT Act s.43B(h),
    works off "supplier", which s.2(n) also confines to micro and small. A
    medium enterprise is registered under MSMED and still belongs in Others."""
    docs = [
        Payable(100, date(2025, 12, 1), msme_status="micro", vendor_id="v1", vendor_name="A"),
        Payable(200, date(2025, 12, 1), msme_status="small", vendor_id="v2", vendor_name="B"),
        Payable(400, date(2025, 12, 1), msme_status="medium", vendor_id="v3", vendor_name="C"),
        Payable(800, date(2025, 12, 1), msme_status="not_registered", vendor_id="v4", vendor_name="D"),
    ]
    t = _build(payables=docs)["payables"]
    assert _row(t, "msme")["total_paise"] == 300
    assert _row(t, "others")["total_paise"] == 1200


def test_disputed_dues_split_msme_from_others_too():
    docs = [
        Payable(100, date(2025, 12, 1), msme_status="small", disputed=True,
                vendor_id="v1", vendor_name="A"),
        Payable(200, date(2025, 12, 1), msme_status="medium", disputed=True,
                vendor_id="v2", vendor_name="B"),
    ]
    t = _build(payables=docs)["payables"]
    assert _row(t, "disputed_msme")["total_paise"] == 100
    assert _row(t, "disputed_others")["total_paise"] == 200
    assert _row(t, "msme")["total_paise"] == 0


# ── What is refused rather than guessed ──────────────────────────────────────

def test_an_unclassified_vendor_is_a_gap_and_never_an_other():
    """The reason this is not a default. IT Act s.43B(h), inserted by the
    Finance Act 2023 with effect from AY 2024-25, disallows a deduction for a
    sum payable to a micro or small enterprise beyond the MSMED s.15 limit
    unless actually paid. Calling an unclassified vendor "Others" does not
    misplace a row; it changes the client's taxable income."""
    docs = [
        Payable(100, date(2025, 12, 1), msme_status="micro", vendor_id="v1", vendor_name="Known"),
        Payable(900, date(2025, 12, 1), msme_status=None, vendor_id="v2", vendor_name="Unknown"),
    ]
    doc = _build(payables=docs)
    t = doc["payables"]
    assert _row(t, "others")["total_paise"] == 0, "an unclassified vendor was folded into Others"
    assert t["total_paise"] == 100
    assert t["unclassified_paise"] == 900
    assert t["unclassified_vendors"] == [
        {"vendor_id": "v2", "vendor_name": "Unknown", "outstanding_paise": 900}]
    assert "vendors_unclassified" in [g["code"] for g in doc["gaps"]]


def test_unclassified_vendors_are_listed_largest_first():
    docs = [
        Payable(100, date(2025, 12, 1), vendor_id="v1", vendor_name="Small One"),
        Payable(900, date(2025, 12, 1), vendor_id="v2", vendor_name="Big One"),
        Payable(50, date(2025, 12, 1), vendor_id="v1", vendor_name="Small One"),
    ]
    listed = _build(payables=docs)["payables"]["unclassified_vendors"]
    assert [v["vendor_name"] for v in listed] == ["Big One", "Small One"]
    assert listed[1]["outstanding_paise"] == 150, "the vendor's bills were not summed"


def test_no_unclassified_vendor_means_no_gap():
    docs = [Payable(100, date(2025, 12, 1), msme_status="micro",
                    vendor_id="v1", vendor_name="Known")]
    doc = _build(payables=docs)
    assert "vendors_unclassified" not in [g["code"] for g in doc["gaps"]]
    assert doc["payables"]["unclassified_vendors"] == []


def test_unbilled_dues_are_null_not_zero():
    """Schedule III requires unbilled dues to be disclosed separately under both
    schedules. Nothing in this platform holds them, and a zero would claim there
    are none."""
    doc = _build()
    assert doc["receivables"]["unbilled_dues_paise"] is None
    assert doc["payables"]["unbilled_dues_paise"] is None
    assert "unbilled_dues_not_modelled" in [g["code"] for g in doc["gaps"]]


def test_a_past_reporting_date_says_what_it_excludes():
    """Amounts are each document's balance outstanding today. Aged against an
    earlier date, a document settled since is simply absent — the schedule
    understates and must say so."""
    doc = _build(as_of=date(2026, 3, 31), today=date(2026, 9, 1))
    assert "as_at_is_current_balance" in [g["code"] for g in doc["gaps"]]
    assert "understates" in dict((g["code"], g["message"]) for g in doc["gaps"])[
        "as_at_is_current_balance"]


def test_todays_schedule_carries_no_as_at_caveat():
    doc = _build(as_of=date(2026, 3, 31), today=date(2026, 3, 31))
    assert "as_at_is_current_balance" not in [g["code"] for g in doc["gaps"]]


# ── Totals ───────────────────────────────────────────────────────────────────

def test_column_totals_and_row_totals_agree():
    docs = [
        Receivable(100, date(2026, 4, 30)),
        Receivable(200, date(2026, 1, 31)),
        Receivable(400, date(2025, 1, 31), doubtful=True),
        Receivable(800, date(2022, 1, 31), disputed=True),
    ]
    t = _build(receivables=docs)["receivables"]
    assert sum(t["column_totals"].values()) == t["total_paise"] == 1500
    assert sum(r["total_paise"] for r in t["rows"]) == 1500


def test_a_settled_document_is_not_aged():
    """Belt and braces for a caller that hands over a closed document: a zero or
    negative balance is not a receivable and must not create a row."""
    t = _build(receivables=[Receivable(0, date(2020, 1, 1)),
                            Receivable(-500, date(2020, 1, 1))])["receivables"]
    assert t["total_paise"] == 0
