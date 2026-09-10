"""PAY-29 — the payslip states the things it is produced in order to state.

WHAT WAS WRONG
    services/payslip_pdf_service.py rendered the employer's name, the
    employee's name/designation/department/PAN, the pay period, seven earning
    lines, five deduction lines and net pay. Nothing else.

    So: an employee querying their PF with the EPFO could not find their UAN or
    the establishment code the contribution was remitted under — the two things
    the EPFO asks for. An employee producing the slip for a loan gave a bank a
    document naming no bank account and no employer registration. The
    employer's own contribution — the whole difference between gross salary and
    cost to company — was invisible, so the CTC conversation had no document
    behind it. And there was no year-to-date, which is the figure that has to
    agree with Form 16 in March.

    The data was not merely unrendered. The employee join selected only
    (name, pan, designation, department), so uan / esi_number /
    bank_account_no / bank_ifsc could not reach the renderer at all.

WHAT THIS PINS
    The arithmetic, not the layout. Two invariants are worth more than the rest:

    (1) The employer's contributions are NOT in the deductions table. Net is
        gross minus the deductions shown and nothing else — the one sum an
        employee actually checks.

    (2) pf_employer_paise is the WHOLE 12% and the EPS diversion is INSIDE it
        (migration 295's COMMENT ON COLUMN says so). Listing the 12% beside the
        EPS line would tell every employee their employer paid 20.33%.
"""
from __future__ import annotations

import io

import pdfplumber

from services.payslip_pdf_service import (
    build_payslip_pdf, deduction_lines, employer_contribution_lines,
    fy_months_upto, mask_account, ytd_totals,
)


SLIP = {
    "id": "S1", "employee_id": "E1", "month": 7, "year": 2026,
    "gross_paise": 50_000_00, "basic_paise": 25_000_00, "hra_paise": 12_500_00,
    "pf_employee_paise": 1_800_00, "esi_employee_paise": 0,
    "pt_paise": 200_00, "tds_paise": 1_950_00, "net_paise": 46_050_00,
    "working_days": 26, "days_present": 26, "lop_days": 0,
    # Employer side (migrations 054, 295, 329).
    "pf_employer_paise": 1_800_00,
    "pf_employer_epf_paise": 550_00, "pf_employer_eps_paise": 1_250_00,
    "esi_employer_paise": 0, "edli_paise": 75_00, "pf_admin_paise": 75_00,
}
EMPLOYEE = {"name": "Asha Kumar", "pan": "ABCPK1234F", "designation": "Fitter",
            "department": "Assembly", "uan": "100200300400",
            "esi_number": "3100123456", "bank_account_no": "0011223344",
            "bank_ifsc": "HDFC0001234"}
RUN = {"month": "2026-07", "firm_id": "FIRM", "client_id": "CLI"}
EMPLOYER = {"id": "CLI", "client_name": "Acme Manufacturing",
            "legal_name": "Acme Manufacturing Private Limited",
            "pan": "AAACA1234C", "tan": "MUMA12345B",
            "epf_establishment_code": "MHBAN0012345000",
            "esic_employer_code": "31000123450001099"}
YTD = {"months": 4, "gross_paise": 2_00_000_00, "deductions_paise": 15_800_00,
       "tds_paise": 7_800_00, "net_paise": 1_84_200_00}


def _text(pdf: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return "\n".join(page.extract_text() or "" for page in doc.pages)


# ───────────── the two invariants that cost the most to get wrong ─────────────

def test_the_employers_contribution_is_not_a_deduction():
    """Net is gross minus the deductions SHOWN. If the employer's 12% appeared
    in that table the arithmetic on the page would not close, and the employee
    would read their employer's contribution as money taken from them."""
    rows, total = deduction_lines(SLIP)
    assert total == 1_800_00 + 0 + 200_00 + 1_950_00
    assert SLIP["gross_paise"] - total == SLIP["net_paise"]
    labels = " ".join(r[0] for r in rows)
    assert "Employer" not in labels
    assert "EDLI" not in labels


def test_the_eps_diversion_is_inside_the_twelve_percent_not_beside_it():
    """migration 295: 'the employer 12% in pf_employer_paise, not additional to
    it.' EPF + EPS must sum to the 12%, and the block's total must add the 12%
    ONCE — 1800 + 75 + 75, never 1800 + 550 + 1250 + 75 + 75."""
    rows, total = employer_contribution_lines(SLIP)
    assert total == 1_800_00 + 0 + 75_00 + 75_00 == 1_950_00
    assert SLIP["pf_employer_epf_paise"] + SLIP["pf_employer_eps_paise"] \
        == SLIP["pf_employer_paise"]
    assert any("EPF (Employer)" in r[0] for r in rows)
    assert any("EPS (Employer)" in r[0] for r in rows)


def test_a_slip_written_before_the_split_existed_shows_the_total_it_holds():
    """Migration 295 defaulted both split columns to 0 on every existing row and
    said splitting them retrospectively would be inventing a figure. So an old
    slip shows one Provident Fund (Employer) line, not a split that reads
    550 + 0 != 1800."""
    old = dict(SLIP, pf_employer_epf_paise=0, pf_employer_eps_paise=0)
    rows, total = employer_contribution_lines(old)
    assert total == 1_950_00
    assert any(r[0] == "Provident Fund (Employer)" for r in rows)
    assert not any("EPS" in r[0] for r in rows)


def test_no_employer_contribution_means_no_block_at_all():
    rows, total = employer_contribution_lines(
        {"pf_employer_paise": 0, "esi_employer_paise": 0,
         "edli_paise": 0, "pf_admin_paise": 0})
    assert (rows, total) == ([], 0)


# ─────────────────────────── year to date ───────────────────────────

def test_the_year_to_date_is_the_financial_year_not_the_calendar_year():
    """Form 16 and the §192 withholding both run April to March, so a January
    payslip's YTD starts the previous April. A calendar-year YTD would disagree
    with the certificate the same employee gets in June."""
    assert fy_months_upto("2026-07") == ["2026-04", "2026-05", "2026-06", "2026-07"]
    assert fy_months_upto("2026-04") == ["2026-04"]
    assert fy_months_upto("2027-01")[0] == "2026-04"
    assert len(fy_months_upto("2027-03")) == 12


def test_an_unparseable_month_gives_no_period_rather_than_a_wrong_one():
    for bad in ("", None, "2026", "2026/07", "2026-13", "xxxx-07"):
        assert fy_months_upto(bad) == []


def test_the_year_to_date_adds_the_deductions_the_payslip_shows():
    """Summed from DEDUCTION_DEFS rather than from a stored total, so a
    deduction added to the slip is in the YTD the same day it is on the slip."""
    ytd = ytd_totals([SLIP, dict(SLIP, gross_paise=52_000_00, net_paise=48_050_00)])
    assert ytd["months"] == 2
    assert ytd["gross_paise"] == 1_02_000_00
    assert ytd["deductions_paise"] == 2 * (1_800_00 + 200_00 + 1_950_00)
    assert ytd["tds_paise"] == 2 * 1_950_00


def test_no_slips_is_an_empty_year_not_a_crash():
    assert ytd_totals([])["months"] == 0
    assert ytd_totals(None)["gross_paise"] == 0


# ─────────────────────────── the bank account ───────────────────────────

def test_the_account_number_shows_only_its_last_four_digits():
    """The slip is emailed, printed and handed to landlords. Which account was
    credited is the question it answers; the whole number is not."""
    assert mask_account("0011223344") == "XXXXXX3344"
    assert mask_account("123") == "123"          # nothing left to mask
    assert mask_account(None) == ""
    assert mask_account("  0011 2233 44 ") == "XXXXXX3344"


# ─────────────────────────── the rendered document ───────────────────────────

def test_everything_reaches_the_page():
    text = _text(build_payslip_pdf(SLIP, EMPLOYEE, RUN, EMPLOYER, ytd=YTD))
    for expected in ("100200300400",                # UAN
                     "3100123456",                  # ESIC number
                     "XXXXXX3344", "HDFC0001234",   # bank account, masked
                     "MHBAN0012345000",             # EPF establishment
                     "31000123450001099",           # ESIC employer code
                     "MUMA12345B",                  # TAN, IT Act §203A
                     "Employer Contributions",
                     "Year to Date",
                     "Rupees Forty Six Thousand Fifty Only"):
        assert expected in text, f"{expected!r} is not on the payslip"


def test_the_full_account_number_never_reaches_the_page():
    text = _text(build_payslip_pdf(SLIP, EMPLOYEE, RUN, EMPLOYER, ytd=YTD))
    assert "0011223344" not in text


def test_a_slip_with_none_of_it_still_renders():
    """Every one of these fields is optional on the master. A client that has
    recorded no registrations and an employee with no UAN must still get a
    payslip — an absent line, not a blank label reading 'UAN:'."""
    text = _text(build_payslip_pdf(
        {"gross_paise": 30_000_00, "net_paise": 30_000_00},
        {"name": "Ravi"}, {"month": "2026-07"}, {"client_name": "Small Co"}))
    assert "Ravi" in text and "Small Co" in text
    for absent in ("UAN:", "ESIC No.:", "Bank A/c:", "EPF Estt.:",
                   "Employer Contributions", "Year to Date"):
        assert absent not in text


def test_no_year_to_date_supplied_means_no_year_to_date_block():
    """Absent, not zero. A YTD of nil in month nine is a statement, and a false
    one — load_ytd returns {} when the lookup fails, and the payslip must not
    turn that into a claim about the employee's earnings."""
    text = _text(build_payslip_pdf(SLIP, EMPLOYEE, RUN, EMPLOYER, ytd=None))
    assert "Year to Date" not in text
    assert "Net Pay" in text                       # the pay itself is unaffected
    text_zero = _text(build_payslip_pdf(SLIP, EMPLOYEE, RUN, EMPLOYER,
                                        ytd={"months": 0}))
    assert "Year to Date" not in text_zero
