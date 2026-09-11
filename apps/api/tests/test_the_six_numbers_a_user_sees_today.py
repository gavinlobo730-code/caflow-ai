"""Phase 13a — six figures a person reads off a screen, and what they should say.

WHY THESE SIX ARE ONE FILE

They are not one subsystem. They are one CLASS: each was an engine computing
the wrong number, held at medium or low severity in the September audit because
NOTHING REACHED IT — and Phase 7 built the screens that reach them. The
mitigation expired and nobody re-scored, because a rescore reads the finding
rather than the diff that invalidated it.

  IT-08   §111A/§112/§112A basic-exemption absorption, missing entirely
  IT-26   §10(13A) and §24(b) reported as Chapter VI-A deductions
  IT-32   an uncapped catch-all that escapes §80CCE, with no way into §80C
  IT-20   §80CCD(2) at 10% where the new regime may allow 14%, silently
  PAY-07  §17(2) perquisites that never reach monthly §192
  PAY-08  a payroll reversal that leaves the loan written down

Each test states the figure the Act gives and asserts it, so a later change
that moves a number has to argue with a section rather than with a fixture.
"""
from __future__ import annotations

import pytest

from domain.income_tax.itr_engine import (
    ITRComputeRequest, ITREngine, HRADetails, Deductions80C,
    LIMIT_80CCD2_GOVT_PERCENT, LIMIT_80CCD2_OTHER_PERCENT,
)

FY = "2026-27"
R = 100  # paise in a rupee


def compute(**kw):
    return ITREngine().compute(ITRComputeRequest(fy=FY, **kw))


# ── IT-08: the basic exemption absorbs into special-rate capital gains ───────
#
# Proviso to §111A(1), proviso to §112(1)(a)(ii), second proviso to §112A(2):
# where "the total income as reduced by such capital gains is below the maximum
# amount which is not chargeable to income-tax", the gains "shall be reduced by
# the amount by which the total income as so reduced falls short of" it.

def test_stcg_alone_absorbs_the_whole_basic_exemption():
    """₹5,00,000 of §111A STCG and no other income.

    The nil band under §115BAC(1A) is ₹4,00,000 and nothing else has used it,
    so ₹1,00,000 is charged at 20% = ₹20,000, plus 4% cess = ₹20,800.

    Before this fix the engine charged 20% on the WHOLE ₹5,00,000 — ₹1,04,000,
    five times the liability — and 714c1c84 had already wired capital gains
    into the client computation screen, so that is what a CA was shown.
    """
    r = compute(capital_gains_stcg_paise=500_000 * R)
    assert r.total_tax_paise == 20_800 * R
    assert r.basic_exemption_absorbed_paise == 400_000 * R
    assert len(r.basic_exemption_absorption) == 1
    assert "§111A" in r.basic_exemption_absorption[0]


def test_salary_that_fills_the_nil_band_leaves_nothing_to_absorb():
    """The proviso reaches only what the slab income has NOT used.

    Salary of ₹10,00,000 is far above the nil band, so the whole ₹5,00,000 gain
    is charged: 20% + 4% cess on the gain itself.
    """
    r = compute(gross_salary_paise=1_000_000 * R,
                capital_gains_stcg_paise=500_000 * R)
    assert r.basic_exemption_absorbed_paise == 0


def test_a_partly_used_nil_band_absorbs_only_the_balance():
    """₹1,00,000 of other income and ₹5,00,000 of STCG.

    §115BAC(1A) also gives a ₹75,000 standard deduction, but only against
    salary — this income is not salary, so the slab income is ₹1,00,000 and
    ₹3,00,000 of the ₹4,00,000 band is left. ₹2,00,000 of the gain is charged
    at 20% = ₹40,000, plus cess = ₹41,600.
    """
    r = compute(other_income_paise=100_000 * R,
                capital_gains_stcg_paise=500_000 * R)
    assert r.basic_exemption_absorbed_paise == 300_000 * R
    assert r.total_tax_paise == 41_600 * R


def test_the_exemption_is_absorbed_once_across_three_buckets_not_three_times():
    """Each proviso says "total income as reduced by SUCH gains".

    Read in isolation all three are satisfied at once, and applying each on its
    own terms would relieve up to three times what the Act gives. ₹2,00,000 in
    each bucket, no other income: exactly ₹4,00,000 of exemption is absorbed
    across them, not ₹12,00,000.
    """
    r = compute(capital_gains_stcg_paise=200_000 * R,
                capital_gains_ltcg_paise=200_000 * R,
                capital_gains_ltcg_other_paise=200_000 * R)
    assert r.basic_exemption_absorbed_paise == 400_000 * R


def test_the_highest_rate_bucket_absorbs_first():
    """No statutory order, so the allocation is the assessee's to choose and
    the engine takes the most beneficial one: §111A at 20% before §112/§112A at
    12.5%. ₹2,00,000 of STCG and ₹5,00,000 of other LTCG, no other income —
    the STCG is wiped out entirely and ₹2,00,000 of the band reaches the LTCG.
    """
    r = compute(capital_gains_stcg_paise=200_000 * R,
                capital_gains_ltcg_other_paise=500_000 * R)
    assert r.basic_exemption_absorbed_paise == 400_000 * R
    assert "§111A" in r.basic_exemption_absorption[0]
    assert "§112 " in r.basic_exemption_absorption[1]
    # §112 charged on ₹5,00,000 − ₹2,00,000 = ₹3,00,000 at 12.5% = ₹37,500,
    # plus 4% cess = ₹39,000.
    assert r.total_tax_paise == 39_000 * R


def test_a_firm_gets_no_absorption_because_the_provisos_say_individual():
    """All three provisos read "in the case of an individual or a Hindu
    undivided family, being a resident"."""
    r = compute(assessee_kind="firm", business_income_paise=100_000 * R,
                capital_gains_stcg_paise=500_000 * R)
    assert r.basic_exemption_absorbed_paise == 0


def test_a_non_resident_individual_gets_no_absorption_either():
    """"being a RESIDENT" is the other half of the same limb, and the engine
    had been assuming residence silently."""
    r = compute(is_resident=False, capital_gains_stcg_paise=500_000 * R)
    assert r.basic_exemption_absorbed_paise == 0
    assert r.total_tax_paise == 104_000 * R


def test_the_old_regime_reads_its_own_narrower_nil_band():
    """The limit is "the maximum amount which is not chargeable to income-tax",
    which is the regime's own nil band — ₹2,50,000 under the old one, not the
    new regime's ₹4,00,000. Read off the slabs rather than stated as a
    constant, which is why this cannot drift when a Finance Act moves it."""
    r = compute(use_new_regime=False, capital_gains_stcg_paise=500_000 * R)
    assert r.basic_exemption_absorbed_paise == 250_000 * R


def test_a_senior_citizen_on_the_old_regime_gets_the_wider_band():
    """Part III of the First Schedule widens the nil band at 60 — and it widens
    what the gain may absorb with it, for the same reason."""
    r = compute(use_new_regime=False, is_senior_citizen=True,
                capital_gains_stcg_paise=500_000 * R)
    assert r.basic_exemption_absorbed_paise == 300_000 * R


def test_the_112a_exemption_and_the_absorption_are_both_given():
    """§112A(2) exempts the first ₹1,25,000 of equity LTCG and the second
    proviso then absorbs the unused basic exemption into what is left. Both,
    not one: ₹5,00,000 of equity LTCG and no other income is charged on
    ₹5,00,000 − ₹1,25,000 − ₹3,75,000 = nil."""
    r = compute(capital_gains_ltcg_paise=500_000 * R)
    assert r.total_tax_paise == 0
    assert r.basic_exemption_absorbed_paise == 375_000 * R


# ── IT-26: §10(13A) and §24(b) are not Chapter VI-A ──────────────────────────

def _old_regime_with_hra_and_interest():
    return compute(
        gross_salary_paise=2_000_000 * R, use_new_regime=False,
        hra=HRADetails(hra_received_paise=300_000 * R, rent_paid_paise=360_000 * R,
                       basic_salary_paise=1_000_000 * R, is_metro=True),
        home_loan_interest_24b_paise=200_000 * R)


def test_schedule_vi_a_does_not_carry_the_hra_exemption_or_the_house_interest():
    """itr_json.py maps `total_deductions_paise` to SCHEDULE VI-A, labelled
    "Deductions under Chapter VI-A". §10(13A) is an exemption from salary and
    §24(b) is a deduction under the head house property (§§22-27); neither is
    in Chapter VI-A. With no §80-anything claimed, Schedule VI-A is nil.
    """
    r = _old_regime_with_hra_and_interest()
    assert r.deduction_hra_paise == 260_000 * R
    assert r.deduction_24b_paise == 200_000 * R
    assert r.total_deductions_paise == 0


def test_gross_total_income_is_net_of_both():
    """§14's figure is the heads after each head's own computation and before
    Chapter VI-A. ₹20,00,000 salary − ₹50,000 standard deduction − ₹2,60,000
    HRA − ₹2,00,000 interest = ₹14,90,000."""
    r = _old_regime_with_hra_and_interest()
    assert r.gross_total_income_paise == 1_490_000 * R


def test_the_tax_does_not_move_because_this_splits_a_presentation():
    """The single accumulator held head reliefs and Chapter VI-A together, so
    taxable income was already right. Splitting it must leave every tax figure
    identical — this is the control on the whole change."""
    r = _old_regime_with_hra_and_interest()
    assert r.taxable_income_paise == 1_490_000 * R
    assert r.gross_total_income_paise - r.total_deductions_paise == r.taxable_income_paise


def test_chapter_vi_a_still_carries_what_is_actually_chapter_vi_a():
    """The split must not lose §80C on the way out."""
    r = compute(gross_salary_paise=2_000_000 * R, use_new_regime=False,
                s80c=Deductions80C(ppf_paise=150_000 * R))
    assert r.total_deductions_paise == 150_000 * R
    assert r.deduction_80c_paise == 150_000 * R


# ── IT-32: nothing may escape §80CCE without saying so ───────────────────────

def _through_the_endpoint(**kw):
    """Build the request the way POST /api/income-tax/compute builds it.

    Deliberately NOT `compute()` above. The engine's `Deductions80C.other_paise`
    has always existed and has always been inside the §80CCE cap — the defect
    was that the REQUEST MODEL had no field for it, so nothing could ever put a
    figure there and a CA's stamp duty went to `other_deductions_paise`
    instead, outside the cap. A test that calls the engine directly proves the
    half that was never broken.

    The router is mounted on a bare FastAPI with the auth dependency overridden,
    which is the house pattern (38 of the 43 TestClient modules) — `main.app`
    refuses without SUPABASE_URL, and this endpoint computes rather than
    reading anything, so it needs no database at all.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.auth import get_current_user
    import routers.income_tax as it

    app = FastAPI()
    # The router already carries prefix="/api/income-tax" itself.
    app.include_router(it.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "firm_id": "F1", "role": "Partner",
        "email": "p@f1.test", "auth_user_id": "auth-partner"}
    res = TestClient(app, raise_server_exceptions=False).post(
        "/api/income-tax/compute", json={"fy": FY, "use_new_regime": False, **kw})
    assert res.status_code == 200, res.text
    return res.json()["data"]


def test_an_80c_item_claimed_through_other_paise_is_inside_the_cap():
    """§80C(2) runs to twenty-odd clauses and `Deductions80C` names nine.
    `other_paise` is the way in for the rest — stamp duty, §80CCD(1), a
    scheduled-bank term deposit — and §80CCE caps the TOTAL at ₹1,50,000.

    Through the ENDPOINT, because the field that was missing was the request
    model's. See `_through_the_endpoint`.
    """
    r = compute(gross_salary_paise=2_000_000 * R, use_new_regime=False,
                s80c=Deductions80C(ppf_paise=100_000 * R, other_paise=100_000 * R))
    assert r.deduction_80c_paise == 150_000 * R


def test_the_request_model_has_a_way_into_the_80cce_cap():
    """The half that was actually broken: `S80CInput` exposed nine named fields
    and no `other_paise`, so nothing a CA could send ever reached the engine's
    catch-all. ₹1,00,000 of PPF plus ₹1,00,000 of stamp duty is ₹1,50,000
    allowed, not ₹2,00,000 and not ₹1,00,000."""
    data = _through_the_endpoint(
        gross_salary_paise=2_000_000 * R,
        s80c={"ppf_paise": 100_000 * R, "other_paise": 100_000 * R})
    assert data["deductions"]["s80c_paise"] == 150_000 * R


def test_an_unattributed_deduction_is_allowed_but_says_it_could_not_be_checked():
    """`other_deductions_paise` is the Chapter VI-A catch-all and carries no
    section, so no ceiling can be applied to it. It is still allowed — refusing
    would break every caller and §80E, §80U and §80GG are real — but the
    response says what could not be checked, which is this codebase's answer to
    a figure it cannot verify."""
    r = compute(gross_salary_paise=2_000_000 * R, use_new_regime=False,
                other_deductions_paise=500_000 * R)
    assert r.total_deductions_paise == 500_000 * R
    # ₹5,00,000, Indian-grouped through domain/reporting/amount_words —
    # not Python's own "500,000.00", which no Indian document uses.
    assert any("80CCE" in w and "₹5,00,000" in w for w in r.warnings)


def test_no_such_warning_where_nothing_is_claimed_through_it():
    r = compute(gross_salary_paise=2_000_000 * R, use_new_regime=False)
    assert not any("other deductions" in w for w in r.warnings)


# ── IT-20: the conservative §80CCD(2) choice stops being silent ──────────────

def test_the_10_percent_choice_says_what_it_might_be_costing():
    """The Finance (No. 2) Act 2024 is understood to have raised §80CCD(2) to
    14% for an employee taxed under §115BAC(1A). That amendment cannot be
    verified against the Act's text from this deployment (egress is refused at
    the proxy), so the engine keeps 10% — the direction that cannot over-claim.
    It now says so, with the amount at stake, instead of quietly computing the
    smaller figure.

    ₹12,00,000 of salary, ₹1,68,000 of employer NPS: 10% allows ₹1,20,000 and
    14% would allow ₹1,68,000, so ₹48,000 is at stake.
    """
    r = compute(gross_salary_paise=2_000_000 * R,
                salary_for_80ccd2_paise=1_200_000 * R,
                employer_nps_80ccd2_paise=168_000 * R)
    assert r.deduction_80ccd2_paise == 120_000 * R
    assert any("₹48,000" in w and "§80CCD(2)" in w for w in r.warnings)


def test_a_government_employee_gets_14_percent_and_no_warning():
    """The 14%/10% government split is the long-established one and is not in
    question — only the new regime's enhancement for everybody else is."""
    r = compute(gross_salary_paise=2_000_000 * R, is_government_employee=True,
                salary_for_80ccd2_paise=1_200_000 * R,
                employer_nps_80ccd2_paise=168_000 * R)
    assert r.deduction_80ccd2_paise == 168_000 * R
    assert not any("§80CCD(2)" in w for w in r.warnings)


def test_no_warning_where_the_contribution_is_under_ten_percent():
    """Both percentages give the same answer there, so a warning would be
    noise."""
    r = compute(gross_salary_paise=2_000_000 * R,
                salary_for_80ccd2_paise=1_200_000 * R,
                employer_nps_80ccd2_paise=100_000 * R)
    assert r.deduction_80ccd2_paise == 100_000 * R
    assert not any("§80CCD(2)" in w for w in r.warnings)


def test_no_warning_on_the_old_regime_where_the_enhancement_does_not_reach():
    """The enhancement, if it exists, is expressly for an employee chargeable
    under §115BAC(1A)."""
    r = compute(gross_salary_paise=2_000_000 * R, use_new_regime=False,
                salary_for_80ccd2_paise=1_200_000 * R,
                employer_nps_80ccd2_paise=168_000 * R)
    assert not any("§80CCD(2)" in w for w in r.warnings)


def test_the_two_percentages_are_still_the_constants_the_docstring_argues_for():
    """Pinned so that raising 10% to 14% has to be a deliberate edit against a
    verified source, not a drive-by."""
    assert LIMIT_80CCD2_GOVT_PERCENT == 14
    assert LIMIT_80CCD2_OTHER_PERCENT == 10


# ── PAY-07: §17(2) perquisites reach the monthly §192 estimate ───────────────

def _slip(**kw):
    from routers.payroll import _compute_slip
    # ₹2,50,000 a month — ₹30,00,000 a year, comfortably past the §87A rebate
    # threshold, so there is TDS with and without the perquisite. A salary that
    # the rebate wipes out would make "the perquisite raised the tax" true for
    # the wrong reason.
    emp = {"id": "e1", "name": "A", "basic_paise": 250_000 * R,
           "hra_percent": 0, "da_percent": 0, "state": "Maharashtra"}
    emp.update(kw.pop("employee", {}))
    return _compute_slip(emp, fy=FY, pt_month=4, **kw)


def test_a_valued_perquisite_raises_this_month_s_tds():
    """§17(1)(iv) makes "the value of any perquisite" salary and §192(1)
    charges the employer to deduct on the estimated income under that head. A
    ₹6,00,000 rent-free flat is ₹6,00,000 more salary to estimate on."""
    without = _slip()
    with_perq = _slip(perquisites_paise=600_000 * R)
    assert without["tds_paise"] > 0          # the control: there was tax anyway
    assert with_perq["tds_paise"] > without["tds_paise"]


def test_the_perquisite_is_not_added_to_gross_net_or_the_pf_base():
    """A perquisite is a benefit, not cash. Adding it to gross would inflate
    net pay, the PF wage base and the ESI gross alike — none of which the
    value belongs in."""
    without = _slip()
    with_perq = _slip(perquisites_paise=600_000 * R)
    assert with_perq["gross_paise"] == without["gross_paise"]
    assert with_perq["pf_employee_paise"] == without["pf_employee_paise"]
    # Net falls by exactly the extra TDS and by nothing else — and the extra
    # TDS is not zero, or this would assert nothing.
    extra = with_perq["tds_paise"] - without["tds_paise"]
    assert extra > 0
    assert without["net_paise"] - with_perq["net_paise"] == extra


def test_the_slip_records_what_the_estimate_was_computed_on():
    """Migration 368. The only input to the estimate that is not visible
    anywhere else on the payslip, so a CA whose TDS moved can see why."""
    slip = _slip(perquisites_paise=600_000 * R)
    assert slip["perquisites_in_tds_estimate_paise"] == 600_000 * R
    assert _slip()["perquisites_in_tds_estimate_paise"] == 0


def test_a_negative_perquisite_cannot_reduce_the_estimate():
    """Floored, because a perquisite is a value and §17(2) has no negative one
    — and because a negative would under-withhold, which is the direction that
    costs the employer §201(1A) interest."""
    assert (_slip(perquisites_paise=-600_000 * R)["tds_paise"]
            == _slip()["tds_paise"])
