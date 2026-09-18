"""Chapter VI-A, section by section, each with its own limit (IT-32).

WHAT WAS WRONG
    `itr_engine` modelled §80C, §80CCD(1B), §80D, §80TTA/§80TTB and §80G and
    sent EVERYTHING ELSE through `other_deductions_paise` -- one unlabelled
    figure, added with no ceiling and no section attribution. So an old-regime
    individual with an education loan, a disabled dependant, a specified
    illness, a disability, or rent and no HRA had the deductions MOST LIKELY TO
    BE QUESTIONED lumped into a single number with no audit trail.

⚠️ EVERY FIGURE IS `[S]`-GRADED -- egress is refused at this environment's
proxy, so none was read off the Act -- and each is pinned EXACTLY here. A later
correction is then a deliberate edit with a failing test in front of it.

THE THREE SHAPES, AND CONFUSING THEM IS THE COMMON ERROR
    flat        §80DD and §80U give a FIXED amount whatever was spent.
    capped      §80DDB, §80EE and §80EEA allow the spend up to a ceiling.
    uncapped    §80E allows the WHOLE interest, limited only by a PERIOD.
    least-of    §80GG, whose base depends on every other deduction.

NEGATIVE CONTROLS -- all five run against the code and reverted:
  * Read §80DD as a capped REIMBURSEMENT of what was spent -> 5 fail.
  * Cap §80DDB before subtracting the reimbursement -> 1 fails. That order
    under-allows wherever the spend exceeded the ceiling.
  * Add the preventive check-up ON TOP of §80D's ceiling instead of within
    it -> 1 fails.
  * Compute §80G before §80GG -> 1 fails.
  * Delete two fields from the screen's payload while leaving their form state
    in place -> 2 fail. That last shape is the one that matters: an earlier
    guard elsewhere in this repository matched field names ANYWHERE in the
    source and so passed on a screen that had stopped sending them.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.income_tax import chapter_vi_a as c
from domain.income_tax.itr_engine import (
    Deductions80D, LIMIT_80D_PREVENTIVE_PAISE, LIMIT_80D_SELF_PAISE,
    LIMIT_80D_SELF_SENIOR_PAISE)


# ── every [S] figure, pinned exactly ─────────────────────────────────────────

def test_nothing_here_claims_to_be_verified():
    assert c.VERIFIED is False
    assert "pinned exactly by a test" in c.UNVERIFIED_NOTE


@pytest.mark.parametrize("name, expected", [
    ("SECTION_80E_ASSESSMENT_YEARS", 8),
    ("SECTION_80EE_LIMIT_PAISE", 50_000_00),
    ("SECTION_80EEA_LIMIT_PAISE", 1_50_000_00),
    ("DISABILITY_LIMIT_PAISE", 75_000_00),
    ("SEVERE_DISABILITY_LIMIT_PAISE", 1_25_000_00),
    ("SECTION_80DDB_LIMIT_PAISE", 40_000_00),
    ("SECTION_80DDB_SENIOR_LIMIT_PAISE", 1_00_000_00),
    ("SECTION_80GG_MONTHLY_PAISE", 5_000_00),
    ("SECTION_80GG_ANNUAL_PAISE", 60_000_00),
    ("SECTION_80GG_INCOME_PCT", 25),
    ("SECTION_80GG_RENT_OVER_PCT", 10),
])
def test_every_limit_is_pinned(name, expected):
    assert getattr(c, name) == expected


@pytest.mark.parametrize("name, expected", [
    ("SECTION_80EE_SANCTION_FROM", date(2016, 4, 1)),
    ("SECTION_80EE_SANCTION_TO", date(2017, 3, 31)),
    ("SECTION_80EEA_SANCTION_FROM", date(2019, 4, 1)),
    ("SECTION_80EEA_SANCTION_TO", date(2022, 3, 31)),
])
def test_both_windows_are_pinned(name, expected):
    assert getattr(c, name) == expected


# ── §80E: uncapped in amount, capped in YEARS ────────────────────────────────

def test_the_whole_education_loan_interest_is_allowed():
    """No monetary limit at all. A ceiling here would be invented."""
    r = c.compute(c.ChapterVIAClaims(education_loan_interest_paise=3_00_000_00,
                                     education_loan_year=1))
    line = next(l for l in r.lines if l.section == "80E")
    assert line.allowed_paise == 3_00_000_00
    assert line.restricted_paise == 0
    assert "no monetary limit" in line.basis


def test_an_exhausted_education_loan_claim_allows_nothing():
    r = c.compute(c.ChapterVIAClaims(education_loan_interest_paise=50_000_00,
                                     education_loan_year=9))
    line = next(l for l in r.lines if l.section == "80E")
    assert line.allowed_paise == 0
    assert "exhausted" in line.basis


def test_an_unstated_year_is_allowed_and_named():
    """Nothing here counts the years, and refusing would deny a live claim."""
    r = c.compute(c.ChapterVIAClaims(education_loan_interest_paise=50_000_00))
    line = next(l for l in r.lines if l.section == "80E")
    assert line.allowed_paise == 50_000_00
    assert any("which of the" in g for g in r.gaps)


# ── §80EE / §80EEA: the SANCTION date decides, and both windows are shut ─────

@pytest.mark.parametrize("sanctioned, section", [
    (date(2016, 4, 1), "80EE"),
    (date(2017, 3, 31), "80EE"),
    (date(2019, 4, 1), "80EEA"),
    (date(2022, 3, 31), "80EEA"),
    (date(2016, 3, 31), None),      # a day early
    (date(2017, 4, 1), None),       # between the two windows
    (date(2022, 4, 1), None),       # a day late
    (date(2024, 6, 1), None),       # long after
    (None, None),
])
def test_the_sanction_date_alone_decides_the_section(sanctioned, section):
    assert c.housing_loan_section(sanctioned) == section


def test_a_loan_with_no_sanction_date_allows_nothing_and_says_why():
    """The two limits differ by Rs 1,00,000; there is no safe default between
    them, so nothing is allowed rather than one being assumed."""
    r = c.compute(c.ChapterVIAClaims(housing_loan_extra_interest_paise=2_00_000_00))
    line = next(l for l in r.lines if l.section.startswith("80EE"))
    assert line.allowed_paise == 0
    assert any("sanction date" in g for g in r.gaps)


def test_the_additional_interest_is_capped_at_its_own_section():
    r = c.compute(c.ChapterVIAClaims(
        housing_loan_extra_interest_paise=2_00_000_00,
        housing_loan_sanctioned_on=date(2020, 6, 1)))
    line = next(l for l in r.lines if l.section == "80EEA")
    assert line.allowed_paise == c.SECTION_80EEA_LIMIT_PAISE
    assert line.restricted_paise == 50_000_00


# ── §80DD and §80U are FLAT, which is the common error ───────────────────────

@pytest.mark.parametrize("severe, expected", [
    (False, 75_000_00), (True, 1_25_000_00),
])
def test_disability_is_a_flat_deduction_not_a_reimbursement(severe, expected):
    """The amount does not depend on what was spent. A CA who spent Rs 20,000
    on a dependant with a 40% disability deducts Rs 75,000; one who spent
    Rs 3,00,000 deducts the same Rs 75,000."""
    assert c.disability_limit_paise(severe) == expected

    r = c.compute(c.ChapterVIAClaims(has_disabled_dependant=True,
                                     dependant_disability_is_severe=severe))
    line = next(l for l in r.lines if l.section == "80DD")
    assert line.allowed_paise == expected
    assert line.claimed_paise == expected, (
        "a flat deduction claims what it allows; anything else invites a "
        "reader to think the spend mattered")
    assert "FLAT" in line.basis


def test_both_disability_sections_read_one_ladder():
    """§80DD and §80U share the Act's own amounts, so they share one function
    rather than two copies that can drift."""
    r = c.compute(c.ChapterVIAClaims(
        has_disabled_dependant=True, assessee_is_disabled=True,
        dependant_disability_is_severe=True))
    dd = next(l for l in r.lines if l.section == "80DD")
    u = next(l for l in r.lines if l.section == "80U")
    assert dd.allowed_paise == c.SEVERE_DISABILITY_LIMIT_PAISE
    assert u.allowed_paise == c.DISABILITY_LIMIT_PAISE


def test_a_disability_claim_names_the_certificate():
    r = c.compute(c.ChapterVIAClaims(assessee_is_disabled=True))
    line = next(l for l in r.lines if l.section == "80U")
    assert any("Form 10-IA" in x for x in line.caveats)


# ── §80DDB: reduced FIRST, capped SECOND ─────────────────────────────────────

def test_the_reimbursement_comes_off_before_the_ceiling():
    """The other order caps the gross spend and then subtracts, which
    under-allows wherever the spend exceeded the ceiling.

    Rs 1,50,000 spent, Rs 20,000 reimbursed, Rs 40,000 ceiling:
      right  min(1,50,000 - 20,000, 40,000) = 40,000
      wrong  min(1,50,000, 40,000) - 20,000 = 20,000
    """
    r = c.compute(c.ChapterVIAClaims(specified_disease_spend_paise=1_50_000_00,
                                     specified_disease_reimbursed_paise=20_000_00))
    line = next(l for l in r.lines if l.section == "80DDB")
    assert line.allowed_paise == 40_000_00


def test_the_patients_age_sets_the_ceiling():
    claims = dict(specified_disease_spend_paise=90_000_00)
    ordinary = c.compute(c.ChapterVIAClaims(**claims))
    senior = c.compute(c.ChapterVIAClaims(**claims, patient_is_senior=True))
    assert next(l for l in ordinary.lines if l.section == "80DDB").allowed_paise == 40_000_00
    assert next(l for l in senior.lines if l.section == "80DDB").allowed_paise == 90_000_00


def test_a_reimbursement_larger_than_the_spend_allows_nothing():
    r = c.compute(c.ChapterVIAClaims(specified_disease_spend_paise=30_000_00,
                                     specified_disease_reimbursed_paise=50_000_00))
    assert next(l for l in r.lines if l.section == "80DDB").allowed_paise == 0


# ── §80GG: the least of three ────────────────────────────────────────────────

@pytest.mark.parametrize("rent, income, expected, which", [
    # (i) bites: a modest rent against a large income.
    (2_40_000_00, 10_00_000_00, 60_000_00, "5,000 a month"),
    # (iii) bites: rent barely over a tenth of income.
    (1_20_000_00, 10_00_000_00, 20_000_00, "less 10%"),
    # (ii) bites: a tiny income and a large rent.
    (5_00_000_00, 2_00_000_00, 50_000_00, "25% of total income"),
    # Rent under a tenth of income: limb (iii) is negative, so nothing.
    (50_000_00, 10_00_000_00, 0, "less 10%"),
])
def test_section_80gg_takes_the_least_and_says_which(rent, income, expected, which):
    allowed, basis = c.section_80gg_paise(rent, income)
    assert allowed == expected
    assert which in basis


def test_section_80gg_is_refused_where_hra_is_received():
    """§10(13A) is the relief there and is already computed on the salary
    head. Allowing both would relieve the same rent twice."""
    claims = c.ChapterVIAClaims(rent_paid_paise=2_40_000_00, receives_hra=True)
    r = c.compute(claims)
    c.add_section_80gg(r, claims, 10_00_000_00)
    assert not [l for l in r.lines if l.section == "80GG"]
    assert any("receives NO house rent allowance" in g for g in r.gaps)


def test_section_80gg_names_its_declaration():
    claims = c.ChapterVIAClaims(rent_paid_paise=2_40_000_00)
    r = c.add_section_80gg(c.compute(claims), claims, 10_00_000_00)
    line = next(l for l in r.lines if l.section == "80GG")
    assert any("Form 10BA" in x for x in line.caveats)


# ── §80JJAA is refused, with its own reason ──────────────────────────────────

def test_section_80jjaa_is_refused_on_every_answer():
    """Its 30% is the easy half. The section turns on the 240/150-day test, a
    Rs 25,000 monthly ceiling, provident-fund enrolment and the mode of
    payment — none of which these books hold — plus a §44AB audit and a Form
    10DA report."""
    r = c.compute(c.ChapterVIAClaims())
    assert c.SECTION_80JJAA_NOT_COMPUTED in r.caveats
    for needed in ("240 days", "25,000", "10DA", "44AB"):
        assert needed in c.SECTION_80JJAA_NOT_COMPUTED


def test_no_claim_produces_no_line():
    """A statement does not print rows of zeros."""
    r = c.compute(c.ChapterVIAClaims())
    assert r.lines == []
    assert r.total_allowed_paise == 0
    assert r.caveats, "but the refusals and the [S] note still travel"


# ── §80D's two missing routes ────────────────────────────────────────────────

def test_the_preventive_check_up_is_inside_the_ceiling_not_on_top():
    """Reading it as an addition over-claims by up to Rs 5,000 a head, on a
    deduction every salaried return carries."""
    assert LIMIT_80D_PREVENTIVE_PAISE == 5_000_00
    at_cap = Deductions80D(self_family_premium_paise=LIMIT_80D_SELF_PAISE,
                           self_family_preventive_paise=5_000_00)
    assert at_cap.eligible_paise() == LIMIT_80D_SELF_PAISE

    under_cap = Deductions80D(self_family_premium_paise=20_000_00,
                              self_family_preventive_paise=5_000_00)
    assert under_cap.eligible_paise() == 25_000_00


def test_the_check_up_is_itself_capped_at_five_thousand():
    d = Deductions80D(self_family_premium_paise=0,
                      self_family_preventive_paise=12_000_00)
    assert d.eligible_paise() == LIMIT_80D_PREVENTIVE_PAISE


def test_an_uninsured_senior_may_claim_the_medical_expenditure():
    """The route a CA needs most often — an eighty-year-old parent no insurer
    will cover — and there was no field for it."""
    d = Deductions80D(parents_is_senior=True, parents_medical_paise=80_000_00)
    assert d.eligible_paise() == LIMIT_80D_SELF_SENIOR_PAISE


@pytest.mark.parametrize("kwargs, expected, why", [
    ({"parents_is_senior": True, "parents_premium_paise": 30_000_00,
      "parents_medical_paise": 80_000_00}, 30_000_00,
     "the section allows expenditure only where NO policy is in force"),
    ({"parents_medical_paise": 80_000_00}, 0,
     "and only for a SENIOR citizen"),
])
def test_medical_expenditure_has_both_conditions(kwargs, expected, why):
    assert Deductions80D(**kwargs).eligible_paise() == expected, why


# ── the engine ───────────────────────────────────────────────────────────────

def test_the_engine_reports_a_line_per_section():
    from domain.income_tax.itr_engine import ITRComputeRequest, itr_engine

    req = ITRComputeRequest(
        fy="2025-26", gross_salary_paise=15_00_000_00,
        use_new_regime=False,
        chapter_vi_a=c.ChapterVIAClaims(
            education_loan_interest_paise=60_000_00, education_loan_year=2,
            has_disabled_dependant=True))
    result = itr_engine.compute(req)
    sections = {l["section"] for l in result.chapter_vi_a_lines}
    assert {"80E", "80DD"} <= sections
    assert result.chapter_vi_a_paise == 60_000_00 + c.DISABILITY_LIMIT_PAISE


def test_section_80gg_is_computed_before_section_80g():
    """§80G(4)'s ceiling is reduced by every OTHER Chapter VI-A deduction,
    which §80GG is. Computing §80G first leaves §80GG out of its base and
    over-states the donation ceiling."""
    import inspect
    from domain.income_tax import itr_engine as eng

    src = inspect.getsource(eng.ITREngine.compute)
    assert src.index("add_section_80gg") < src.index("compute_80g_deduction")


# ── the endpoint, and the screen that has to reach it ────────────────────────
#
# THE HALF THIS CODEBASE KEEPS GETTING WRONG. A finished engine no caller
# reaches is the `capital_wip` / `fx_revaluation_service` / §115BAC(6) shape:
# built, tested, structurally unreachable, and invisible because the screen
# renders a plausible answer without it. So the endpoint is asserted to TAKE
# the claims and to SERVE the per-section working, and the computation screen
# is asserted to send them.

CALLER = {"firm_id": "F1", "id": "u1", "auth_user_id": "a1",
          "email": "ca@f.test", "role": "Partner"}


def _compute(**chapter):
    import routers.income_tax as it
    body = {
        "fy": "2025-26", "gross_salary_paise": 15_00_000_00,
        "use_new_regime": False,
        "chapter_vi_a": chapter,
    }
    return it.compute_itr(it.ComputeITRRequest(**body), CALLER)


def test_the_endpoint_takes_the_claims_and_serves_the_working():
    res = _compute(education_loan_interest_paise=60_000_00,
                   education_loan_year=2, has_disabled_dependant=True)
    assert res["success"] is True
    lines = res["data"]["deductions"]["chapter_vi_a_lines"]
    assert {l["section"] for l in lines} >= {"80E", "80DD"}
    assert res["data"]["deductions"]["chapter_vi_a_paise"] == (
        60_000_00 + c.DISABILITY_LIMIT_PAISE)


def test_a_line_carries_what_the_ceiling_withheld():
    """`restricted_paise` is the whole point. A total says how much was
    deducted; only the line says how much a ceiling refused, which is what a
    CA has to explain if it is questioned."""
    res = _compute(housing_loan_extra_interest_paise=2_00_000_00,
                   housing_loan_sanctioned_on="2020-06-01")
    line = next(l for l in res["data"]["deductions"]["chapter_vi_a_lines"]
                if l["section"] == "80EEA")
    assert line["claimed_paise"] == 2_00_000_00
    assert line["allowed_paise"] == c.SECTION_80EEA_LIMIT_PAISE
    assert line["restricted_paise"] == 50_000_00
    assert line["basis"]


def test_the_boundary_parses_the_date_and_a_bad_one_allows_nothing():
    """The router parses; the rule does not. A malformed date reads as
    "no date given", which allows NOTHING — §80EE's and §80EEA's limits differ
    by ₹1,00,000 and there is no safe default between them."""
    res = _compute(housing_loan_extra_interest_paise=2_00_000_00,
                   housing_loan_sanctioned_on="not-a-date")
    lines = res["data"]["deductions"]["chapter_vi_a_lines"]
    line = next(l for l in lines if l["section"].startswith("80EE"))
    assert line["allowed_paise"] == 0
    assert any("sanction date" in w for w in res["data"]["warnings"])


def _screen_source() -> str:
    import pathlib
    p = (pathlib.Path(__file__).resolve().parents[2]
         / "web/app/clients/[id]/tax/computation/page.tsx")
    return p.read_text(encoding="utf-8")


@pytest.mark.parametrize("field", [
    "education_loan_interest_paise",
    "education_loan_year",
    "housing_loan_extra_interest_paise",
    "housing_loan_sanctioned_on",
    "has_disabled_dependant",
    "dependant_disability_is_severe",
    "assessee_is_disabled",
    "assessee_disability_is_severe",
    "specified_disease_spend_paise",
    "specified_disease_reimbursed_paise",
    "patient_is_senior",
    "rent_paid_paise",
    "receives_hra",
])
def test_the_computation_screen_sends_every_claim(field):
    """Matched inside the `chapter_vi_a:` OBJECT rather than anywhere in the
    file: a name left behind in form state after the payload entry was deleted
    is exactly how a free-text scan passes on a screen that sends nothing.
    (That was a real negative-control failure on PAY-13.)"""
    src = _screen_source()
    start = src.index("chapter_vi_a: {")
    end = src.index("\n          },", start)
    assert field in src[start:end], field


def test_the_screen_renders_the_per_section_lines():
    """A total alone restates exactly what `other_deductions_paise` was."""
    src = _screen_source()
    assert "chapter_vi_a_lines" in src
    assert "restricted_paise" in src


def test_the_screen_caps_nothing_of_its_own():
    """Zero business logic in the frontend: the screen sends CLAIMS and the
    server applies every ceiling, window and flat amount.

    Stated as the RULE — no arithmetic inside the payload object — rather than
    as a list of numbers not to spell. An earlier draft of this test banned the
    digits of each limit and failed on the money parser's own error message
    ("e.g. 50000 or 50000.50"), which is a spelling of the rule and not the
    rule. That mistake has now been made enough times in this repository to be
    worth writing down again."""
    src = _screen_source()
    start = src.index("chapter_vi_a: {")
    end = src.index("\n          },", start)
    payload = src[start:end]
    for banned in ("Math.min", "Math.max", "Math.round"):
        assert banned not in payload, (
            f"{banned} inside the chapter_vi_a payload is a ceiling applied in "
            "the browser; domain/income_tax/chapter_vi_a.py is the authority")
