"""
One-time and variable earnings, and the four things folding them into a monthly
rate got wrong.

WHAT WAS MISSING
    Every earning a run could compute was a MONTHLY RATE out of the employee
    master or a salary revision. There was nowhere to put an amount decided
    once, so the only way to pay a Diwali bonus was to inflate
    special_allowance_paise for one month.

THE FOUR THINGS THAT GETS WRONG
    1. It is PRORATED by loss of pay. A decided figure is not a rate; nobody
       earns four-fifths of a bonus by taking a day off.
    2. It enters PF WAGES. EPF Act s.2(b) expressly excludes "any bonus,
       commission or any other similar allowance" from basic wages.
    3. It enters ESI WAGES. ESI Act s.2(22) includes additional remuneration
       only where paid "at intervals not exceeding two months" — an INTERVAL
       test, so an annual bonus is out and a monthly incentive is in. It matters
       twice: the same figure is what the wage ceiling is tested against, so
       folding a bonus in throws somebody out of ESI for a month.
    4. s.192 PROJECTS it. `gross * months_left` over eleven remaining months
       turns a fifty-thousand-rupee bonus into six lakh of estimated income.

AND ONE LIVE BUG FOUND ALONGSIDE
    _tds_already_deducted_this_fy selected "employee_id, tds_paise" and its
    accumulator read sl.get("gross_paise") — always None. So
    gross_already_paid_paise was ZERO in every run ever computed, and the s.192
    projection estimated the year as this month's pay times the months still to
    come, ignoring every month already paid.

NEGATIVE CONTROLS
    Revert routers/payroll.py to HEAD~ and the run-level tests fail: the bonus
    is prorated, enters PF and ESI wages, and is projected.
    Restore the narrowed select in _tds_already_deducted_this_fy and
    test_a_month_already_paid_counts_towards_the_projection fails.
    Point _SALARY_COMPONENTS at one_time_earnings_paise instead of
    one_time_taxable_paise and test_a_reimbursement_is_paid_but_is_not_salary
    fails.
"""
from __future__ import annotations

import pytest

from domain.payroll import one_time_earnings as ote


# ─────────────────────────────────────────────────────────────────────────────
#  The three statutory questions, answered per kind
# ─────────────────────────────────────────────────────────────────────────────

def test_a_bonus_is_not_pf_wages():
    """EPF Act s.2(b) excludes bonus from basic wages, in those words."""
    d = ote.statutory_defaults("bonus")
    assert d.pf_wages is False
    assert "s.2(b)" in d.reason


def test_a_commission_is_not_pf_wages_either():
    """The same words exclude commission."""
    assert ote.statutory_defaults("commission").pf_wages is False


def test_arrears_are_pf_wages():
    """Arrears are basic and DA paid late, not an allowance, so s.2(b)'s
    exclusion does not reach them and EPFO takes contributions in the month of
    payment."""
    d = ote.statutory_defaults("arrears")
    assert d.pf_wages is True
    assert "paid late" in d.reason


@pytest.mark.parametrize("interval,expected", [
    (1, True),    # monthly — within two months
    (2, True),    # bi-monthly — the boundary, inclusive
    (3, False),   # quarterly — outside
    (12, False),  # annual
    (None, False),  # paid once, not at an interval
])
def test_esi_wages_turn_on_the_interval_and_not_the_name(interval, expected):
    """ESI Act s.2(22): additional remuneration "paid at intervals not exceeding
    two months". The SAME kind answers differently at different intervals, which
    is why the answer cannot be a lookup on the kind alone."""
    assert ote.statutory_defaults("incentive", interval).esi_wages is expected


def test_the_two_month_line_is_inclusive():
    """"not exceeding two months" includes two."""
    assert ote.statutory_defaults("incentive", 2).esi_wages is True
    assert ote.statutory_defaults("incentive", 3).esi_wages is False


def test_everything_is_salary_except_a_reimbursement():
    for kind in ("incentive", "bonus", "ex_gratia", "arrears", "commission", "other"):
        assert ote.statutory_defaults(kind).taxable is True, kind
    r = ote.statutory_defaults("reimbursement")
    assert r.taxable is False
    assert r.pf_wages is False and r.esi_wages is False


def test_an_unknown_kind_is_refused_rather_than_defaulted():
    with pytest.raises(ValueError):
        ote.statutory_defaults("diwali_ka_paisa")


# ─────────────────────────────────────────────────────────────────────────────
#  Bundling — four bases, not one
# ─────────────────────────────────────────────────────────────────────────────

def _row(amount, pf=False, esi=False, taxable=True, kind="bonus", **kw):
    return {"kind": kind, "amount_paise": amount, "pf_wages": pf,
            "esi_wages": esi, "taxable": taxable, **kw}


def test_the_four_bases_are_summed_separately():
    b = ote.bundle([
        _row(5_000_000, kind="bonus"),                              # neither
        _row(1_000_000, kind="arrears", pf=True, esi=True),          # both
        _row(200_000, kind="incentive", esi=True),                   # ESI only
    ])
    assert b.total_paise == 6_200_000
    assert b.pf_wages_paise == 1_000_000
    assert b.esi_wages_paise == 1_200_000
    assert b.taxable_paise == 6_200_000


def test_the_bundle_reads_the_row_and_never_re_derives_from_the_kind():
    """A CA may know something the default cannot. The row is the record of what
    was decided, which is what makes a slip still readable in March."""
    b = ote.bundle([_row(1_000_000, kind="bonus", pf=True)])
    assert b.pf_wages_paise == 1_000_000


def test_a_negative_row_reduces_the_same_bases_it_inflated():
    """A recovery of an earlier overpayment is not a deduction — it is the same
    earning, undone."""
    b = ote.bundle([_row(1_000_000, kind="arrears", pf=True, esi=True),
                    _row(-400_000, kind="arrears", pf=True, esi=True)])
    assert b.total_paise == 600_000
    assert b.pf_wages_paise == 600_000
    assert b.esi_wages_paise == 600_000


def test_an_empty_bundle_is_falsy_and_all_zero():
    assert not ote.bundle([])
    assert ote.EMPTY.total_paise == 0


def test_rows_are_grouped_by_employee_in_one_pass():
    by = ote.bundles_by_employee([
        {**_row(100_000), "employee_id": "e-1"},
        {**_row(250_000), "employee_id": "e-1"},
        {**_row(700_000), "employee_id": "e-2"},
    ])
    assert by["e-1"].total_paise == 350_000
    assert by["e-2"].total_paise == 700_000


# ─────────────────────────────────────────────────────────────────────────────
#  Validation — every problem at once
# ─────────────────────────────────────────────────────────────────────────────

def test_a_zero_amount_is_refused_not_ignored():
    """A zero-rupee earning is a row somebody started and did not finish."""
    p = ote.validate(_row(0))
    assert any("zero" in m.lower() for m in p)


def test_an_unknown_kind_is_named_with_the_kinds_that_exist():
    p = ote.validate(_row(100_000, kind="tip"))
    assert any("incentive" in m and "bonus" in m for m in p)


def test_an_unanswered_statutory_question_is_refused():
    row = _row(100_000)
    row["esi_wages"] = None
    p = ote.validate(row)
    assert any("esi_wages" in m and "s.2(22)" in m for m in p)


def test_an_interval_outside_one_to_twelve_is_refused():
    assert ote.validate(_row(100_000, payment_interval_months=0))
    assert ote.validate(_row(100_000, payment_interval_months=13))
    assert ote.validate(_row(100_000, payment_interval_months=None)) == []


def test_every_problem_is_reported_at_once():
    """Whole-row, not first-failure — a CA fixing a form wants the list."""
    row = {"kind": "tip", "amount_paise": 0, "pf_wages": None,
           "esi_wages": None, "taxable": None, "payment_interval_months": 99}
    assert len(ote.validate(row)) >= 5


def test_a_saved_row_that_disagrees_with_the_statute_says_so():
    """Not a refusal — visible. These booleans are what the ECR is built from."""
    note = ote.divergence_note(_row(1_000_000, kind="bonus", pf=True))
    assert note and "PF wages" in note


def test_a_row_that_agrees_says_nothing():
    assert ote.divergence_note(_row(1_000_000, kind="bonus")) is None


# ═════════════════════════════════════════════════════════════════════════════
#  Through the real run — FakeDB, not the mock branch
# ═════════════════════════════════════════════════════════════════════════════

import routers.payroll as payroll_mod  # noqa: E402
from domain.payroll.annexure2 import _SALARY_COMPONENTS  # noqa: E402
from tests.e2e_harness import FakeDB, wire_e2e  # noqa: E402

FIRM = "FIRM-OTE"
CALLER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "a-1",
          "email": "ca@f.test", "role": "Partner"}

BASIC = 3_000_000          # ₹30,000
BONUS = 5_000_000          # ₹50,000


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM,
                       "financial_year_start": "2026-04-01"})
    d.seed("payroll_employees", {
        "id": "e-1", "firm_id": FIRM, "client_id": "CLI", "name": "Asha",
        "basic_paise": BASIC, "hra_percent": 0.0, "da_percent": 0.0,
        "lta_paise": 0, "medical_paise": 0, "special_allowance_paise": 0,
        "other_allowances_paise": 0,
        "pf_applicable": True, "eps_eligible": True,
        "esi_applicable": True, "pt_applicable": False,
        "joining_date": "2020-04-01", "is_active": True, "status": "active",
    })
    # Attendance ENTERED, so nothing here is testing the not-entered path.
    d.seed("attendance", {"id": "a-1", "firm_id": FIRM, "employee_id": "e-1",
                          "year": 2026, "month": 8, "working_days": 26,
                          "days_present": 26, "casual_leaves": 0,
                          "sick_leaves": 0, "earned_leaves": 0, "lop_days": 0,
                          "entered_by": "u-1", "entered_at": "2026-08-31T00:00:00Z"})
    return d


def _earning(d, **kw):
    row = {"id": kw.pop("id", "ote-1"), "firm_id": FIRM, "client_id": "CLI",
           "employee_id": "e-1", "month": "2026-08-01", "kind": "bonus",
           "label": None, "amount_paise": BONUS, "pf_wages": False,
           "esi_wages": False, "taxable": True,
           "payment_interval_months": None}
    row.update(kw)
    d.seed("payroll_one_time_earnings", row)


def _run(d, month="2026-08"):
    from models.payroll import PayrollRunIn
    payroll_mod.create_run(PayrollRunIn(client_id="CLI", month=month), CALLER)
    run = [r for r in d.rows("payroll_runs") if r["month"] == month][0]
    slip = [s for s in d.rows("payroll_slips") if s["run_id"] == run["id"]][0]
    return run, slip


def test_a_bonus_reaches_gross(db):
    _earning(db)
    _, slip = _run(db)
    assert slip["one_time_earnings_paise"] == BONUS
    assert slip["gross_paise"] == BASIC + BONUS


def test_a_bonus_is_not_prorated_by_loss_of_pay(db):
    """The whole point of the type. Basic loses four days; the bonus does not."""
    for r in db.rows("attendance"):
        r["days_present"], r["lop_days"] = 22, 4
    _earning(db)
    _, slip = _run(db)
    assert slip["basic_paise"] == BASIC * 22 // 26, "basic must still prorate"
    assert slip["one_time_earnings_paise"] == BONUS, \
        "a decided amount is not a rate and must not be scaled by attendance"


def test_a_bonus_does_not_enter_pf_wages(db):
    """EPF Act s.2(b). PF must be identical with and without the bonus."""
    _, without = _run(db)
    pf_without = without["pf_employee_paise"]

    for s in list(db.rows("payroll_slips")):
        db.rows("payroll_slips").remove(s)
    for r in list(db.rows("payroll_runs")):
        db.rows("payroll_runs").remove(r)
    _earning(db)
    _, with_bonus = _run(db)
    assert with_bonus["pf_employee_paise"] == pf_without
    assert with_bonus["one_time_pf_wages_paise"] == 0


def test_arrears_of_basic_do_enter_pf_wages(db):
    """The one kind s.2(b)'s exclusion does not reach.

    Basic dropped to ₹10,000 so the ₹15,000 statutory ceiling does not bind and
    the arithmetic is visible: at the seeded ₹30,000 the contribution is the
    ceiling's ₹1,800 either way and the test would prove nothing.
    """
    for e in db.rows("payroll_employees"):
        e["basic_paise"] = 1_000_000                  # ₹10,000
    _earning(db, kind="arrears", amount_paise=200_000, pf_wages=True)
    _, slip = _run(db)
    assert slip["one_time_pf_wages_paise"] == 200_000
    # 12% of (basic + arrears), not of basic alone.
    assert slip["pf_employee_paise"] == (1_000_000 + 200_000) * 12 // 100


def test_an_annual_bonus_does_not_throw_an_employee_out_of_esi(db):
    """ESI Act s.2(22) and the wage ceiling read the SAME figure. ₹30,000 basic
    is already over the ₹21,000 ceiling here, so use a low-paid employee: the
    point is that the bonus must not move the base at all."""
    for e in db.rows("payroll_employees"):
        e["basic_paise"] = 1_500_000        # ₹15,000 — inside the ceiling
    _earning(db)                             # ₹50,000 bonus, not ESI wages
    _, slip = _run(db)
    assert slip["one_time_esi_wages_paise"] == 0
    assert slip["esi_employee_paise"] > 0, \
        "the bonus must not push this employee over the ESI wage ceiling"


def test_a_monthly_incentive_does_enter_esi_wages(db):
    for e in db.rows("payroll_employees"):
        e["basic_paise"] = 1_500_000
    _earning(db, kind="incentive", amount_paise=100_000,
             esi_wages=True, payment_interval_months=1)
    _, slip = _run(db)
    assert slip["one_time_esi_wages_paise"] == 100_000


def test_a_bonus_is_added_to_the_projection_once_and_not_projected(db):
    """s.192(1) estimates the year. A bonus paid once is income once.

    Without the fix `gross * months_left` multiplied the bonus by every month
    still to come. Asserted as: TDS with the bonus must be strictly less than
    TDS computed on twelve bonuses' worth of extra income would be — and the
    cleanest form of that is that the projected annual figure the run uses rises
    by exactly the bonus.
    """
    # ₹1,50,000 a month, so the year is ₹18 lakh and there is real tax to move.
    # At the seeded ₹30,000 the s.87A rebate takes the liability to nil with and
    # without the bonus, and the assertion would hold vacuously.
    for e in db.rows("payroll_employees"):
        e["basic_paise"] = 15_000_000

    _, without = _run(db)
    tds_without = without["tds_paise"]
    assert tds_without > 0, "the fixture must have real tax for this to mean anything"

    for s in list(db.rows("payroll_slips")):
        db.rows("payroll_slips").remove(s)
    for r in list(db.rows("payroll_runs")):
        db.rows("payroll_runs").remove(r)
    _earning(db)
    _, with_bonus = _run(db)

    # The month's withholding rises because the year's estimate rose by ONE
    # bonus. Grossed back up over the twelve months it is spread across, the
    # year's extra tax must be a fraction of the bonus — at the top slab, about
    # a third of it. Projected forward instead, the estimate would rise by
    # twelve bonuses and the extra tax would exceed the bonus itself.
    extra_tax = (with_bonus["tds_paise"] - tds_without) * 12
    assert 0 < extra_tax < BONUS, (
        f"extra annual tax {extra_tax} on a {BONUS} bonus — a projected bonus "
        "taxes twelve times the income actually paid")


def test_a_reimbursement_is_paid_but_is_not_salary(db):
    """In gross and in net, out of s.17(1). The first component the annexure's
    'summed from components, not gross' comment was written for."""
    _earning(db, kind="reimbursement", amount_paise=300_000, taxable=False)
    _, slip = _run(db)
    assert slip["one_time_earnings_paise"] == 300_000
    assert slip["gross_paise"] == BASIC + 300_000
    assert slip["one_time_taxable_paise"] == 0
    assert "one_time_taxable_paise" in _SALARY_COMPONENTS
    assert "one_time_earnings_paise" not in _SALARY_COMPONENTS


def test_the_run_total_says_how_much_was_not_the_salary_bill(db):
    _earning(db)
    run, _ = _run(db)
    row = [r for r in db.rows("payroll_runs") if r["id"] == run["id"]][0]
    assert row["total_one_time_paise"] == BONUS
    assert row["total_gross_paise"] == BASIC + BONUS


# ═════════════════════════════════════════════════════════════════════════════
#  The two statutory files read the SAME bases the run deducted on
# ═════════════════════════════════════════════════════════════════════════════
#  Both used to recompute the wage figure from the slip's components — the ECR
#  as basic + DA, the ESIC return as gross — which was right until a one-time
#  earning could move either base. Left alone, the ECR would file EPF wages
#  LOWER than the 12% remitted against them, and the ESIC return would file
#  wages HIGHER than the contribution deducted from them. Both reconcile on the
#  portal, and both would be rejected.

def test_the_ecr_includes_arrears_in_epf_wages(db_free=None):
    from domain.payroll.ecr import build_ecr
    slips = [{"employee_id": "e-1", "basic_paise": 1_000_000, "da_paise": 0,
              "gross_paise": 1_200_000, "one_time_pf_wages_paise": 200_000,
              "pf_employee_paise": 144_000, "pf_employer_paise": 144_000,
              "pf_employer_eps_paise": 99_960, "pf_employer_epf_paise": 44_040,
              "lop_days": 0}]
    out = build_ecr(slips=slips,
                    employees_by_id={"e-1": {"id": "e-1", "name": "Asha",
                                             "uan": "100200300400",
                                             "eps_eligible": True}},
                    days_in_month=31, wage_ceiling_paise=1_500_000)
    assert out.members, out.problems
    # ₹10,000 basic + ₹2,000 arrears of basic — not ₹10,000.
    assert out.members[0].epf_wages == 12_000


def test_the_esic_return_leaves_an_annual_bonus_out_of_wages(db_free=None):
    from domain.payroll.esic import build_esic_return
    slips = [{"employee_id": "e-1", "gross_paise": 6_500_000,
              "one_time_earnings_paise": 5_000_000,
              "one_time_esi_wages_paise": 0,
              "esi_employee_paise": 11_250, "lop_days": 0}]
    out = build_esic_return(slips=slips,
                            employees_by_id={"e-1": {"id": "e-1", "name": "Asha",
                                                     "esi_number": "1234567890"}},
                            days_in_month=31)
    assert out.members, out.problems
    # ₹15,000 of wages and a ₹50,000 bonus that ESI Act s.2(22) does not reach.
    assert out.members[0].wages_rupees == 15_000


def test_the_esic_return_keeps_a_monthly_incentive_in_wages(db_free=None):
    from domain.payroll.esic import build_esic_return
    slips = [{"employee_id": "e-1", "gross_paise": 1_600_000,
              "one_time_earnings_paise": 100_000,
              "one_time_esi_wages_paise": 100_000,
              "esi_employee_paise": 12_000, "lop_days": 0}]
    out = build_esic_return(slips=slips,
                            employees_by_id={"e-1": {"id": "e-1", "name": "Asha",
                                                     "esi_number": "1234567890"}},
                            days_in_month=31)
    assert out.members[0].wages_rupees == 16_000


def test_a_month_already_paid_counts_towards_the_projection(db):
    """The live bug: _tds_already_deducted_this_fy selected employee_id and
    tds_paise, and its accumulator read gross_paise off rows that never carried
    it. Every run's gross_already_paid_paise was therefore zero.

    Asserted through the public helper rather than a private one, so it fails on
    the narrowed select and not on a rename.
    """
    _run(db, "2026-08")
    ytd = payroll_mod._tds_already_deducted_this_fy(
        db, FIRM, "CLI", "2026-09", "2026-27")
    _tds, months, gross = ytd["e-1"]
    assert months == 1
    assert gross == BASIC, \
        "August's gross must be visible to September's s.192 projection"
