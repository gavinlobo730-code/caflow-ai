"""Provident fund, pension and insurance wages follow the wage ceiling the Government notifies, by WAGE MONTH (POST-A-516).

WHAT WAS WRONG
    The three ceilings the product held (EPF wages, the employer's EPS wages, EDLI wages) were three copies of Rs 15,000 inside one
    financial-year entry, because the three old schemes each said so in their own text. The 2026 schemes (G.S.R. 525(E), 526(E) and
    527(E) of 29-06-2026) say no figure: each ties its contribution to the wage ceiling the Central Government notifies under section
    2(89) of the Code on Social Security, 2020. S.O. 5109(E) of 17-09-2026 (the e-Gazette's own copy, read on 19-11-2026) notified
    Rs 25,000 a month "with effect from the date of publication", so from 17-09-2026 every payroll run, ECR and ledger accrual that
    capped at Rs 15,000 under-deducted the employee and under-accrued the employer. A ceiling that changes on 17 September is not a
    fact about a financial year, so the year's entry could not hold it.

WHAT THE FIX DOES
    `domain/payroll/statutory.PF_WAGE_CEILINGS` is a dated table of notifications; `pf_rates_for_month` reads the ceiling for the
    wage month and `_compute_pf`, the ECR route and the Statutory Deductions projection all take it from there. The month the change
    falls INSIDE (September 2026) keeps the ceiling at its start and is NAMED in the run's statutory gaps, because no text read says
    which ceiling a month of that kind takes; a guess is exactly what the owner's standing instruction forbids.

WHAT THIS PROVES, AND THE NEGATIVE CONTROLS (each mutant was run and the tests named fail)
    * the registry's own figures                          — change either date or figure and `test_the_notifications_are_what_the_text_says`
                                                            fails
    * a month before the change keeps Rs 15,000, a month after takes Rs 25,000, and September keeps Rs 15,000 and says so
                                                          — make `wage_ceiling_for_month` read the END of the month and the straddle
                                                            tests fail
    * the whole contribution on the new ceiling, to the rupee: employee 3,000, EPS 2,083 (8.33% of 25,000 is 2,082.50, half up),
      EPF 917, EDLI 125, admin 125                        — make `_compute_pf` read `payroll_rates_for(fy).pf` and every October test
                                                            fails
    * the same through the REAL run, the real ECR and the real release-gap recompute
                                                          — take `month=` off `_pf_for_slip`'s call, or off `_build_run_ecr`'s, or
                                                            drop `_wage_ceiling_gap` from `_release_gaps` and the matching test fails
    * a property over every wage and every month of the year against an oracle written longhand here, apart from the registry
"""
from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import routers.payroll as pr
from domain.payroll import statutory
from domain.payroll.statutory import (
    PF_WAGE_CEILINGS,
    pf_rates_for_month,
    wage_ceiling_for_month,
    wage_ceiling_gap,
    wage_month_of,
)
from tests.e2e_harness import FakeDB, wire_e2e

# ── AN ORACLE WRITTEN APART FROM THE REGISTRY ────────────────────────────────
# Longhand, with literals, so a test of "the figure is right" cannot be passed by moving both sides.


def _oracle_ceiling(year: int, month: int) -> int:
    """Rs 25,000 for a wage month from October 2026; Rs 15,000 before it. September 2026 is the month 17-09-2026 falls inside and
    keeps the ceiling at its start."""
    return 25_000_00 if (year, month) >= (2026, 10) else 15_000_00


def _rupee(paise: int) -> int:
    return ((paise + 50) // 100) * 100


def _oracle_pf(wages: int, ceiling: int) -> dict:
    capped = min(wages, ceiling)
    employer = _rupee(capped * 1200 // 10000)
    eps = min(_rupee(min(wages, ceiling) * 833 // 10000), employer)
    return {
        "employee": _rupee(capped * 1200 // 10000),
        "employer": employer,
        "employer_eps": eps,
        "employer_epf": employer - eps,
        "edli": _rupee(min(wages, ceiling) * 50 // 10000),
        "admin": _rupee(capped * 50 // 10000),
    }


def _pf(wages: int, fy: str, month: int, **kw) -> dict:
    return pr._compute_pf(wages, fy, month=month, **kw)


# ═════════════════════════════════════════════════════════════════════════════
# THE REGISTRY
# ═════════════════════════════════════════════════════════════════════════════

def test_the_notifications_are_what_the_text_says():
    assert [(n.effective_from, n.ceiling_paise) for n in PF_WAGE_CEILINGS] == [
        (date(2014, 9, 1), 15_000_00),
        (date(2026, 9, 17), 25_000_00),
    ]
    old, new = PF_WAGE_CEILINGS
    # Only the figure whose primary text was read is graded verified: the Rs 15,000 is the old schemes' own text and the Code
    # notification that carried it (S.O. 2702(E)) is known from secondary reports only.
    assert new.verified is True and "5109(E)" in new.source and "17-09-2026" in new.source
    assert old.verified is False


@pytest.mark.parametrize("year, month, ceiling, straddles", [
    (2025, 4, 15_000_00, False),
    (2026, 2, 15_000_00, False),
    (2026, 8, 15_000_00, False),
    (2026, 9, 15_000_00, True),        # 17-09-2026 falls inside: the ceiling at the START of the month, and the month is named
    (2026, 10, 25_000_00, False),
    (2026, 12, 25_000_00, False),
    (2027, 3, 25_000_00, False),
])
def test_a_wage_month_takes_the_ceiling_notified_for_it(year, month, ceiling, straddles):
    got = wage_ceiling_for_month(year, month)
    assert got.ceiling_paise == ceiling
    assert got.straddles is straddles
    assert got.ceiling_paise == _oracle_ceiling(year, month)


def test_the_month_the_change_falls_inside_is_named_and_not_settled():
    got = wage_ceiling_for_month(2026, 9)
    assert got.effective_from == date(2026, 9, 17)
    for needle in ("S.O. 5109(E)", "17-09-2026", "Rs 25,000", "Rs 15,000", "confirm"):
        assert needle in got.note, needle
    assert wage_ceiling_for_month(2026, 8).note is None
    assert wage_ceiling_for_month(2026, 10).note is None


def test_the_financial_year_label_and_month_number_make_the_calendar_month():
    assert wage_month_of("2026-27", 4) == (2026, 4)
    assert wage_month_of("2026-27", 12) == (2026, 12)
    assert wage_month_of("2026-27", 1) == (2027, 1)
    assert wage_month_of("2026-27", 3) == (2027, 3)
    # unknown stays unknown: no month is invented for a caller that did not say
    assert wage_month_of("2026-27", None) is None
    assert wage_month_of(None, 5) is None
    assert wage_month_of("2026-27", 0) is None
    assert wage_month_of("2026-27", 13) is None
    assert wage_month_of("garbage", 5) is None


def test_the_three_ceilings_move_together_because_the_schemes_tie_them_to_one_notification():
    for fy, month in (("2026-27", 8), ("2026-27", 10), ("2026-27", 3)):
        r = pf_rates_for_month(fy, month)
        assert r.wage_ceiling_paise == r.eps_ceiling_paise == r.edli_ceiling_paise
    assert pf_rates_for_month("2026-27", 10).wage_ceiling_paise == 25_000_00
    assert pf_rates_for_month("2026-27", 8).wage_ceiling_paise == 15_000_00


def test_a_caller_with_no_month_gets_the_years_own_figures_as_before():
    base = statutory.rates_for("2026-27").pf
    assert pf_rates_for_month("2026-27", None) == base
    assert base.wage_ceiling_paise == 15_000_00        # 1 April 2026 is before the notification
    assert pf_rates_for_month("2025-26", None).wage_ceiling_paise == 15_000_00
    # the rates did not move with the ceiling
    r = pf_rates_for_month("2026-27", 10)
    assert (r.employee_rate_bps, r.employer_rate_bps, r.eps_rate_bps, r.edli_rate_bps, r.admin_rate_bps) == (
        1200, 1200, 833, 50, 50)


def test_the_gap_sentence_is_the_registrys_and_only_for_the_straddling_month():
    assert wage_ceiling_gap("2026-27", 6) is None
    assert wage_ceiling_gap("2026-27", 8) is None
    assert wage_ceiling_gap("2026-27", 9) == wage_ceiling_for_month(2026, 9).note
    assert wage_ceiling_gap("2026-27", 10) is None
    assert wage_ceiling_gap("2026-27", None) is None
    assert wage_ceiling_gap(None, 9) is None


# ═════════════════════════════════════════════════════════════════════════════
# THE CONTRIBUTION, TO THE RUPEE
# ═════════════════════════════════════════════════════════════════════════════

def test_from_october_2026_a_member_above_the_ceiling_is_computed_on_rs_25000():
    pf = _pf(40_000_00, "2026-27", 10)
    assert pf["employee"] == 3_000_00
    assert pf["employer"] == 3_000_00
    assert pf["employer_eps"] == 2_083_00          # 8.33% of 25,000 is 2,082.50, half up
    assert pf["employer_epf"] == 917_00
    assert pf["edli"] == 125_00
    assert pf["admin"] == 125_00


def test_up_to_august_2026_the_same_member_is_still_computed_on_rs_15000():
    pf = _pf(40_000_00, "2026-27", 8)
    assert pf["employee"] == 1_800_00
    assert pf["employer"] == 1_800_00
    assert pf["employer_eps"] == 1_250_00          # 8.33% of 15,000 is 1,249.50, half up
    assert pf["employer_epf"] == 550_00
    assert pf["edli"] == 75_00
    assert pf["admin"] == 75_00


def test_september_2026_keeps_rs_15000_until_somebody_with_the_text_says_otherwise():
    assert _pf(40_000_00, "2026-27", 9) == _pf(40_000_00, "2026-27", 8)


def test_a_wage_between_the_two_ceilings_is_computed_on_itself_only_from_october():
    # Rs 20,000: above the old ceiling and below the new one
    sept = _pf(20_000_00, "2026-27", 9)
    octo = _pf(20_000_00, "2026-27", 10)
    assert sept["employee"] == 1_800_00
    assert octo["employee"] == 2_400_00
    assert octo["employer_eps"] == 1_666_00        # 8.33% of 20,000
    assert octo["employer_epf"] == 734_00
    assert octo["edli"] == 100_00
    assert octo["admin"] == 100_00


@pytest.mark.parametrize("wages, employee", [
    (24_999_00, _rupee(24_999_00 * 1200 // 10000)),
    (25_000_00, 3_000_00),
    (25_001_00, 3_000_00),                         # the cap bites one rupee above the new ceiling
])
def test_the_boundary_of_the_new_ceiling(wages, employee):
    assert _pf(wages, "2026-27", 11)["employee"] == employee


def test_a_wage_below_both_ceilings_does_not_move():
    for month in (8, 9, 10, 11):
        assert _pf(12_000_00, "2026-27", month) == _pf(12_000_00, "2026-27", 8)


def test_an_election_to_contribute_on_actual_wages_still_leaves_eps_and_edli_at_the_ceiling():
    pf = _pf(40_000_00, "2026-27", 10, on_actual_wages=True)
    assert pf["employee"] == 4_800_00                        # 12% of the whole wage
    assert pf["employer_eps"] == 2_083_00                    # EPS never follows the election
    assert pf["edli"] == 125_00                              # nor does EDLI
    assert pf["admin"] == 200_00                             # the admin charge follows the PF wage


@settings(max_examples=250, deadline=None)
@given(wages=st.integers(min_value=0, max_value=2_000_000_00),
       month=st.integers(min_value=1, max_value=12),
       fy=st.sampled_from(["2025-26", "2026-27"]),
       eps_eligible=st.booleans())
def test_every_wage_in_every_month_agrees_with_the_longhand_oracle(wages, month, fy, eps_eligible):
    year, cal_month = wage_month_of(fy, month)
    expected = _oracle_pf(wages, _oracle_ceiling(year, cal_month))
    if not eps_eligible:
        expected["employer_epf"] = expected["employer"]
        expected["employer_eps"] = 0
    got = _pf(wages, fy, month, eps_eligible=eps_eligible)
    assert {k: got[k] for k in expected} == expected


# ═════════════════════════════════════════════════════════════════════════════
# THE REAL SLIP, RUN, RELEASE CHECK AND ECR
# ═════════════════════════════════════════════════════════════════════════════

FIRM = "FIRM-PF516"
CALLER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1",
          "email": "ca@f.test", "role": "Partner"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [pr])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2026-04-01"})
    d.seed("client_payroll_settings", {"id": "cps-1", "firm_id": FIRM, "client_id": "CLI",
                                       "payroll_enabled": True})
    return d


def _seed_employee(db, emp_id: str, name: str, basic: int, **kw):
    row = {"id": emp_id, "firm_id": FIRM, "client_id": "CLI", "name": name,
           "uan": "1002003004" + emp_id[-2:], "basic_paise": basic,
           "hra_percent": 0.0, "da_percent": 0.0, "other_allowances_paise": 0,
           "lta_paise": 0, "medical_paise": 0, "special_allowance_paise": 0,
           "pf_applicable": True, "eps_eligible": True, "esi_applicable": False,
           "pt_applicable": False, "is_active": True, "status": "active"}
    row.update(kw)
    return db.seed("payroll_employees", row)


def _roster(db):
    _seed_employee(db, "e-01", "Forty Thousand", 40_000_00)
    _seed_employee(db, "e-02", "Twenty Thousand", 20_000_00)
    _seed_employee(db, "e-03", "Twelve Thousand", 12_000_00)


def _run(db, month: str) -> dict:
    out = pr.create_run(pr.PayrollRunIn(client_id="CLI", month=month), CALLER)
    assert out["success"] is True
    return out["data"]


def _slips(db, run_id: str) -> dict:
    return {s["employee_id"]: s for s in db.rows("payroll_slips") if s["run_id"] == run_id}


def test_a_real_run_for_october_computes_every_member_on_the_new_ceiling(db):
    _roster(db)
    slips = _slips(db, _run(db, "2026-10")["id"])
    assert slips["e-01"]["pf_employee_paise"] == 3_000_00
    assert slips["e-01"]["pf_employer_eps_paise"] == 2_083_00
    assert slips["e-01"]["pf_employer_epf_paise"] == 917_00
    assert slips["e-01"]["edli_paise"] == 125_00
    assert slips["e-01"]["pf_admin_paise"] == 125_00
    assert slips["e-02"]["pf_employee_paise"] == 2_400_00
    assert slips["e-03"]["pf_employee_paise"] == 1_440_00        # Rs 12,000 is below both ceilings


def test_a_real_run_for_august_is_what_it_always_was(db):
    _roster(db)
    slips = _slips(db, _run(db, "2026-08")["id"])
    assert slips["e-01"]["pf_employee_paise"] == 1_800_00
    assert slips["e-02"]["pf_employee_paise"] == 1_800_00
    assert slips["e-03"]["pf_employee_paise"] == 1_440_00


def test_a_real_run_for_september_keeps_rs_15000_and_names_the_month(db):
    _roster(db)
    out = _run(db, "2026-09")
    slips = _slips(db, out["id"])
    assert slips["e-01"]["pf_employee_paise"] == 1_800_00
    named = [g for g in out["statutory_gaps"] if "S.O. 5109(E)" in g]
    assert len(named) == 1 and "2026-09" in named[0] and "17-09-2026" in named[0]


@pytest.mark.parametrize("month", ["2026-08", "2026-10", "2026-12", "2027-03"])
def test_a_month_the_change_does_not_fall_inside_adds_no_gap(db, month):
    _roster(db)
    out = _run(db, month)
    assert not [g for g in out["statutory_gaps"] if "S.O. 5109(E)" in g]


def test_releasing_a_september_run_asks_the_same_question_again(db):
    """The gap a CA saw on the draft is the gap asked again at release: finalising a September run needs the typed reason."""
    _roster(db)
    run_id = _run(db, "2026-09")["id"]
    run = next(r for r in db.rows("payroll_runs") if r["id"] == run_id)
    assert [g for g in pr._release_gaps(db, FIRM, run) if "S.O. 5109(E)" in g]


def test_releasing_an_october_run_carries_no_ceiling_gap(db):
    _roster(db)
    run_id = _run(db, "2026-10")["id"]
    run = next(r for r in db.rows("payroll_runs") if r["id"] == run_id)
    assert not [g for g in pr._release_gaps(db, FIRM, run) if "S.O. 5109(E)" in g]


def _finalise_and_build(db, run_id):
    for row in db.rows("payroll_runs"):
        if row["id"] == run_id:
            row["status"] = "finalized"
    return pr._build_run_ecr(db, CALLER, run_id)


def test_the_ecr_of_an_october_run_declares_wages_up_to_rs_25000(db):
    _roster(db)
    _run_row, _month, f = _finalise_and_build(db, _run(db, "2026-10")["id"])
    assert f.problems == []
    by_name = {m.name: m for m in f.members}
    forty = by_name["FORTY THOUSAND"]
    assert (forty.epf_wages, forty.eps_wages, forty.edli_wages) == (25_000, 25_000, 25_000)
    assert by_name["TWENTY THOUSAND"].epf_wages == 20_000
    assert by_name["TWELVE THOUSAND"].epf_wages == 12_000


def test_the_ecr_of_an_august_run_declares_wages_up_to_rs_15000(db):
    _roster(db)
    _run_row, _month, f = _finalise_and_build(db, _run(db, "2026-08")["id"])
    assert f.problems == []
    by_name = {m.name: m for m in f.members}
    forty = by_name["FORTY THOUSAND"]
    assert (forty.epf_wages, forty.eps_wages, forty.edli_wages) == (15_000, 15_000, 15_000)


def test_the_statutory_deductions_projection_agrees_with_the_run_for_the_month(db):
    _roster(db)
    for month, expected in (("2026-08", 1_800_00), ("2026-10", 3_000_00)):
        resp = pr.statutory_position(client_id="CLI", month=month, current_user=CALLER)
        assert resp["success"] is True
        rows = {r["employee_id"]: r for r in resp["data"]["rows"]}
        assert rows["e-01"]["pf_employee_paise"] == expected, month
