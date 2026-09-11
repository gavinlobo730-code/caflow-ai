"""FA-02 — an asset whose depreciation basis is not one Schedule II prescribes.

WHAT THE RISK ACTUALLY IS

`wdv_rate_percent` is what every charge the asset will ever produce is computed
from. Rows written before that rate was derived from Schedule II Part C carry
INCOME-TAX ACT block rates instead — Furniture at 10% where Part C gives 25.89%,
Intangibles at 25% — and every one of them under-depreciates for the life of the
asset. Nothing recomputed them and nothing reported them.

WHY THIS REPORTS RATHER THAN MIGRATING

A backfill is the obvious fix and the wrong one. **Schedule II Part A expressly
permits a company to use a different useful life or residual value**, provided
the difference is disclosed in the accounts and justified. So a rate off the
table is not necessarily an error — it may be a judgement somebody has to
disclose, and the schema does not distinguish the two. A migration would
silently overwrite the judgement, change the depreciation charge, and move the
profit.

So it is named, on the endpoint that already reports rather than repairs, and
the CA corrects it (PATCH /{asset_id}, a Tier C field) or discloses it.

THE SUBTLETY THAT WOULD OTHERWISE PRODUCE FALSE FINDINGS

Conforming means matching ANY class the category offers, not the default one.
Schedule II gives several lives per category, and a CA picking the second has
chosen from the table rather than departed from it.
"""
from __future__ import annotations

import pytest

from routers.fixed_assets import SCHEDULE_II_CATEGORIES, schedule_ii_departure

FURNITURE = "Furniture & Fixtures"


def _asset(**over) -> dict:
    base = dict(asset_code="FA-0001", asset_name="Office desks",
                asset_category=FURNITURE, depreciation_method="WDV",
                wdv_rate_percent=25.89, useful_life_years=10, is_disposed=False)
    base.update(over)
    return base


# ── the defect this exists for ───────────────────────────────────────────────

def test_the_income_tax_block_rate_is_named():
    """10% on furniture is the Income-tax Act block rate that used to sit under
    a field labelled "Companies Act 2013 Sch II rate". Part C gives 25.89%."""
    found = schedule_ii_departure(_asset(wdv_rate_percent=10.00))
    assert found is not None
    assert found["kind"] == "depreciation_basis_departs_from_schedule_ii"
    assert found["field"] == "wdv_rate_percent"
    assert found["stored"] == 10.00
    assert 25.89 in found["schedule_ii_prescribes"]
    assert "disclosed" in found["what_it_means"]


def test_the_finding_names_the_asset_so_a_ca_can_act_on_it():
    found = schedule_ii_departure(_asset(wdv_rate_percent=10.00))
    assert found["asset_code"] == "FA-0001"
    assert found["asset_name"] == "Office desks"
    assert found["asset_category"] == FURNITURE


# ── what must NOT be reported ────────────────────────────────────────────────

def test_the_category_default_conforms():
    assert schedule_ii_departure(_asset()) is None


def test_a_non_default_class_from_the_same_table_also_conforms():
    """THE FALSE-POSITIVE THIS TURNS ON. Furniture offers 10 years (25.89%) and
    8 years (31.23%). A CA on the second has chosen from Schedule II."""
    other = [c for c in SCHEDULE_II_CATEGORIES[FURNITURE]][1]
    assert schedule_ii_departure(
        _asset(wdv_rate_percent=float(other["wdv_rate_percent"]))) is None


def test_land_is_not_a_departure():
    """Schedule II never depreciates land, so 0.00 is the definite right answer
    rather than a missing one."""
    assert schedule_ii_departure(
        _asset(asset_category="Land", wdv_rate_percent=0.00)) is None


@pytest.mark.parametrize("category", ["Intangibles", "Other", "Nonsense Category"])
def test_a_category_schedule_ii_prescribes_nothing_for_cannot_depart(category):
    """Intangibles are amortised under AS 26 / Ind AS 38 — a judgement, not a
    figure this table supplies. There is no prescribed basis to depart FROM, and
    the create path already refuses those without an explicit figure."""
    assert schedule_ii_departure(
        _asset(asset_category=category, wdv_rate_percent=25.00)) is None


def test_an_asset_with_no_rate_recorded_is_not_a_departure():
    """Absent is not wrong. Creation refuses a missing rate where one is needed,
    so a null here is a row from before that guard, and 'no basis' is a
    different finding from 'a basis off the table'."""
    assert schedule_ii_departure(_asset(wdv_rate_percent=None)) is None


# ── straight line is judged on the LIFE, not the rate ────────────────────────

def test_straight_line_conforms_on_a_prescribed_life():
    assert schedule_ii_departure(
        _asset(depreciation_method="SL", useful_life_years=10)) is None


def test_straight_line_departs_on_a_life_the_table_does_not_give():
    found = schedule_ii_departure(
        _asset(depreciation_method="SL", useful_life_years=7))
    assert found is not None
    assert found["field"] == "useful_life_years"
    assert found["stored"] == 7
    assert 10 in found["schedule_ii_prescribes"]


def test_the_method_decides_which_field_is_judged():
    """An SL asset carrying a stale WDV rate is not a departure: the rate is not
    what its charge is computed from."""
    assert schedule_ii_departure(_asset(
        depreciation_method="SL", useful_life_years=10,
        wdv_rate_percent=10.00)) is None


# ── the wiring ───────────────────────────────────────────────────────────────

def test_the_register_integrity_endpoint_actually_calls_it():
    """A check nothing calls is a check that does not exist.

    register-integrity short-circuits in mock mode (no database), so the call
    itself cannot be exercised here — and that is exactly the failure worth
    guarding: a function written, reviewed, merged and never reached.
    """
    import inspect

    from routers import fixed_assets

    src = inspect.getsource(fixed_assets.register_integrity)
    assert "schedule_ii_departure(" in src, (
        "register-integrity must call the check, or FA-02 is reported nowhere")

    # And it must fetch what the check reads. The endpoint selects an explicit
    # column list; a departure cannot be judged from columns that were not asked
    # for, and the check would silently return None for every asset.
    for column in ("asset_category", "depreciation_method",
                   "wdv_rate_percent", "useful_life_years"):
        assert column in src, f"the select list must include {column}"


def test_a_disposed_asset_is_not_reported():
    """Its basis is settled — the gain or loss was computed from it — so a
    departure there is noise the CA cannot act on. Asserted on the endpoint's
    source for the same reason as above."""
    import inspect

    from routers import fixed_assets

    src = inspect.getsource(fixed_assets.register_integrity)
    assert 'if not a.get("is_disposed"):' in src
