"""
The employer's 12% is two contributions, not one.

WHY THIS MATTERS BEYOND THE TRIAL BALANCE

_compute_pf used to return a flat {"employee": 12%, "employer": 12%}. The
employee's 12% is indeed all EPF, but EPS 1995 ¶3 diverts 8.33% of PF wages —
capped at 8.33% of the ₹15,000 ceiling, i.e. ₹1,250 — out of the EMPLOYER's
share to the pension fund, leaving the rest in EPF.

The EPFO's ECR return carries EPF wages, EPS wages, the EPF contribution, the
EPS contribution and the difference between them as separate columns per
member. A single employer figure cannot produce a valid return at all, so no
amount of downstream work could have built ECR filing on the old shape.

THE NUMBERS BELOW ARE THE PUBLISHED ONES

Every EPF table states ₹1,250 EPS and ₹550 EPF at the ceiling, not ₹1,249.50
and ₹550.50 — because EPFO rounds each member's contributions to the rupee.
8.33% of ₹15,000 is ₹1,249.50, so without that rounding the figures are wrong
by fifty paise in a way a CA would spot instantly and the portal would reject.
"""
from __future__ import annotations

import pytest

from routers.payroll import _compute_pf, _to_nearest_rupee
from domain.payroll.statutory import rates_for, RATES_BY_FY, LATEST_VERIFIED_FY

R = 100  # paise per rupee


# ── the published EPF table ──────────────────────────────────────────────────
# (PF wages ₹, employee ₹, employer total ₹, EPS ₹, EPF employer ₹)
PUBLISHED = [
    (5_000,   600,  600,   417, 183),
    (10_000, 1200, 1200,   833, 367),
    (15_000, 1800, 1800,  1250, 550),   # at the ceiling — the canonical row
    (20_000, 1800, 1800,  1250, 550),   # above it, everything stops rising
    (50_000, 1800, 1800,  1250, 550),
]


@pytest.mark.parametrize("wages,employee,employer,eps,epf", PUBLISHED)
def test_matches_the_published_epf_table(wages, employee, employer, eps, epf):
    got = _compute_pf(wages * R)
    assert got["employee"] == employee * R
    assert got["employer"] == employer * R
    assert got["employer_eps"] == eps * R
    assert got["employer_epf"] == epf * R


@pytest.mark.parametrize("wages", [0, 1, 4_999, 5_000, 12_345, 15_000, 15_001, 99_999])
def test_the_split_always_sums_to_the_employer_share(wages):
    """The invariant that makes the split safe to post: whatever the wage, EPS
    plus EPF is exactly the employer's 12% — no rupee is created or lost
    between the two halves."""
    got = _compute_pf(wages * R)
    assert got["employer_eps"] + got["employer_epf"] == got["employer"]


@pytest.mark.parametrize("wages", [0, 1, 15_000, 15_001, 99_999])
def test_no_contribution_is_ever_negative(wages):
    got = _compute_pf(wages * R)
    assert all(v >= 0 for v in got.values()), got


def test_eps_never_exceeds_the_employer_share():
    for wages in range(0, 60_001, 250):
        got = _compute_pf(wages * R)
        assert got["employer_eps"] <= got["employer"], wages


def test_the_eps_clamp_holds_when_the_two_ceilings_diverge(monkeypatch):
    """The clamp cannot be exercised by any real wage today, because the PF and
    EPS ceilings are both ₹15,000 — so 8.33% is always under 12%. It is there
    for the notification that moves one and not the other, and without this test
    deleting it would break nothing and pass.

    Here the EPS ceiling is pushed far above the PF ceiling, which is exactly
    the shape that would make an unclamped 8.33% of EPS wages exceed the
    employer's 12% of the capped PF wages and leave EPF negative — a negative
    contribution posted to the GL and sent on the ECR.
    """
    import dataclasses
    import routers.payroll as payroll

    base = rates_for("2026-27")
    skewed = dataclasses.replace(
        base, pf=dataclasses.replace(base.pf, eps_ceiling_paise=100_000 * R))
    monkeypatch.setattr(payroll, "payroll_rates_for", lambda fy=None: skewed)

    got = _compute_pf(100_000 * R)
    assert got["employer_epf"] >= 0, f"EPF went negative: {got}"
    assert got["employer_eps"] <= got["employer"]
    assert got["employer_eps"] + got["employer_epf"] == got["employer"]


def test_edli_and_admin_are_employer_costs_outside_the_twelve_percent():
    """Neither is deducted from anyone, and neither is part of the 12% — so
    they must not appear inside the employee or employer contribution."""
    got = _compute_pf(15_000 * R)
    assert got["edli"] == 75 * R
    assert got["admin"] == 75 * R
    assert got["employee"] + got["employer"] == (1800 + 1800) * R


# ── the rounding that produces ₹1,250 ────────────────────────────────────────

@pytest.mark.parametrize("paise,expected", [
    (0, 0), (49, 0), (50, 100), (99, 100), (100, 100),
    (124_950, 125_000),        # 8.33% of ₹15,000 -> ₹1,250, the whole point
    (55_050, 55_100),
])
def test_rounds_to_the_nearest_rupee_half_up(paise, expected):
    assert _to_nearest_rupee(paise) == expected


def test_the_ceiling_row_would_be_wrong_without_rounding():
    """Guards the reason rounding exists: unrounded, the ceiling row is
    ₹1,249.50 / ₹550.50, which is not what any EPF table or the ECR says."""
    got = _compute_pf(15_000 * R)
    assert got["employer_eps"] == 125_000, "EPS at the ceiling must be exactly ₹1,250"
    assert got["employer_eps"] % R == 0, "a contribution must not carry paise"
    assert got["employer_epf"] % R == 0


# ── the registry ─────────────────────────────────────────────────────────────

def test_rates_are_versioned_by_financial_year():
    """CLAUDE.md recorded these literals as a known gap — unversioned, and not
    printable by the coverage command every other registry answers to."""
    assert LATEST_VERIFIED_FY in RATES_BY_FY
    assert {"2025-26", "2026-27"} <= set(RATES_BY_FY)


def test_an_unknown_year_falls_back_rather_than_raising():
    """Same convention as every other registry, and the same hazard — which is
    why the annual sweep in CLAUDE.md is a checklist somebody works."""
    assert (rates_for("2099-00").pf.wage_ceiling_paise
            == rates_for(LATEST_VERIFIED_FY).pf.wage_ceiling_paise)


def test_the_statutory_ceilings_are_what_the_acts_say():
    r = rates_for("2026-27")
    assert r.pf.wage_ceiling_paise == 15_000 * R       # EPF & MP Act §6
    assert r.pf.eps_ceiling_paise == 15_000 * R        # EPS 1995 ¶3
    assert r.esi.wage_ceiling_paise == 21_000 * R      # ESI Act §2(9)
    assert r.pf.admin_minimum_paise == 500 * R         # per establishment
