"""
Choosing between the tax regimes — §115BAC(6), Rule 21AGA, Form 10-IEA.

Nothing modelled the election. ITRComputeRequest carried a use_new_regime flag
and computed either way, but nothing said HOW a taxpayer gets to the old
regime, by when, or whether they are still allowed to.

Since AY 2024-25 the §115BAC regime is the default, and §115BAC(6) splits into
two clauses that are not variations of one rule:

  (i)  WITH business or professional income — the option is exercised in Form
       10-IEA on or before the §139(1) due date, may be withdrawn only ONCE,
       and after that withdrawal the person "shall never be eligible to
       exercise the option under this sub-section" unless business income
       ceases.
  (ii) WITHOUT such income — exercised in the return itself, no form, no
       lock-out, afresh every year.

Both failure modes are invisible in the return, which computes cleanly either
way: a missed Form 10-IEA taxes a client on the new regime for a year they
planned around the old one and cannot be cured after the due date, and an
unwitting withdrawal closes an option worth lakhs over a career.
"""
from datetime import date

import pytest

from domain.income_tax.regime_election import (
    PriorElection, election_route, evaluate_election, form_10iea_due_date,
)
from services.compliance_engine import itr_due_date

FYE = 2026        # FY 2025-26 ends 31 March 2026


# ── Which limb applies ───────────────────────────────────────────────────────

def test_business_income_decides_the_whole_shape_of_the_election():
    assert election_route(has_business_income=True) == "form_10iea"
    assert election_route(has_business_income=False) == "in_the_return"


# ── The deadline follows §139(1), and is not restated ────────────────────────

def test_the_form_deadline_is_the_return_due_date():
    """Rule 21AGA ties Form 10-IEA to §139(1). A second copy of those dates
    here is the thing that drifts when a year is extended by circular."""
    assert form_10iea_due_date(FYE) == itr_due_date(FYE)
    assert form_10iea_due_date(FYE, is_audit=True) == itr_due_date(FYE, is_audit=True)


def test_the_three_section_139_dates():
    assert itr_due_date(FYE) == date(2026, 7, 31)
    assert itr_due_date(FYE, is_audit=True) == date(2026, 10, 31)
    assert itr_due_date(FYE, has_transfer_pricing_report=True) == date(2026, 11, 30)


def test_a_transfer_pricing_report_extends_past_the_audit_date():
    """§92E was missing entirely, and it is not a rarity a CA can be left to
    remember: it governs any assessee with an international or specified
    domestic transaction. Told 31 October when the Act allows 30 November, a
    client files a month early or is wrongly told they are late."""
    assert itr_due_date(FYE, is_audit=True, has_transfer_pricing_report=True) \
        == date(2026, 11, 30)
    assert form_10iea_due_date(FYE, has_transfer_pricing_report=True) == date(2026, 11, 30)


# ── Clause (ii): no business income ──────────────────────────────────────────

def test_a_salaried_taxpayer_chooses_in_the_return_with_no_form():
    r = evaluate_election(wants_old_regime=True, has_business_income=False,
                          financial_year_end=FYE)
    assert r.regime == "old"
    assert r.route == "in_the_return"
    assert r.form_10iea_required is False
    assert r.due_date is None
    assert any("§115BAC(6)(ii)" in x for x in r.reasons)


def test_a_salaried_taxpayer_is_never_locked_out():
    """No withdrawal limit applies under clause (ii) — the choice is afresh
    every year, however many times it has been made before."""
    r = evaluate_election(
        wants_old_regime=True, has_business_income=False, financial_year_end=FYE,
        prior_elections=[PriorElection("2023-24", "opted_out"),
                         PriorElection("2024-25", "withdrew")])
    assert r.regime == "old"
    assert r.election_is_available is True


# ── The default needs no election ────────────────────────────────────────────

def test_staying_in_the_new_regime_requires_nothing():
    r = evaluate_election(wants_old_regime=False, has_business_income=True,
                          financial_year_end=FYE)
    assert r.regime == "new"
    assert r.form_10iea_required is False
    assert any("default since AY 2024-25" in x for x in r.reasons)


# ── Clause (i): business income ──────────────────────────────────────────────

def test_without_the_form_the_new_regime_applies_whatever_the_return_says():
    r = evaluate_election(wants_old_regime=True, has_business_income=True,
                          financial_year_end=FYE, prior_elections=[])
    assert r.regime == "new"
    assert r.form_10iea_required is True
    assert r.due_date == date(2026, 7, 31)
    assert any("has not been filed" in x for x in r.reasons)


def test_filed_on_time_the_old_regime_applies():
    r = evaluate_election(wants_old_regime=True, has_business_income=True,
                          financial_year_end=FYE,
                          form_10iea_filed_on=date(2026, 7, 30), prior_elections=[])
    assert r.regime == "old"
    assert r.election_is_available is True


def test_filing_on_the_due_date_itself_counts():
    """"On or before" includes the day. A boundary error here costs a client
    the regime for a whole year."""
    r = evaluate_election(wants_old_regime=True, has_business_income=True,
                          financial_year_end=FYE,
                          form_10iea_filed_on=date(2026, 7, 31), prior_elections=[])
    assert r.regime == "old"


def test_one_day_late_is_not_an_election_and_cannot_be_cured():
    r = evaluate_election(wants_old_regime=True, has_business_income=True,
                          financial_year_end=FYE,
                          form_10iea_filed_on=date(2026, 8, 1), prior_elections=[])
    assert r.regime == "new"
    assert r.election_is_available is False
    assert any("cannot be cured" in x for x in r.reasons)


def test_an_audit_case_has_until_the_thirty_first_of_october():
    r = evaluate_election(wants_old_regime=True, has_business_income=True,
                          financial_year_end=FYE, is_audit=True,
                          form_10iea_filed_on=date(2026, 10, 20), prior_elections=[])
    assert r.due_date == date(2026, 10, 31)
    assert r.regime == "old"


# ── The proviso: one withdrawal, then never again ────────────────────────────

def test_a_withdrawal_closes_the_old_regime_permanently():
    r = evaluate_election(
        wants_old_regime=True, has_business_income=True, financial_year_end=FYE,
        form_10iea_filed_on=date(2026, 7, 1),
        prior_elections=[PriorElection("2023-24", "opted_out"),
                         PriorElection("2024-25", "withdrew")])
    assert r.regime == "new"
    assert r.election_is_available is False
    assert any("never" in x or "bars exercising it again" in x for x in r.reasons)


def test_opting_out_repeatedly_is_not_a_withdrawal():
    """The proviso bars a further election only after a WITHDRAWAL. Staying in
    the old regime across years keeps the option exercised; it does not spend
    it. Counting those as withdrawals would lock out a client who never left."""
    r = evaluate_election(
        wants_old_regime=True, has_business_income=True, financial_year_end=FYE,
        form_10iea_filed_on=date(2026, 7, 1),
        prior_elections=[PriorElection("2022-23", "opted_out"),
                         PriorElection("2023-24", "opted_out"),
                         PriorElection("2024-25", "opted_out")])
    assert r.regime == "old"
    assert r.election_is_available is True


def test_ceasing_to_have_business_income_reopens_the_choice():
    """The proviso's own exception: the person falls back under clause (ii) and
    may choose in the return each year again."""
    r = evaluate_election(
        wants_old_regime=True, has_business_income=True, financial_year_end=FYE,
        business_income_ceased=True,
        prior_elections=[PriorElection("2024-25", "withdrew")])
    assert r.regime == "old"
    assert r.route == "in_the_return"
    assert r.form_10iea_required is False
    assert r.election_is_available is True


def test_a_successful_election_warns_that_the_return_journey_is_one_way():
    r = evaluate_election(wants_old_regime=True, has_business_income=True,
                          financial_year_end=FYE,
                          form_10iea_filed_on=date(2026, 7, 1), prior_elections=[])
    assert any("only ONCE" in x for x in r.reasons)


# ── What the product does not know, it says ──────────────────────────────────

def test_missing_history_is_reported_rather_than_assumed_available():
    """The product holds no filing history. Assuming the option is available is
    the dangerous direction — it tells a CA the old regime is open when the
    client spent it years ago."""
    r = evaluate_election(wants_old_regime=True, has_business_income=True,
                          financial_year_end=FYE,
                          form_10iea_filed_on=date(2026, 7, 1))
    assert r.history_unknown is True
    assert any("cannot be determined here" in x for x in r.reasons)


def test_supplied_history_is_not_reported_as_unknown():
    r = evaluate_election(wants_old_regime=True, has_business_income=True,
                          financial_year_end=FYE,
                          form_10iea_filed_on=date(2026, 7, 1), prior_elections=[])
    assert r.history_unknown is False


def test_an_empty_history_is_different_from_no_history():
    """[] means "the CA checked and there were none"; None means "nobody
    looked". Conflating them turns a gap into a false assurance."""
    checked = evaluate_election(wants_old_regime=True, has_business_income=True,
                                financial_year_end=FYE, prior_elections=[])
    not_checked = evaluate_election(wants_old_regime=True, has_business_income=True,
                                    financial_year_end=FYE)
    assert checked.history_unknown is False
    assert not_checked.history_unknown is True
