"""
Form 24Q, assembled from payroll instead of typed in again.

WHAT WAS WRONG

routers/tds.py's compute_24q took every deductee from the REQUEST BODY. Payroll
computes §192 TDS on every payslip and posts it to the ledger — and then the CA
re-keyed each employee's name, PAN, gross and tax by hand, for all three months
of the quarter. Beyond the labour, re-keying is where the return stops agreeing
with the books, and the mismatch surfaces as a TRACES default months later.

Nothing here computes tax. The TDS is what payroll deducted; this only puts it
in the shape 24Q wants.
"""
from __future__ import annotations

import pytest

from domain.payroll.form24q import (
    build_24q_from_payroll, months_in_quarter, _average_rate_pct)
from domain.tds.tds_computer import TDSDeducteeRecord


def _slip(**over) -> dict:
    base = dict(employee_id="e1", gross_paise=1_00_000_00, tds_paise=5_000_00)
    base.update(over)
    return base


def _emp(**over) -> dict:
    base = dict(id="e1", name="Asha Kumar", pan="ABCDE1234F")
    base.update(over)
    return base


def _challan(**over) -> dict:
    base = dict(challan_no="00123", bsr_code="0510308", payment_date="2026-07-07",
                section="192", tds_paise=15_000_00)
    base.update(over)
    return base


def _build(slips_by_month=None, emps=None, challans=None):
    slips_by_month = slips_by_month or {"2026-04": [_slip()]}
    emps = emps or [_emp()]
    challans = [_challan()] if challans is None else challans
    return build_24q_from_payroll(
        slips_by_month=slips_by_month,
        employees_by_id={e["id"]: e for e in emps},
        challans=challans,
        record_cls=TDSDeducteeRecord,
    )


# ── the quarters ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q,expect", [
    ("Q1", ["2026-04", "2026-05", "2026-06"]),
    ("Q2", ["2026-07", "2026-08", "2026-09"]),
    ("Q3", ["2026-10", "2026-11", "2026-12"]),
    ("Q4", ["2027-01", "2027-02", "2027-03"]),
])
def test_quarters_map_to_payroll_months(q, expect):
    """Q4 crosses the calendar year — FY 2026-27 Q4 is January to March 2027,
    not 2026. Getting that wrong files an empty quarter."""
    assert months_in_quarter("2026-27", q) == expect


# ── the rows ─────────────────────────────────────────────────────────────────

def test_a_deductee_row_is_built_from_the_payslip():
    src = _build()
    assert src.problems == []
    d = src.deductees[0]
    assert d.deductee_name == "ASHA KUMAR"
    assert d.deductee_pan == "ABCDE1234F"
    assert d.section == "192"
    assert d.payment_amount_paise == 1_00_000_00
    assert d.tds_deducted_paise == 5_000_00
    assert d.payment_date == "2026-04-30", "payment date is the month end"
    assert d.challan_no == "00123" and d.bsr_code == "0510308"


def test_one_row_per_employee_per_month():
    src = _build({"2026-04": [_slip()], "2026-05": [_slip()], "2026-06": [_slip()]})
    assert len(src.deductees) == 3
    assert [d.payment_date for d in src.deductees] == \
        ["2026-04-30", "2026-05-31", "2026-06-30"]


def test_the_rate_is_the_average_rate_actually_deducted():
    """§192(1) deducts at the AVERAGE rate — the annual liability spread over
    the year — so the rate on the row is derived from what was deducted, never
    looked up in a table."""
    assert _average_rate_pct(5_000_00, 1_00_000_00) == 5.0
    assert _average_rate_pct(0, 1_00_000_00) == 0.0
    assert _average_rate_pct(1, 0) == 0.0, "no division by zero on a nil-pay month"


def test_totals_reconcile_to_the_challan():
    src = _build({"2026-04": [_slip()], "2026-05": [_slip()], "2026-06": [_slip()]})
    t = src.totals()
    assert t["deductees"] == 3
    assert t["tds_paise"] == 15_000_00
    assert t["challan_paise"] == 15_000_00


# ── what it refuses ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [None, "", "ABCDE1234", "12345ABCDE", "ABCDE12345"])
def test_an_invalid_pan_is_refused_and_cites_206AA(bad):
    """Not a form-filling problem. §206AA requires tax at the HIGHER of the
    specified rate or 20% where PAN is not furnished, so filing tax deducted at
    slab rates against a missing PAN declares a short deduction — and the
    employer carries it, not the employee."""
    src = _build(emps=[_emp(pan=bad)])
    assert src.deductees == []
    assert any("206AA" in p for p in src.problems), src.problems
    assert not src.is_ready


def test_a_quarter_with_tds_but_no_challan_is_refused():
    """TDS deducted is held in trust. A return declaring a deduction with
    nothing showing it was deposited invites the demand it exists to prevent."""
    src = _build(challans=[])
    assert any("No §192 challan" in p for p in src.problems), src.problems
    assert not src.is_ready


def test_no_challan_is_not_an_error_when_nothing_was_deducted():
    """A quarter where every employee was below the threshold has nothing to
    deposit, so demanding a challan would be wrong."""
    src = _build({"2026-04": [_slip(tds_paise=0)]}, challans=[])
    assert src.problems == []
    assert src.deductees == []
    assert src.employees_with_nil_tds == 1


# ── what it leaves to the CA ─────────────────────────────────────────────────

def test_nil_tax_employees_are_counted_rather_than_written_as_rows():
    """Annexure I is a break-up of TDS DEDUCTED, and there is nothing to break
    up for someone below the threshold. They are counted and returned so the
    decision is visible instead of silently made here."""
    src = _build({"2026-04": [_slip(), _slip(employee_id="e2", tds_paise=0)]},
                 [_emp(), _emp(id="e2", name="Below Threshold")])
    assert len(src.deductees) == 1
    assert src.employees_with_nil_tds == 1
