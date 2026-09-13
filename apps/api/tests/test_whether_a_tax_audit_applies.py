"""
IT Act §44AB — whether a tax audit applies (IT-11, the applicability half).

WHAT THIS REPLACES
    `apps/web/app/income-tax/tax-audit/page.tsx` decided this in three lines of
    TypeScript against two constants, and read the NATURE OF THE ACTIVITY off
    the AMOUNT:

        turnover >= 1 crore  -> "tax audit mandatory (business)"
        turnover >= 50 lakh  -> "tax audit mandatory (profession)"

    Two of the tests below are the two wrong statements that produced. The rest
    pin the proviso to §44AB(a), which that badge never applied at all, and the
    refusals.
"""
from __future__ import annotations

import pytest

from domain.income_tax import tax_audit as ta

CRORE = ta.CRORE_PAISE
LAKH = ta.LAKH_PAISE
FY = "2026-27"


# ── The two statements the browser badge got wrong ───────────────────────────

def test_a_business_under_one_crore_needs_no_audit_and_is_not_called_a_profession():
    """₹60 lakh of BUSINESS turnover. The badge said "tax audit mandatory
    (profession)" because 60 lakh clears §44AB(b)'s figure — but (b) reaches a
    person carrying on a profession, and this client is not one."""
    a = ta.answer(nature="business", turnover_paise=60 * LAKH, financial_year=FY)
    assert a.required is False
    assert a.clause == "44AB(a)"
    assert "profession" not in a.basis.lower().split("gross receipts")[0]
    assert a.threshold_applied_paise == 1 * CRORE


def test_a_profession_over_one_crore_is_still_judged_on_its_own_clause():
    """₹1.2 crore of PROFESSIONAL gross receipts. The badge said "business"."""
    a = ta.answer(nature="profession", turnover_paise=120 * LAKH, financial_year=FY)
    assert a.required is True
    assert a.clause == "44AB(b)"
    assert a.threshold_applied_paise == 50 * LAKH


def test_the_nature_is_required_and_is_never_guessed_from_the_amount():
    with pytest.raises(ValueError) as e:
        ta.answer(nature="", turnover_paise=5 * CRORE, financial_year=FY)
    assert "fact about the client" in str(e.value)
    with pytest.raises(ValueError):
        ta.answer(nature="trade", turnover_paise=5 * CRORE, financial_year=FY)


# ── §44AB(a) and its proviso ─────────────────────────────────────────────────

def test_a_business_over_one_crore_needs_an_audit():
    a = ta.answer(nature="business", turnover_paise=1 * CRORE + 1, financial_year=FY)
    assert a.required is True
    assert a.clause == "44AB(a)"


def test_the_clause_charges_on_EXCEEDING_the_limit_not_on_reaching_it():
    """"exceed one crore rupees" — exactly the limit is outside the clause."""
    at = ta.answer(nature="business", turnover_paise=1 * CRORE, financial_year=FY)
    over = ta.answer(nature="business", turnover_paise=1 * CRORE + 1, financial_year=FY)
    assert at.required is False
    assert over.required is True


def test_the_proviso_lifts_the_figure_to_ten_crore_when_both_cash_sides_are_within_five_percent():
    a = ta.answer(
        nature="business", turnover_paise=4 * CRORE, financial_year=FY,
        cash_receipts_paise=2 * LAKH,          # 0.5% of turnover
        cash_payments_paise=1 * LAKH,          # 0.33% of payments
        total_payments_paise=3 * CRORE,
    )
    assert a.required is False
    assert a.enhanced_limit_applied is True
    assert a.threshold_applied_paise == 10 * CRORE


def test_the_proviso_is_CONJUNCTIVE_so_one_side_over_the_ceiling_defeats_it():
    a = ta.answer(
        nature="business", turnover_paise=4 * CRORE, financial_year=FY,
        cash_receipts_paise=2 * LAKH,           # fine
        cash_payments_paise=50 * LAKH,          # 16.7% of payments — not fine
        total_payments_paise=3 * CRORE,
    )
    assert a.required is True
    assert a.enhanced_limit_applied is False
    assert a.threshold_applied_paise == 1 * CRORE
    assert any("cash payments exceed" in c for c in a.caveats)


def test_exactly_five_percent_QUALIFIES_because_the_test_is_cross_multiplied():
    """10,00,00,000 with exactly 50,00,000 in cash is 5.000%. A percentage
    computed by division can round a taxpayer across this boundary; the module
    cross-multiplies for the reason presumptive.py gives."""
    a = ta.answer(
        nature="business", turnover_paise=8 * CRORE, financial_year=FY,
        cash_receipts_paise=40 * LAKH,          # exactly 5% of 8 crore
        cash_payments_paise=25 * LAKH,          # exactly 5% of 5 crore
        total_payments_paise=5 * CRORE,
    )
    assert a.enhanced_limit_applied is True


def test_the_proviso_is_NOT_applied_when_any_of_its_three_figures_is_missing():
    """Assuming the cash test is met is what produces a missed audit and
    §271B. The base figure stands and the answer says which fact would move
    it — including the payments DENOMINATOR, which turnover cannot supply."""
    for kwargs in (
        {"cash_receipts_paise": 2 * LAKH, "cash_payments_paise": 1 * LAKH},   # no denominator
        {"cash_receipts_paise": 2 * LAKH, "total_payments_paise": 3 * CRORE},  # no cash payments
        {"cash_payments_paise": 1 * LAKH, "total_payments_paise": 3 * CRORE},  # no cash receipts
        {},
    ):
        a = ta.answer(nature="business", turnover_paise=4 * CRORE,
                      financial_year=FY, **kwargs)
        assert a.required is True, kwargs
        assert a.enhanced_limit_applied is False, kwargs
        assert any("was NOT applied" in c for c in a.caveats), kwargs


def test_the_proviso_caveat_names_the_missing_figures():
    a = ta.answer(nature="business", turnover_paise=4 * CRORE, financial_year=FY,
                  cash_receipts_paise=2 * LAKH)
    caveat = next(c for c in a.caveats if "was NOT applied" in c)
    assert "cash payments" in caveat
    assert "total payments" in caveat
    assert "cash receipts" not in caveat.split("not stated")[0].split("NOT applied")[1]


def test_no_proviso_caveat_where_the_base_limit_is_not_even_reached():
    """A caveat about a limb that changes nothing is noise on the answer."""
    a = ta.answer(nature="business", turnover_paise=40 * LAKH, financial_year=FY)
    assert not any("proviso" in c for c in a.caveats)


# ── §44AB(b) has no cash-based enhancement ───────────────────────────────────

def test_a_profession_gets_no_higher_limit_however_little_cash_it_takes():
    """The proviso sits on clause (a) and names clause (a)'s words."""
    a = ta.answer(
        nature="profession", turnover_paise=60 * LAKH, financial_year=FY,
        cash_receipts_paise=0, cash_payments_paise=0, total_payments_paise=40 * LAKH,
    )
    assert a.required is True
    assert a.enhanced_limit_applied is False
    assert a.threshold_applied_paise == 50 * LAKH


def test_the_profession_answer_says_the_seventy_five_lakh_figure_is_a_different_section():
    """Finance Act 2023 raised §44ADA's PRESUMPTIVE receipts limit to 75 lakh.
    It did not move §44AB(b). The browser module's own comment said otherwise,
    which is why the sentence is on every professional answer."""
    a = ta.answer(nature="profession", turnover_paise=60 * LAKH, financial_year=FY)
    assert any("44ADA" in c and "75 lakh" in c for c in a.caveats)


def test_the_registry_agrees_with_presumptive_on_the_seventy_five_lakh_figure():
    """Reconciliation, not duplication: presumptive.py holds 75 lakh as
    §44ADA's ENHANCED limit, which is the reading this module states."""
    from domain.income_tax.presumptive import limits_for
    p = limits_for("2025-26")
    assert p.s44ada_enhanced_receipts_limit_paise == 75 * LAKH
    assert p.s44ada_receipts_limit_paise == 50 * LAKH
    assert ta.thresholds_for("2025-26").profession_limit_paise == 50 * LAKH


def test_the_cash_percentage_matches_the_one_presumptive_already_holds():
    from domain.income_tax.presumptive import limits_for
    assert (ta.thresholds_for("2025-26").enhanced_limit_cash_percent
            == limits_for("2025-26").enhanced_limit_cash_receipts_percent)


# ── What is refused, and what is named ───────────────────────────────────────

def test_every_answer_names_the_three_limbs_it_does_not_test():
    """Including a "not required" one. §44AB is not exhausted by (a) and (b),
    and an answer that reads as if it were is the one a CA would rely on."""
    for a in (ta.answer(nature="business", turnover_paise=10 * LAKH, financial_year=FY),
              ta.answer(nature="profession", turnover_paise=90 * LAKH, financial_year=FY)):
        joined = " ".join(a.limbs_not_tested)
        assert "44AB(c)" in joined
        assert "44AB(d)" in joined
        assert "44AB(e)" in joined
        assert len(a.limbs_not_tested) == 3


def test_no_year_claims_to_be_verified_against_a_finance_act():
    """Egress is refused here, so nothing was read off one. The same contract
    as domain/tds/section_195_rates.py."""
    assert ta.LATEST_VERIFIED_FY is None
    assert all(not t.verified for t in ta.THRESHOLDS_BY_FY.values())


def test_an_unverified_year_says_so_on_the_answer():
    a = ta.answer(nature="business", turnover_paise=2 * CRORE, financial_year=FY)
    assert any("not been confirmed" in c for c in a.caveats)


def test_a_year_the_registry_does_not_hold_is_named_rather_than_silently_substituted():
    """The fallback trap CLAUDE.md records: a missing year comes back with
    another year's figures. The answer states which year it used."""
    a = ta.answer(nature="business", turnover_paise=2 * CRORE, financial_year="2031-32")
    assert a.financial_year == "2025-26"
    assert any("No §44AB figures are held for FY 2031-32" in c for c in a.caveats)


def test_a_negative_turnover_is_refused():
    with pytest.raises(ValueError):
        ta.answer(nature="business", turnover_paise=-1, financial_year=FY)


# ── The form the report goes on ──────────────────────────────────────────────

def test_a_company_files_3CA_because_its_accounts_are_audited_under_another_law():
    a = ta.answer(nature="business", turnover_paise=5 * CRORE, financial_year=FY,
                  is_company=True)
    assert a.form_type == "3CA-3CD"
    assert any("Companies Act 2013 §139" in c for c in a.caveats)


def test_everyone_else_files_3CB():
    a = ta.answer(nature="profession", turnover_paise=60 * LAKH, financial_year=FY)
    assert a.form_type == "3CB-3CD"


def test_no_form_where_no_audit_is_required():
    a = ta.answer(nature="business", turnover_paise=10 * LAKH, financial_year=FY)
    assert a.form_type is None


# ── The endpoint ─────────────────────────────────────────────────────────────

def _client():
    """The router alone, with the auth dependency overridden — the same shape
    as tests/test_r3_1b_capital_gains_endpoints.py, which exercises the
    capital-gains endpoints in this router."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.auth import get_current_user
    import routers.income_tax as income_tax_mod

    app = FastAPI()
    app.include_router(income_tax_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "firm_id": "F1", "role": "Partner", "email": "p1@f1.test"}
    return TestClient(app, raise_server_exceptions=False)


def test_the_endpoint_answers_and_carries_both_dates_when_an_audit_applies():
    r = _client().get("/api/income-tax/tax-audit/applicability",
                      params={"nature": "profession", "turnover_paise": 60 * LAKH,
                              "financial_year": "2026-27"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    d = body["data"]
    assert d["required"] is True
    assert d["clause"] == "44AB(b)"
    # Explanation (ii) to §44AB — one month before the §139(1) date, DERIVED
    # from compliance_engine rather than restated here.
    assert d["report_due_date"] == "2027-09-30"
    assert d["return_due_date"] == "2027-10-31"


def test_the_endpoint_carries_no_dates_where_no_audit_is_required():
    r = _client().get("/api/income-tax/tax-audit/applicability",
                      params={"nature": "business", "turnover_paise": 60 * LAKH,
                              "financial_year": "2026-27"})
    d = r.json()["data"]
    assert d["required"] is False
    assert d["report_due_date"] is None
    assert d["return_due_date"] is None


def test_the_endpoint_refuses_a_nature_it_does_not_recognise():
    r = _client().get("/api/income-tax/tax-audit/applicability",
                      params={"nature": "guess", "turnover_paise": 5 * CRORE})
    body = r.json()
    assert body["success"] is False
    assert "fact about the client" in body["error"]


def test_the_endpoint_carries_the_proviso_through():
    r = _client().get("/api/income-tax/tax-audit/applicability",
                      params={"nature": "business", "turnover_paise": 4 * CRORE,
                              "financial_year": "2026-27",
                              "cash_receipts_paise": 2 * LAKH,
                              "cash_payments_paise": 1 * LAKH,
                              "total_payments_paise": 3 * CRORE})
    d = r.json()["data"]
    assert d["enhanced_limit_applied"] is True
    assert d["required"] is False


def test_the_two_report_dates_are_the_ones_compliance_engine_gives():
    """DERIVED, not restated — a CBDT extension of the §139(1) date has to
    move the report date with it, which is why compliance_engine owns both."""
    from services import compliance_engine as ce
    r = _client().get("/api/income-tax/tax-audit/applicability",
                      params={"nature": "business", "turnover_paise": 5 * CRORE,
                              "financial_year": "2025-26"})
    d = r.json()["data"]
    assert d["report_due_date"] == ce.tax_audit_report_due_date(2026).isoformat()
    assert d["return_due_date"] == ce.itr_due_date(2026, is_audit=True).isoformat()
