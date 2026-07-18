"""
R1.2 — payroll finalization journal must balance (fixes finding F13).

Before the fix, journal_for_payroll debited only `gross` but credited
net + PF + ESI + PT + TDS, which exceeds gross by the EMPLOYER PF/ESI, so the
posting kernel raised on the imbalance and finalization 500'd on essentially
every run (PF/ESI are on by default). This test locks the invariant that the
generated journal always balances, and that the Salaries Expense debit is the
employer's total cost (gross wages + employer statutory contributions).

Runs everywhere — exercises the pure line-builder, no database needed.
"""
from __future__ import annotations

import pytest

from services.phase2_journal_service import Phase2JournalService

ACCOUNT_IDS = {
    "salary_exp": "acc-salary-exp",
    "net": "acc-net-payable",
    "pf": "acc-pf-payable",
    "esi": "acc-esi-payable",
    "pt": "acc-pt-payable",
    "tds": "acc-tds-payable",
}


def _build(run: dict) -> list[dict]:
    return Phase2JournalService._build_payroll_lines(ACCOUNT_IDS, run)


def _sums(lines: list[dict]) -> tuple[int, int]:
    return (
        sum(l["debit_paise"] for l in lines),
        sum(l["credit_paise"] for l in lines),
    )


def test_balances_with_pf_esi_pt_tds():
    # basic=1000.00; PF emp/er = 120 each -> total 240; ESI emp 7.50 / er 32.50 -> total 40;
    # PT = 200; TDS = 0. net = gross - (pf_emp + esi_emp + pt + tds) = 1000 - (120+7.50+200) = 672.50
    run = {
        "month": "2026-06",
        "total_gross_paise": 100000,
        "total_net_paise": 67250,
        "total_pf_paise": 24000,   # 12000 employee + 12000 employer
        "total_esi_paise": 4000,   # 750 employee + 3250 employer
        "total_pt_paise": 20000,
        "total_tds_paise": 0,
    }
    lines = _build(run)
    debit, credit = _sums(lines)
    assert debit == credit, f"payroll journal must balance: Dr {debit} != Cr {credit}"

    # Salaries Expense debit = employer's total cost = gross + employer PF (12000) + employer ESI (3250).
    salary_debit = next(l["debit_paise"] for l in lines if l["account_id"] == ACCOUNT_IDS["salary_exp"])
    assert salary_debit == 100000 + 12000 + 3250 == 115250
    # ...and it is NOT the bare gross (that was exactly the F13 bug).
    assert salary_debit != run["total_gross_paise"]


def test_balances_without_pf_esi():
    # No PF/ESI applicable -> net = gross - (pt + tds); debit == gross; no pf/esi lines.
    run = {
        "month": "2026-06",
        "total_gross_paise": 50000,
        "total_net_paise": 48000,   # gross - pt(2000) - tds(0)
        "total_pf_paise": 0,
        "total_esi_paise": 0,
        "total_pt_paise": 2000,
        "total_tds_paise": 0,
    }
    lines = _build(run)
    debit, credit = _sums(lines)
    assert debit == credit == 50000
    account_ids = {l["account_id"] for l in lines}
    assert ACCOUNT_IDS["pf"] not in account_ids and ACCOUNT_IDS["esi"] not in account_ids


def test_balances_with_tds_present():
    run = {
        "month": "2026-06",
        "total_gross_paise": 1000000,
        "total_net_paise": 780000,   # gross - pf_emp(60000) - esi_emp(0) - pt(0) - tds(160000)
        "total_pf_paise": 120000,    # 60000 + 60000
        "total_esi_paise": 0,
        "total_pt_paise": 0,
        "total_tds_paise": 160000,
    }
    lines = _build(run)
    debit, credit = _sums(lines)
    assert debit == credit
    # employer PF is 60000 -> total cost = 1,000,000 + 60,000 = 1,060,000
    assert debit == 1060000


def test_identity_violation_fails_loud():
    """Defensive guard: if `net` is ever reduced by a deduction with no matching
    credit leg (e.g. a future loan/advance recovery), total_cost drops below gross
    and the journal must raise rather than post a wrong-but-balanced entry."""
    run = {
        "month": "2026-06",
        "total_gross_paise": 100000,
        "total_net_paise": 40000,   # artificially low vs gross with no offsetting credit
        "total_pf_paise": 0, "total_esi_paise": 0,
        "total_pt_paise": 0, "total_tds_paise": 0,
    }
    with pytest.raises(ValueError, match="identity violated"):
        _build(run)


def test_every_line_is_pure_debit_or_credit():
    """Posting-kernel invariant: each line is a debit XOR a credit (never both)."""
    run = {
        "month": "2026-06", "total_gross_paise": 100000, "total_net_paise": 67250,
        "total_pf_paise": 24000, "total_esi_paise": 4000, "total_pt_paise": 20000,
        "total_tds_paise": 0,
    }
    for line in _build(run):
        d, c = line["debit_paise"], line["credit_paise"]
        assert (d > 0) != (c > 0), f"line must be debit XOR credit: {line}"


# ── Salary disbursement (mark-paid) journal ───────────────────────────────────
# Dr Net Salary Payable / Cr Bank — clears the payable raised at finalization.

def _disb(net: int) -> list[dict]:
    return Phase2JournalService._build_payroll_disbursement_lines(
        "acc-net-payable", "acc-bank", net)


def test_disbursement_balances_and_clears_the_payable():
    lines = _disb(67250)
    debit, credit = _sums(lines)
    assert debit == credit == 67250          # single Dr == single Cr == net pay
    dr = next(l for l in lines if l["debit_paise"] > 0)
    cr = next(l for l in lines if l["credit_paise"] > 0)
    assert dr["account_id"] == "acc-net-payable" and dr["debit_paise"] == 67250
    assert cr["account_id"] == "acc-bank" and cr["credit_paise"] == 67250


def test_disbursement_lines_are_pure_debit_or_credit():
    for line in _disb(50000):
        d, c = line["debit_paise"], line["credit_paise"]
        assert (d > 0) != (c > 0), f"line must be debit XOR credit: {line}"


def test_disbursement_rejects_non_positive_net():
    for bad in (0, -100):
        with pytest.raises(ValueError, match="no net pay"):
            _disb(bad)
