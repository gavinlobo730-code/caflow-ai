"""
The §16(iii) professional-tax deduction in the §192 projection.

IT Act §16(iii) allows a deduction for "any sum paid by the assessee on account
of a tax on employments within the meaning of clause (2) of article 276 of the
Constitution". It is the YEAR's professional tax — what will actually be paid —
and only Karnataka and West Bengal of the four states this codebase models levy
the same amount in every month of it.

WHAT WAS WRONG, AND WHY IT SURVIVED A ROUND OF FIXES
    routers/payroll.py projected the deduction as `pt * months_in_year`, this
    month's professional tax times the months employed. An earlier pass changed
    it from `pt * 12` to `pt * months_in_year` while fixing a different defect
    in the same statement. For a full-year employee `months_in_year` IS 12, so
    the arithmetic is bit-for-bit what it was, on exactly the case this file
    measures. Reading the diff, or the commit, scores it closed. Only running it
    says otherwise, which is why every assertion below is a NUMBER.

Every figure here is arrived at from the state Act and the FY 2025-26 rates,
not read back off the implementation.
"""
import pytest

from routers.payroll import _annual_pt_paise, _compute_slip, _compute_pt

FY = "2025-26"


def _pt_year(state, gross_paise, *, run_month, months=12, gender=None,
             run_month_gross_paise=None):
    return _annual_pt_paise(
        monthly_gross_paise=gross_paise,
        run_month_gross_paise=run_month_gross_paise if run_month_gross_paise is not None else gross_paise,
        state=state, gender=gender, firm_slabs=None, on=None,
        run_month=run_month, months_employed_in_fy=months,
    )


# ── Tamil Nadu: a half-yearly levy, in two of the twelve months ──────────────

def test_tamil_nadu_is_two_half_years_not_twelve_months():
    """TN Municipal Laws (Second Amendment) Act 1998 — the levy is half-yearly,
    remitted by 30 Sep and 31 Mar, and _compute_pt_tn deducts the whole
    half-yearly amount in September and March and nil in the other ten months.

    At ₹50,000 a month the half-year is ₹3,00,000, which is the top band, so
    each half-year is ₹1,250 and the year is ₹2,500.
    """
    assert _compute_pt(50_000 * 100, "TN", month=9) == 1_250 * 100
    assert _compute_pt(50_000 * 100, "TN", month=3) == 1_250 * 100
    assert _compute_pt(50_000 * 100, "TN", month=10) == 0

    # THE REGRESSION. `pt * 12` in September was 1_250_00 * 12 = ₹15,000 — six
    # times the real liability — and ₹0 in each of the ten months either side.
    assert _pt_year("TN", 50_000 * 100, run_month=9) == 2_500 * 100
    assert _pt_year("TN", 50_000 * 100, run_month=3) == 2_500 * 100
    assert _pt_year("TN", 50_000 * 100, run_month=10) == 2_500 * 100
    # And it is the same figure in every month of the year, which is the whole
    # point: the employee's withholding must not move because of which month
    # the run happens to be in.
    assert len({_pt_year("TN", 50_000 * 100, run_month=m) for m in range(1, 13)}) == 1


def test_a_tamil_nadu_joiner_is_charged_only_the_half_year_they_were_here_for():
    """months_employed_in_fy counts inclusively from the joining month to March,
    so an October joiner's employed months are Oct-Mar — which contains the
    March half-year and not the September one."""
    assert _pt_year("TN", 50_000 * 100, run_month=10, months=6) == 1_250 * 100
    # A January joiner (Jan, Feb, Mar) still meets the March remittance.
    assert _pt_year("TN", 50_000 * 100, run_month=1, months=3) == 1_250 * 100
    # Somebody whose joining date falls after this year ends owes nothing.
    assert _pt_year("TN", 50_000 * 100, run_month=1, months=0) == 0


# ── Maharashtra: eleven months at ₹200 and February at ₹300 ─────────────────

def test_maharashtra_february_differential_totals_the_statutory_cap():
    """Maharashtra Act 1975, Schedule I: the >₹10,000 tier pays ₹300 in
    February and ₹200 in the other eleven months, so the year totals the ₹2,500
    cap Article 276(2) sets. `pt * 12` gave ₹3,600 in February and ₹2,400 in
    every other month — neither of which is ₹2,500."""
    assert _compute_pt(50_000 * 100, "MH", month=2) == 300_00
    assert _compute_pt(50_000 * 100, "MH", month=7) == 200_00
    assert _pt_year("MH", 50_000 * 100, run_month=2) == 2_500 * 100
    assert _pt_year("MH", 50_000 * 100, run_month=7) == 2_500 * 100
    assert len({_pt_year("MH", 50_000 * 100, run_month=m) for m in range(1, 13)}) == 1


def test_a_maharashtra_woman_under_the_ceiling_is_exempt_all_year():
    """W.e.f. 01-04-2023 a woman earning ≤ ₹25,000 a month pays nil, and nil
    twelve times is nil — the sum must not manufacture a February charge."""
    assert _pt_year("MH", 20_000 * 100, run_month=2, gender="female") == 0
    assert _pt_year("MH", 20_000 * 100, run_month=2, gender="male") == 200_00 * 11 + 300_00


# ── The flat-slab states are unchanged, which is the control ────────────────

@pytest.mark.parametrize("state,monthly", [("KA", 200_00), ("WB", 200_00)])
def test_a_flat_monthly_state_is_exactly_twelve_times_the_month(state, monthly):
    """Karnataka and West Bengal ARE plain monthly slabs, so summing the months
    has to give what multiplying gave. If this moved, the fix broke the two
    states that were right."""
    assert _compute_pt(50_000 * 100, state, month=7) == monthly
    assert _pt_year(state, 50_000 * 100, run_month=7) == monthly * 12
    assert _pt_year(state, 50_000 * 100, run_month=7, months=6) == monthly * 6


def test_an_unmodelled_state_still_deducts_nothing_and_projects_nothing():
    """An unset or unrecognised state returns 0 rather than falling back to any
    one state's rate; _statutory_gaps is what names it. Summing twelve zeroes
    must not change that."""
    assert _pt_year("DL", 50_000 * 100, run_month=7) == 0
    assert _pt_year(None, 50_000 * 100, run_month=7) == 0


# ── The run month's own gross, and the other eleven months' ─────────────────

def test_the_bonus_month_does_not_project_its_slab_across_the_year():
    """The run month is taken at its actual gross — the state Acts levy on
    "salary or wage" with none of the EPF/ESI exclusions — and every other
    month at the recurring gross. Projecting the bonus month's slab across the
    year would overstate a §16(iii) deduction, and overstating a deduction
    under-withholds, which §192(1) makes the employer answerable for."""
    # West Bengal: ₹9,000 recurring is nil; ₹9,000 + a ₹40,000 bonus is ₹200.
    assert _compute_pt(9_000 * 100, "WB", month=7) == 0
    assert _compute_pt(49_000 * 100, "WB", month=7) == 200_00
    year = _pt_year("WB", 9_000 * 100, run_month=7, run_month_gross_paise=49_000 * 100)
    assert year == 200_00, "one month at the bonus slab, eleven at nil"


# ── End to end, through the slip the payroll run actually produces ──────────

def _tn_employee():
    # ₹50,000 basic, no HRA/DA, so gross is ₹50,000 and the half-year is the
    # top TN band.
    return {"id": "e", "basic_paise": 50_000 * 100, "hra_percent": 0,
            "da_percent": 0, "pf_applicable": False, "esi_applicable": False,
            "pt_applicable": True, "pt_state": "TN"}


def test_the_withholding_no_longer_moves_with_the_month_of_the_run():
    """THE MEASUREMENT PAY-17 NAMED. An old-regime Tamil Nadu employee at
    ₹50,000: the §16(iii) deduction was ₹15,000 in September and ₹0 in the flat
    months, so the same employee's monthly TDS was ₹1,690 in September and
    ₹1,950 in the others — a difference with no cause in their pay.

    The deduction only bites on the OLD regime: §115BAC(2) allows §16(ia) and
    nothing else from section 16, so a new-regime employee gets no §16(iii) at
    all and their withholding was already flat.
    """
    from domain.payroll import declarations as D
    old = D.Declaration(employee_id="e", fy=FY, regime="old")

    tds = {m: _compute_slip(_tn_employee(), fy=FY, pt_month=m,
                            months_employed_in_fy=12,
                            declaration=old)["tds_paise"]
           for m in range(1, 13)}
    assert len(set(tds.values())) == 1, (
        f"the same pay withheld differently by month of run: {tds}")


def test_the_september_slip_still_deducts_the_half_year_from_the_payslip():
    """The projection changed; the DEDUCTION did not. TN professional tax is
    still taken in September and March and not in the other ten months — that
    is the remittance cycle, and §16(iii) allows what is actually paid."""
    sep = _compute_slip(_tn_employee(), fy=FY, pt_month=9, months_employed_in_fy=12)
    oct_ = _compute_slip(_tn_employee(), fy=FY, pt_month=10, months_employed_in_fy=12)
    assert sep["pt_paise"] == 1_250 * 100
    assert oct_["pt_paise"] == 0
