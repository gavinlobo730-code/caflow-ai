"""
The settlement TDS that was deposited, posted, and left off the return (PAY-14).

WHAT WAS WRONG
    `record_settlement` computes §192 on the taxable part of a full and final,
    stores it, and posts it to TDS Payable — Salary through the kernel. So the
    money is deducted, deposited on the challan, and on the ledger.

    `_assemble_24q_source` built the quarter's deductee rows from
    `payroll_runs` → `payroll_slips` and never read `payroll_settlements`. The
    ANNUAL Annexure II does read it (`domain/payroll/annexure2.py`), so the two
    annexures of the same statement disagreed by exactly the settlement TDS:
    Annexure II's total larger than the four quarters of Annexure I.

WHAT THAT COSTS
    TRACES reads that as a short-deduction default against the employer. The
    quarter's deductee rows do not tie to the challan the CA actually paid. And
    the employee gets no 26AS credit for the deduction until the Q4 filing —
    which is the year's end, after they have filed their own return.

WHY IT IS EMITTED AS A SLIP-SHAPED ROW
    So it goes through the SAME PAN validation, the SAME §206AA refusal and the
    SAME challan matching as every other deductee. A second assembly path for
    one statement is how the two annexures came to disagree in the first place.
"""
from __future__ import annotations

import pytest

import routers.payroll as pr
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
CLIENT = "CLI"
EMP = "EMP-1"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "a1",
          "email": "ca@f.test", "role": "Partner"}
FY = "2026-27"


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [pr])
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM})
    d.seed("payroll_employees", {"id": EMP, "firm_id": FIRM, "client_id": CLIENT,
                                 "name": "Asha Rao", "pan": "ABCPA1234A"})
    return d


def _finalised_run(db, month, *, tds=25_000_00, gross=3_00_000_00):
    run = db.seed("payroll_runs", {
        "firm_id": FIRM, "client_id": CLIENT, "month": month, "status": "finalized"})
    db.seed("payroll_slips", {
        "run_id": run["id"], "employee_id": EMP, "gross_paise": gross,
        "tds_paise": tds, "pf_employee_paise": 0, "esi_employee_paise": 0,
        "pt_paise": 0, "net_paise": gross - tds})
    return run


def _settlement(db, *, leaving="2026-11-20", taxable=4_00_000_00, tds=40_000_00):
    return db.seed("payroll_settlements", {
        "firm_id": FIRM, "client_id": CLIENT, "employee_id": EMP, "fy": FY,
        "leaving_date": leaving, "gross_paise": taxable + 1_00_000_00,
        "exempt_paise": 1_00_000_00, "taxable_paise": taxable,
        "deductions_paise": 0, "net_paid_paise": taxable - tds, "tds_paise": tds})


def _source(db, quarter="Q3"):
    src, _months, _deductor = pr._assemble_24q_source(db, CALLER, CLIENT, FY, quarter)
    return src


# ── the finding ──────────────────────────────────────────────────────────────

def test_a_settlement_becomes_a_deductee_row_in_its_own_quarter(db):
    """November is Q3. The deduction was made and deposited in Q3, so Q3's
    Annexure I has to carry it."""
    _finalised_run(db, "2026-11")
    _settlement(db)

    rows = _source(db).deductees

    assert len(rows) == 2, "the month's payslip AND the leaver's settlement"
    assert sum(r.tds_deducted_paise for r in rows) == 65_000_00


def test_the_row_reports_the_taxable_part_not_the_gross(db):
    """§192 is charged on the taxable part; `gross_paise` on a settlement
    includes the §10(10) and §10(10AA) exempt amounts, which are not salary the
    deductee row reports."""
    _settlement(db)

    row = _source(db).deductees[0]

    assert row.payment_amount_paise == 4_00_000_00
    assert row.tds_deducted_paise == 40_000_00


def test_a_settlement_in_another_quarter_stays_there(db):
    """A June leaver belongs in Q1. Putting it in whichever quarter is being
    prepared would move a real deduction between statements."""
    _settlement(db, leaving="2026-06-20")

    assert _source(db, "Q3").deductees == []
    assert len(_source(db, "Q1").deductees) == 1


def test_a_settlement_in_another_financial_year_is_not_in_this_one(db):
    db.seed("payroll_settlements", {
        "firm_id": FIRM, "client_id": CLIENT, "employee_id": EMP, "fy": "2025-26",
        "leaving_date": "2026-11-20", "taxable_paise": 4_00_000_00,
        "tds_paise": 40_000_00, "gross_paise": 4_00_000_00, "exempt_paise": 0,
        "deductions_paise": 0, "net_paid_paise": 3_60_000_00})

    assert _source(db).deductees == []


def test_another_clients_settlement_is_not_in_this_return(db):
    db.seed("clients", {"id": "CLI-2", "firm_id": FIRM})
    db.seed("payroll_settlements", {
        "firm_id": FIRM, "client_id": "CLI-2", "employee_id": EMP, "fy": FY,
        "leaving_date": "2026-11-20", "taxable_paise": 4_00_000_00,
        "tds_paise": 40_000_00, "gross_paise": 4_00_000_00, "exempt_paise": 0,
        "deductions_paise": 0, "net_paid_paise": 3_60_000_00})

    assert _source(db).deductees == []


def test_a_nil_tds_settlement_is_not_a_deductee_row(db):
    """Annexure I reports DEDUCTIONS. A settlement under the threshold is not
    one, and a row of zero would not tie to any challan."""
    _settlement(db, tds=0)

    assert _source(db).deductees == []
    assert _source(db).employees_with_nil_tds == 1


# ── it goes through the same gates as every other deductee ───────────────────

def test_a_settlement_with_no_valid_pan_is_refused_like_any_other_row(db):
    """§206AA requires tax at the higher of the specified rate or 20% where PAN
    is not furnished, and §201(1) puts the shortfall on the EMPLOYER. This is
    the check a second assembly path would have skipped."""
    db.table("payroll_employees").update({"pan": ""}).eq("id", EMP).execute()
    _settlement(db)

    src = _source(db)

    assert src.deductees == []
    assert any("206AA" in p for p in src.problems)


def test_the_settlement_is_matched_to_the_same_challan(db):
    """A deductee row the FVU cannot tie to a challan is a rejected statement,
    or an accepted one whose 26AS entries all read 'U'."""
    _settlement(db)
    db.seed("tds_challans", {
        "firm_id": FIRM, "client_id": CLIENT, "financial_year": FY, "quarter": "Q3",
        "challan_no": "00123", "bsr_code": "0510308", "section": "192",
        "payment_date": "2026-12-07", "tds_paise": 40_000_00})

    row = _source(db).deductees[0]

    assert row.challan_no == "00123"
    assert row.bsr_code == "0510308"


def test_the_quarter_totals_now_tie_to_what_was_deposited(db):
    """The whole point. Before this, the challan carried ₹65,000 and the
    statement declared ₹25,000 — a difference TRACES reads as a
    short-deduction default."""
    _finalised_run(db, "2026-11")
    _settlement(db)
    db.seed("tds_challans", {
        "firm_id": FIRM, "client_id": CLIENT, "financial_year": FY, "quarter": "Q3",
        "challan_no": "00123", "bsr_code": "0510308", "section": "192",
        "payment_date": "2026-12-07", "tds_paise": 65_000_00})

    src = _source(db)

    declared = sum(r.tds_deducted_paise for r in src.deductees)
    deposited = sum(int(c.get("tds_paise") or 0) for c in src.challans)
    assert declared == deposited == 65_000_00
