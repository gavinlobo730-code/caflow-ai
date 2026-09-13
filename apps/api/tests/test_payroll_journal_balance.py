"""
R1.2 — payroll finalization journal must balance (fixes finding F13).

Before the fix, journal_for_payroll debited only `gross` but credited
net + PF + ESI + PT + TDS, which exceeds gross by the EMPLOYER PF/ESI, so the
posting kernel raised on the imbalance and finalization 500'd on essentially
every run (PF/ESI are on by default). This test locks the invariant that the
generated journal always balances.

SINCE PAY-25 THERE ARE TWO DEBITS, and the invariant is sharper for it.
Schedule III Part II presents Employee Benefits Expense split into salaries and
wages and contribution to provident and other funds, so `Salaries Expense`
carries GROSS and the employer's own contribution goes to its own account. The
sum of the two is still the employer's total cost of employment, which is what
these tests assert.

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
    "employer_contribution": "acc-employer-contribution",
}


def _build(run: dict, employer_contribution: int = 0) -> list[dict]:
    """The employer share is an EXPLICIT argument, not derived from `run`.

    `payroll_runs` stores `total_pf_paise` and `total_esi_paise` combined and
    has no column for either employer half — it is on the SLIPS, which
    `journal_for_payroll` sums. Passing it keeps this builder pure.
    """
    return Phase2JournalService._build_payroll_lines(
        ACCOUNT_IDS, run, employer_contribution)


def _debit_on(lines: list[dict], key: str) -> int:
    return sum(l["debit_paise"] for l in lines if l["account_id"] == ACCOUNT_IDS[key])


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
    lines = _build(run, employer_contribution=12000 + 3250)
    debit, credit = _sums(lines)
    assert debit == credit, f"payroll journal must balance: Dr {debit} != Cr {credit}"

    # Salaries and wages is GROSS — IT Act s.17(1), Schedule III Part II (a).
    assert _debit_on(lines, "salary_exp") == 100000
    # Contribution to provident and other funds is the employer's own — (b).
    # It used to be inside the line above, which made (b) nil on every note.
    assert _debit_on(lines, "employer_contribution") == 12000 + 3250
    # Together they are still the employer's total cost of employment, which is
    # what F13 was about and what the kernel balances against.
    assert debit == 100000 + 12000 + 3250 == 115250


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
    lines = _build(run, employer_contribution=0)
    debit, credit = _sums(lines)
    assert debit == credit == 50000
    account_ids = {l["account_id"] for l in lines}
    assert ACCOUNT_IDS["pf"] not in account_ids and ACCOUNT_IDS["esi"] not in account_ids
    # No contribution, no contribution line — a client with no PF or ESI keeps
    # exactly the entry it has always had and is never asked to hold a ledger
    # it will never post to.
    assert ACCOUNT_IDS["employer_contribution"] not in account_ids
    assert _debit_on(lines, "salary_exp") == 50000


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
    lines = _build(run, employer_contribution=60000)
    debit, credit = _sums(lines)
    assert debit == credit
    # employer PF is 60000 -> total cost = 1,000,000 + 60,000 = 1,060,000
    assert debit == 1060000
    assert _debit_on(lines, "salary_exp") == 1000000
    assert _debit_on(lines, "employer_contribution") == 60000


def test_identity_violation_fails_loud():
    """If `net` is reduced by a deduction with no matching credit leg, the
    payable credits no longer foot to gross + the employer contribution, and the
    journal must raise rather than post a wrong-but-balanced entry."""
    run = {
        "month": "2026-06",
        "total_gross_paise": 100000,
        "total_net_paise": 40000,   # artificially low vs gross with no offsetting credit
        "total_pf_paise": 0, "total_esi_paise": 0,
        "total_pt_paise": 0, "total_tds_paise": 0,
    }
    with pytest.raises(ValueError, match="identity violated"):
        _build(run)


def test_the_identity_is_now_exact_and_not_a_range():
    """Before PAY-25 the debit was DEFINED as sum(credits), so nothing could
    catch a run whose employer share was wrong — only a RANGE guard stood in
    for it, and any figure inside [gross, gross + pf + esi] passed. The two
    debits are now computed independently, so an employer share that does not
    agree with the credits is refused."""
    run = {
        "month": "2026-06",
        "total_gross_paise": 100000,
        "total_net_paise": 67250,
        "total_pf_paise": 24000, "total_esi_paise": 4000,
        "total_pt_paise": 20000, "total_tds_paise": 0,
    }
    # The true employer share is 12000 + 3250 = 15250, and it is accepted.
    assert _sums(_build(run, 15250))[0] == 115250
    # Anything else is refused — including a figure the OLD range guard allowed,
    # which is the whole point: 15249 sits inside [100000, 128000].
    for wrong in (15249, 15251, 0, 28000):
        with pytest.raises(ValueError, match="identity violated"):
            _build(run, wrong)


def test_a_run_with_no_stored_gross_keeps_the_old_single_debit_shape():
    """Older fixtures and the mock-mode doubles carry no `total_gross_paise`.
    Refusing them would break finalisation for a shape that used to work, so
    the salaries debit falls back to sum(credits) less the contribution —
    exactly what this entry did before PAY-25."""
    run = {
        "month": "2026-06", "total_net_paise": 67250,
        "total_pf_paise": 24000, "total_esi_paise": 4000,
        "total_pt_paise": 20000, "total_tds_paise": 0,
    }
    lines = _build(run, 0)
    debit, credit = _sums(lines)
    assert debit == credit == 115250
    assert _debit_on(lines, "salary_exp") == 115250


def test_every_line_is_pure_debit_or_credit():
    """Posting-kernel invariant: each line is a debit XOR a credit (never both)."""
    run = {
        "month": "2026-06", "total_gross_paise": 100000, "total_net_paise": 67250,
        "total_pf_paise": 24000, "total_esi_paise": 4000, "total_pt_paise": 20000,
        "total_tds_paise": 0,
    }
    for line in _build(run, employer_contribution=15250):
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
