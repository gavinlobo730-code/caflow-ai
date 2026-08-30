"""
Income Tax computation — Financial Year selector regression tests (H6).

The frontend's tax computation page had a working FY dropdown wired correctly
into every OTHER call on the page (snapshots, disallowances) but omitted `fy`
entirely from the POST body sent to /api/income-tax/compute — so the engine
always fell back to today's-date-derived current FY regardless of what the
user had selected, silently mislabeling the saved snapshot with the wrong
FY's numbers.

The backend (ComputeITRRequest.fy -> ITRComputeRequest.fy -> rates_for(fy))
already threaded an explicit fy through correctly; these tests pin that
contract at the router layer so a future regression here is caught, and the
frontend fix (routers/income_tax.py's caller in
apps/web/app/clients/[id]/tax/computation/page.tsx) has something to prove
itself against below the browser layer.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routers.income_tax as it_router
from routers.income_tax import ComputeITRRequest
from domain.income_tax.statutory_rates import current_fy, RATES_BY_FY

CALLER = {"firm_id": "firm-1", "id": "u1"}


def _compute(**overrides):
    payload = {"gross_salary_paise": 12_00_000_00, "use_new_regime": True}
    payload.update(overrides)
    return it_router.compute_itr(ComputeITRRequest(**payload), CALLER)


def test_omitted_fy_defaults_to_current_fy():
    result = _compute()
    assert result["data"]["fy"] == current_fy()


def test_explicit_previous_fy_is_respected():
    result = _compute(fy="2025-26")
    assert result["data"]["fy"] == "2025-26"
    assert result["data"]["rates_verified"] == RATES_BY_FY["2025-26"].verified


def test_explicit_fy_override_is_not_silently_replaced_by_current_fy():
    """The exact H6 regression: an explicitly-selected FY must reach the
    engine and be reflected in the response verbatim -- never silently
    overridden by today's-date current_fy(), which is what happened when the
    frontend omitted `fy` from the request body entirely."""
    explicit_fy = "2025-26"
    result = _compute(fy=explicit_fy)
    assert result["data"]["fy"] == explicit_fy
    # Only a meaningful regression guard if "today" isn't already 2025-26 —
    # true for any date from 2026-04-01 onward (Indian FY runs Apr-Mar).
    if current_fy() != explicit_fy:
        assert result["data"]["fy"] != current_fy()


def test_two_different_explicit_fys_produce_different_responses():
    r1 = _compute(fy="2025-26")
    r2 = _compute(fy="2026-27")
    assert r1["data"]["fy"] == "2025-26"
    assert r2["data"]["fy"] == "2026-27"
    assert r1["data"]["rates_verified"] != r2["data"]["rates_verified"]


# ── The picker may only offer years the engine can actually compute ──────────

def test_supported_years_are_exactly_what_the_rate_registry_holds():
    """The dead-control rule, applied to a dropdown.

    The workspace's picker was a hard-coded ["2025-26", "2024-25", "2023-24"]
    while RATES_BY_FY held two years, neither of them the last two. Selecting
    FY 2024-25 or FY 2023-24 therefore computed at FY 2025-26 rates — rates_for
    falls back to LATEST_VERIFIED_FY for anything unregistered — and the screen
    discarded the `fy` the engine honestly returned, so nothing said so.

    The list now comes from the registry itself, which is the only thing that
    knows. If a year is added or removed, the picker follows without an edit
    here or in the browser."""
    out = it_router.supported_financial_years({"role": "Partner", "firm_id": "F1"})
    assert out["success"] is True
    offered = {row["fy"] for row in out["data"]["financial_years"]}
    assert offered == set(RATES_BY_FY.keys()), (
        "the picker would offer a year the engine has no rates for, or hide "
        "one it does"
    )


def test_each_offered_year_declares_whether_its_rates_are_confirmed():
    """A year carried forward pending the Finance Act is computable but not
    settled, and a CA needs to know which they are looking at."""
    out = it_router.supported_financial_years({"role": "Partner", "firm_id": "F1"})
    for row in out["data"]["financial_years"]:
        assert row["verified"] == RATES_BY_FY[row["fy"]].verified


def test_the_current_year_is_named_so_the_picker_can_default_to_it():
    out = it_router.supported_financial_years({"role": "Partner", "firm_id": "F1"})
    assert out["data"]["current_fy"] == current_fy()


def test_an_unregistered_year_still_reports_the_year_it_actually_used():
    """The engine's own honesty, pinned. The substitution is defensible for a
    FUTURE year; what was not defensible was the screen hiding it."""
    from domain.income_tax.itr_engine import ITREngine, ITRComputeRequest
    r = ITREngine().compute(ITRComputeRequest(gross_salary_paise=10_00_000_00,
                                              fy="2019-20"))
    assert r.fy in RATES_BY_FY
    assert r.fy != "2019-20", (
        "a year with no rate table cannot report itself as the year computed"
    )
