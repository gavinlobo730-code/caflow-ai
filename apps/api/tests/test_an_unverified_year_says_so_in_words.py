"""TDS-INCOME-TAX-19 — an unverified year is loud in every computation response.

`_stamp_rate_provenance` wrote a sentence only when the requested FY differed
from the year whose rates were used. FY 2026-27 is held in the registry as an
unverified copy of FY 2025-26, so the engine answered `rates_verified: False`
with `warnings: []` — and a CA reading the words rather than the flag saw
nothing. The same gap is asserted closed on the TDS side (`fy_rate_gap`).
"""
import pytest

from domain.income_tax.itr_engine import ITREngine, ITRComputeRequest
from domain.income_tax.statutory_rates import RATES_BY_FY, LATEST_VERIFIED_FY
from domain.tds import section_rates as tds


def _compute(fy, **over):
    return ITREngine().compute(ITRComputeRequest(
        fy=fy, gross_salary_paise=15_00_000_00, **over))


# ── the premise: the registry really does hold an unverified year ────────────

def test_the_registry_holds_a_year_that_is_unverified():
    """Guard. If no such year existed the cases below would be vacuous."""
    unverified = [fy for fy, r in RATES_BY_FY.items() if not r.verified]
    assert unverified, "no unverified year in the registry — these tests prove nothing"
    assert LATEST_VERIFIED_FY not in unverified


# ── the income-tax engine ────────────────────────────────────────────────────

def test_a_held_but_unverified_year_carries_a_warning_naming_it():
    for fy in [fy for fy, r in RATES_BY_FY.items() if not r.verified]:
        r = _compute(fy)
        assert r.rates_verified is False
        assert r.warnings, f"FY {fy}: rates_verified is False and warnings is empty"
        joined = " ".join(r.warnings)
        assert f"FY {fy}" in joined
        assert LATEST_VERIFIED_FY in joined, "it must say which year the figures came from"


def test_the_verified_year_carries_no_provenance_warning():
    r = _compute(LATEST_VERIFIED_FY)
    assert r.rates_verified is True
    assert not [w for w in r.warnings if "carried forward" in w or "No rates are held" in w]


def test_a_year_the_registry_does_not_hold_still_gets_its_own_sentence():
    """The older branch is untouched and is a DIFFERENT sentence: a substitution
    and a carry-forward are different problems."""
    r = _compute("2019-20")
    assert r.rates_verified is False
    assert any("No rates are held for FY 2019-20" in w for w in r.warnings)
    assert not any("carried forward" in w for w in r.warnings)


def test_the_two_unverified_sentences_are_not_interchangeable():
    held = " ".join(_compute("2026-27").warnings)
    missing = " ".join(_compute("2019-20").warnings)
    assert held != missing
    assert "carried forward" in held
    assert "No rates are held" in missing


def test_an_entity_computation_says_it_too():
    """The firm / LLP / company branch stamps through the same function."""
    r = ITREngine().compute(ITRComputeRequest(
        fy="2026-27", assessee_kind="firm", business_income_paise=50_00_000_00))
    assert r.rates_verified is False
    assert any("FY 2026-27" in w for w in r.warnings)


# ── the TDS registry already has the sentence; hold it ───────────────────────

def test_tds_names_an_unverified_year_and_is_silent_on_the_verified_one():
    assert tds.fy_rate_gap("2026-27") is not None
    assert "FY 2026-27" in tds.fy_rate_gap("2026-27")
    assert tds.fy_rate_gap(tds.LATEST_VERIFIED_TDS_FY) is None


def test_tds_tells_a_substituted_year_apart_from_a_carried_forward_one():
    assert tds.fy_rate_gap("2019-20") != tds.fy_rate_gap("2026-27")
