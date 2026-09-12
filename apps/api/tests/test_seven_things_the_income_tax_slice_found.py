"""
IT-21, IT-07, IT-29, IT-30, PAY-04 and FA-04 — from the 12 September probe pass.
(IT-34, the debounce, is frontend-only and is asserted in apps/web.)

Six defects, and four of them are latent-but-real: a wrong answer nothing
reaches yet, on a path that will be reached.

  IT-21  compute_amt had no regime parameter, so §115BAC's disapplication of
         Chapter XII-BA could not be expressed at all.
  IT-07  it surcharged every non-corporate assessee at the FIRM's single
         12%-above-₹1-crore bracket, including individuals whose ladder runs
         to 37%.
  IT-29  the CII fallback was invisible: a sale in an FY whose index is not
         yet notified was indexed at the newest known one and the figure was
         written into the register as if it were computed.
  IT-30  `POST /itr/snapshots/{id}/review` had no caller, so every snapshot
         was permanently "draft" — and the filing workflow never asked.
  PAY-04 two payroll_runs reads had no status predicate, so a DRAFT run
         counted as tax already deducted and as an ESI contribution made.
  FA-04  a first depreciation posting forecloses every earlier month and said
         nothing about it.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from domain.income_tax import minimum_tax as mt
from domain.income_tax.capital_gains_engine import (
    CII_BY_FY, cii_for, cii_is_notified, compute_capital_gains,
)

WEB = Path("../web")


# ── IT-21: §115BAC disapplies Chapter XII-BA ─────────────────────────────────

def test_the_new_regime_disapplies_amt_for_an_individual():
    r = mt.compute_amt(adjusted_total_income_paise=5_00_00_000_00,
                       assessee="individual", claimed_specified_deduction=True,
                       fy="2025-26", regime="new")
    assert r.applies is False
    assert r.minimum_tax_paise == 0
    assert "§115BAC" in r.reasons[0]


@pytest.mark.parametrize("assessee", ["individual", "huf", "aop", "boi",
                                      "artificial_juridical_person"])
def test_every_assessee_115bac_reaches_is_covered(assessee):
    r = mt.compute_amt(adjusted_total_income_paise=5_00_00_000_00,
                       assessee=assessee, claimed_specified_deduction=True,
                       fy="2025-26", regime="new")
    assert r.applies is False


@pytest.mark.parametrize("assessee", ["firm", "llp"])
def test_a_firm_or_llp_is_outside_115bac_so_the_regime_cannot_waive_amt(assessee):
    """§115BAC(1A) reaches an individual, HUF, AOP, BOI or artificial juridical
    person. A firm and an LLP are taxed at a flat 30% with no regime to choose,
    so `regime="new"` on one is meaningless and must not waive the tax."""
    r = mt.compute_amt(adjusted_total_income_paise=5_00_00_000_00,
                       assessee=assessee, claimed_specified_deduction=True,
                       fy="2025-26", regime="new")
    assert r.applies is True
    assert r.minimum_tax_paise > 0


def test_the_old_regime_still_charges_amt():
    r = mt.compute_amt(adjusted_total_income_paise=5_00_00_000_00,
                       assessee="individual", claimed_specified_deduction=True,
                       fy="2025-26", regime="old")
    assert r.applies is True


def test_the_default_regime_is_the_one_in_which_amt_can_arise():
    """"old" is the parameter default and not a claim about which regime is
    more common — since AY 2024-25 §115BAC is the default. It is the default
    here because a caller that has not thought about the regime is asking the
    question that has an answer."""
    explicit = mt.compute_amt(adjusted_total_income_paise=5_00_00_000_00,
                              assessee="individual",
                              claimed_specified_deduction=True,
                              fy="2025-26", regime="old")
    implicit = mt.compute_amt(adjusted_total_income_paise=5_00_00_000_00,
                              assessee="individual",
                              claimed_specified_deduction=True, fy="2025-26")
    assert implicit == explicit


def test_the_itr_engine_passes_the_regime_it_already_knows():
    import inspect
    from domain.income_tax import itr_engine
    src = inspect.getsource(itr_engine)
    assert 'regime="new" if req.use_new_regime else "old"' in src


# ── IT-07: the surcharge ladder is the assessee's own ────────────────────────

def _amt_surcharge(assessee: str, income_paise: int) -> int:
    return mt.compute_amt(adjusted_total_income_paise=income_paise,
                          assessee=assessee, claimed_specified_deduction=True,
                          fy="2025-26", regime="old").surcharge_paise


def test_an_individual_is_not_surcharged_at_the_firms_rate():
    """At ₹6 crore the individual ladder is 37% and the firm's single bracket
    is 12% — 25 percentage points of the AMT, on a figure that decides whether
    the minimum tax or the ordinary tax is payable."""
    individual = _amt_surcharge("individual", 6_00_00_000_00)
    firm = _amt_surcharge("firm", 6_00_00_000_00)
    assert individual > firm
    # 18.5% of ₹6 crore is ₹1,11,00,000; 37% of that is ₹41,07,000.
    assert individual == 41_07_000_00
    assert firm == 13_32_000_00


def test_a_firm_keeps_its_own_single_bracket():
    """The 12%-above-₹1-crore bracket is right for a firm and stays."""
    assert _amt_surcharge("firm", 50_00_000_00) == 0
    assert _amt_surcharge("firm", 2_00_00_000_00) > 0


def test_an_llp_is_surcharged_like_a_firm_and_not_like_an_individual():
    assert _amt_surcharge("llp", 6_00_00_000_00) == _amt_surcharge("firm", 6_00_00_000_00)


# ── IT-29: an estimated index says so ────────────────────────────────────────

def test_a_notified_year_is_not_flagged():
    r = compute_capital_gains("property", date(2015, 5, 1), date(2025, 5, 1),
                              10_00_000_00, 30_00_000_00)
    assert r.indexation_is_estimated is False
    assert r.indexation_note == ""


def test_an_unnotified_sale_year_is_flagged_and_named():
    future = max(CII_BY_FY)
    beyond = f"{int(future[:4]) + 2}"
    r = compute_capital_gains("property", date(2015, 5, 1),
                              date(int(beyond), 5, 1), 10_00_000_00, 30_00_000_00)
    assert r.indexation_is_estimated is True
    assert "not notified" in r.indexation_note
    assert "overstates the gain" in r.indexation_note


def test_the_flag_is_a_different_fact_from_the_slab_estimate():
    """`is_slab_rate_estimate` is about the RATE. This is about the INDEX. A
    figure can be either, both or neither."""
    r = compute_capital_gains("property", date(2015, 5, 1), date(2025, 5, 1),
                              10_00_000_00, 30_00_000_00)
    assert r.is_slab_rate_estimate is False and r.indexation_is_estimated is False


def test_cii_is_notified_answers_what_cii_for_cannot():
    """`cii_for` returns an int either way — a missing year is not an error,
    it is a confidently wrong number."""
    assert cii_is_notified("2025-26") is True
    assert cii_is_notified("2099-00") is False
    assert cii_for("2099-00") == CII_BY_FY[max(CII_BY_FY)]


def test_the_register_stores_nothing_rather_than_a_provisional_index():
    src = Path("routers/income_tax.py").read_text()
    assert '"indexed_cost_paise": (None if result.indexation_is_estimated' in src, (
        "nothing recomputes a stored row, so an index written from an "
        "unnotified year is wrong the moment the notification lands — and "
        "wrong in the direction that overstates the gain")


def test_the_response_carries_the_flag_so_the_screen_can_say_so():
    src = Path("routers/income_tax.py").read_text()
    assert '"indexation_is_estimated": r.indexation_is_estimated' in src
    assert '"indexation_note": r.indexation_note' in src


# ── IT-30: the review endpoint is reachable, and the filing asks ─────────────

def test_the_computation_screen_marks_a_snapshot_reviewed():
    page = (WEB / "app/clients/[id]/tax/computation/page.tsx").read_text()
    assert "/api/itr/snapshots/${snapshotId}/review" in page, (
        "the endpoint had no caller at all, so every snapshot's status was "
        "permanently 'draft' while this very panel rendered a green tick for "
        "'reviewed' — a state it had no way to reach")
    assert "Mark reviewed" in page


def test_a_filing_cannot_leave_draft_on_an_unreviewed_computation():
    from domain.income_tax import computation_workspace as cw
    from domain.income_tax import itr_workflow as wf
    cw._MOCK_SNAPSHOTS["snap-1"] = {"id": "snap-1", "firm_id": "F", "status": "draft"}
    wf._MOCK_FILINGS["fil-1"] = {
        "id": "fil-1", "firm_id": "F", "status": "draft",
        "computation_snapshot_id": "snap-1"}
    try:
        with pytest.raises(ValueError) as exc:
            wf.transition_itr_status("F", "fil-1", "review", "u1")
        assert "still 'draft'" in str(exc.value)
    finally:
        cw._MOCK_SNAPSHOTS.pop("snap-1", None)
        wf._MOCK_FILINGS.pop("fil-1", None)


def test_a_reviewed_computation_lets_the_filing_move():
    from domain.income_tax import computation_workspace as cw
    from domain.income_tax import itr_workflow as wf
    cw._MOCK_SNAPSHOTS["snap-2"] = {"id": "snap-2", "firm_id": "F", "status": "reviewed"}
    wf._MOCK_FILINGS["fil-2"] = {
        "id": "fil-2", "firm_id": "F", "status": "draft",
        "computation_snapshot_id": "snap-2"}
    try:
        out = wf.transition_itr_status("F", "fil-2", "review", "u1")
        assert out["status"] == "review"
    finally:
        cw._MOCK_SNAPSHOTS.pop("snap-2", None)
        wf._MOCK_FILINGS.pop("fil-2", None)


def test_a_filing_that_pins_no_snapshot_is_allowed_through():
    """`computation_snapshot_id` is nullable and always has been. A CA who
    computed outside this product and is recording the return here has no
    snapshot to pin, and refusing them would make the pin mandatory by
    accident."""
    from domain.income_tax import itr_workflow as wf
    wf._MOCK_FILINGS["fil-3"] = {"id": "fil-3", "firm_id": "F", "status": "draft"}
    try:
        assert wf.transition_itr_status("F", "fil-3", "review", "u1")["status"] == "review"
    finally:
        wf._MOCK_FILINGS.pop("fil-3", None)


def test_the_check_runs_only_on_the_way_out_of_draft():
    """Re-asking it in review would block the review → draft step a reviewer
    uses to send a return back."""
    from domain.income_tax import computation_workspace as cw
    from domain.income_tax import itr_workflow as wf
    cw._MOCK_SNAPSHOTS["snap-4"] = {"id": "snap-4", "firm_id": "F", "status": "draft"}
    wf._MOCK_FILINGS["fil-4"] = {
        "id": "fil-4", "firm_id": "F", "status": "review",
        "computation_snapshot_id": "snap-4"}
    try:
        assert wf.transition_itr_status("F", "fil-4", "draft", "u1")["status"] == "draft"
    finally:
        cw._MOCK_SNAPSHOTS.pop("snap-4", None)
        wf._MOCK_FILINGS.pop("fil-4", None)


# ── PAY-04: a draft run has deducted nothing ─────────────────────────────────

class _RunsDB:
    """The narrowest double that answers one question: which payroll_runs rows
    does the caller ask for? Not a general FakeDB — the point is the PREDICATE,
    and a double that ignores it could not show the defect."""

    def __init__(self, rows):
        self._rows = rows
        self._filters: dict = {}
        self._in: dict = {}
        #: The run ids the caller went on to fetch slips for. Empty means the
        #: run was filtered out — which is the whole assertion.
        self.slips_asked_for: list = []

    def table(self, name):
        assert name in ("payroll_runs", "payroll_slips")
        self._name = name
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def in_(self, col, vals):
        self._in[col] = list(vals)
        return self

    def execute(self):
        if self._name == "payroll_slips":
            self.slips_asked_for.extend(self._in.get("run_id", []))
            self._filters, self._in = {}, {}
            return type("R", (), {"data": []})()
        out = [r for r in self._rows
               if all(r.get(k) == v for k, v in self._filters.items())
               and all(r.get(k) in v for k, v in self._in.items())]
        self._filters, self._in = {}, {}
        return type("R", (), {"data": out})()


def _runs(*statuses):
    return [{"id": f"run-{i}", "firm_id": "F", "client_id": "C",
             "month": "2026-08", "status": st}
            for i, st in enumerate(statuses)]


def test_the_esi_continuation_read_ignores_a_draft_run():
    """ESI Rule 50's continuation applies to someone who WAS covered when the
    period began. A DRAFT run deducted nothing and remitted nothing, so its
    slips are not contributions — and without the filter a draft later
    discarded keeps somebody in past the ₹21,000 ceiling on the strength of a
    deduction that never happened."""
    import routers.payroll as pr
    db = _RunsDB(_runs("draft"))
    assert pr._members_contributing_earlier_this_period(db, "F", "C", "2026-09") == set()


def test_the_esi_continuation_read_sees_a_released_one():
    """The counterpart, and the reason the double records what it was asked
    for: an empty ANSWER proves nothing on its own — the function returns the
    empty set both when it filtered the run out and when the run had no
    contributing slips. What separates them is whether the slips were fetched
    at all."""
    import routers.payroll as pr
    for released in pr._PAYROLL_RELEASED:
        db = _RunsDB(_runs(released))
        pr._members_contributing_earlier_this_period(db, "F", "C", "2026-09")
        assert db.slips_asked_for == ["run-0"], (
            f"a {released!r} run must reach the slips read")

    draft = _RunsDB(_runs("draft"))
    pr._members_contributing_earlier_this_period(draft, "F", "C", "2026-09")
    assert draft.slips_asked_for == []


def test_the_released_statuses_are_the_shared_pair():
    """Not a third spelling of the same idea: tds_return_service names the same
    pair _PAYROLL_POSTED, and migration 323 made RLS agree."""
    import routers.payroll as pr
    assert set(pr._PAYROLL_RELEASED) == {"finalized", "paid"}


# ── FA-04: a first posting says what it forecloses ───────────────────────────

def test_the_first_posting_warns_about_the_months_it_forecloses():
    src = Path("routers/fixed_assets.py").read_text()
    assert "foreclosed_months" in src
    assert "foreclosure_notice" in src


def test_it_is_a_warning_and_not_a_refusal():
    """`test_the_first_ever_posting_may_start_at_any_month` pins the other
    half, correctly: an asset brought over from Tally mid-life already carries
    its accumulated depreciation and its first posting here is whatever month
    the CA takes over in. Refusing the skip would refuse every migrated asset,
    so this is the Rule 46(b) shape — warn, and say what it costs."""
    src = Path("routers/fixed_assets.py").read_text()
    start = src.index("foreclosed: list[str] = []")
    block = src[start:src.index("\n\n", start)]
    assert "raise HTTPException" not in block
    assert "_months_missing_before(purchase_month, period)" in block


def test_the_screen_renders_the_notice_as_a_warning_not_an_error():
    page = (WEB / "app/clients/[id]/fixed-assets/page.tsx").read_text()
    assert "foreclosure_notice" in page
    assert "notices[r.asset_id]" in page
    assert "text-amber-700" in page[page.index("notices[r.asset_id]") - 200:
                                    page.index("notices[r.asset_id]") + 200]
