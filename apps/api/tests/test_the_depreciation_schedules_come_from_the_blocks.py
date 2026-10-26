"""POST-A-070 — Schedules DPM, DOA and DEP from the §32 block working, each block on the row of the return the CA recorded for it.

WHAT THE RETURN ASKS AND THE BLOCK REGISTER DID NOT SAY

    Schedule DPM and Schedule DOA are a fixed set of ROWS, each a nature of asset at a rate. The block register (migration 357) holds a
    block's name and rate and not its nature, and §2(11) makes the nature half of a block's identity, so a block cannot be placed on the
    return without a fact only the CA holds. Migration 552 stores it (`itr_schedule_row`), and `domain/income_tax/itr_depreciation_rows`
    reads the vocabulary from the Department's own schema, so this product holds no table of rows or rates.

WHAT THIS FILE HOLDS

    * THE ROWS ARE THE SCHEMA'S: identical across ITR-3, ITR-5 and ITR-6, with the rate the Department printed on each, and a row's
      rate must agree with the block's (a block IS a rate). Land takes only a block recorded at nil.
    * EVERY BOX THE ASSEMBLY FILLS IS A BOX THE ROW HAS, with the engine's own working behind it (the moneys payable bite the
      full-rate part first, the half-rate base is what is left, the allowance is the sum of what each rate gave), and a box the row
      lacks (ITR-6 has no 115BAC adjustment, the 45 per cent row has fewer columns) is simply not filled.
    * A BLOCK THAT CANNOT BE PLACED IS LISTED WITH ITS FIGURES AND THE REASON, never dropped: its depreciation is still in the allowance,
      so the tie-out says the rows and the blocks left off them add to the §32 total.
    * THE WORKING THE ENGINE NOW CARRIES OUT is an identity over any inputs: what it reports for the rates adds to the allowance.
"""
from __future__ import annotations

from datetime import date

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from domain.income_tax import books_schedules as B
from domain.income_tax import itr_depreciation_rows as R
from domain.income_tax import itr_schema
from domain.income_tax.section_32 import Addition, Block, Deletion, compute
from services.section_32_service import block_to_dict
from tests._books_statements import L, balanced_statements

FORMS = list(R.FORMS)
FY_END = date(2026, 3, 31)


def _result(*blocks: Block, rows: dict | None = None) -> dict:
    """What `section_32_service.assemble` serves, built from the engine itself and the service's own dict function."""
    res = compute(list(blocks), fy_end=FY_END)
    rows = rows or {}
    return {
        "blocks": [block_to_dict(b, rows.get(b.key)) for b in res.blocks],
        "depreciation_paise": res.depreciation_paise, "additional_depreciation_paise": res.additional_depreciation_paise,
        "allowance_paise": res.total_allowance_paise, "short_term_capital_gain_paise": res.short_term_capital_gain_paise,
        "statutory_gaps": list(res.gaps), "unclassified_assets": [], "blocks_without_opening_wdv": [],
    }


def _plant() -> Block:
    """Opening 10 lakh; 4 lakh put to use in June (full rate) and 2 lakh in January (half); 1 lakh realised; 20 per cent additional on
    the June machine. Hand-worked below."""
    return Block(key="P&M 15%", rate_percent=15, opening_wdv_paise=10 * L,
                 additions=(Addition("lathe", 4 * L, date(2025, 6, 1), additional_depreciation_eligible=True),
                            Addition("press", 2 * L, date(2026, 1, 10))),
                 deletions=(Deletion("old press", 1 * L),))


def _boxes(row: dict) -> dict:
    return {b["box"]: b["amount_paise"] for b in row["boxes"]}


# ── the rows are the schema's ────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_rows_are_identical_across_the_three_forms_and_carry_the_departments_rates():
    keys = {f: R.keys_for(f) for f in FORMS}
    assert keys["ITR-3"] == keys["ITR-5"] == keys["ITR-6"]
    assert {r.key: r.rate_percent for r in R.rows_for("ITR-3")} == {
        "PlantMachinery.Rate15": 15, "PlantMachinery.Rate30": 30, "PlantMachinery.Rate40": 40, "PlantMachinery.Rate45": 45,
        "Land": None, "Building.Rate5": 5, "Building.Rate10": 10, "Building.Rate40": 40,
        "FurnitureFittings.Rate10": 10, "IntangibleAssets.Rate25": 25, "Ships.Rate20": 20}


def test_a_nature_the_schema_adds_without_a_caption_is_noticed():
    for f in FORMS:
        for r in R.rows_for(f):
            assert r.nature in R.NATURE_CAPTIONS, f"{f}: {r.nature} has no caption; add one (the key is the Department's)"


def test_the_module_holds_no_rate_of_its_own():
    """A rate typed here would be Appendix I by another name. The only integer in the module is the capture group that reads the
    Department's own `Rate15`."""
    import ast
    tree = ast.parse(open(R.__file__).read())
    ints = {c.value for c in ast.walk(tree)
            if isinstance(c, ast.Constant) and isinstance(c.value, int) and not isinstance(c.value, bool)}
    assert ints <= {0, 1}, ints


def test_a_row_must_agree_with_the_blocks_rate():
    plant15, plant30, land = (R.row_by_key("ITR-3", k) for k in ("PlantMachinery.Rate15", "PlantMachinery.Rate30", "Land"))
    assert R.disagreement(plant15, 15) is None
    assert "15 per cent" in R.disagreement(plant30, 15) and "30 per cent" in R.disagreement(plant30, 15)
    assert R.disagreement(land, 0) is None
    assert "not depreciated" in R.disagreement(land, 15)
    assert R.disagreement(plant15, 0) is not None


def test_the_vocabulary_is_what_a_screen_is_served():
    vocab = R.vocabulary()
    assert [v["key"] for v in vocab] == list(R.keys_for("ITR-3"))
    assert all(set(v) == {"key", "schedule", "caption", "rate_percent"} for v in vocab)
    assert {v["schedule"] for v in vocab} == {"ScheduleDPM", "ScheduleDOA"}


def test_a_form_that_carries_no_such_schedule_is_refused():
    for f in ("ITR-1", "ITR-2", "ITR-4", "ITR-7"):
        with pytest.raises(ValueError):
            R.rows_for(f)


@pytest.mark.parametrize("form", FORMS)
def test_every_box_the_assembly_fills_or_names_exists_in_a_row_of_the_form(form):
    union = set().union(*(r.boxes for r in R.rows_for(form)))
    trusted = {b for b, _src, _label, forms in B._DETAIL_FILLED if form in forms}
    by_hand = {n for names, *_ in B._DETAIL_BY_HAND.get(form, ()) for n in names}
    assert trusted <= union, trusted - union
    assert by_hand <= union, by_hand - union
    assert not (trusted & by_hand), "a box is both filled by name and left to the CA"
    assert set(B.NOT_RECORDED_BOXES) - union <= {"Total", "AdjustmentSec115BAC", "AddlnDeprOnAssetLessThan180Days"}


def test_a_name_that_means_different_columns_on_different_forms_is_never_filled_by_name():
    """ITR-3's order is (on 180+, on <180, last year's carry-forward) and ITR-5/6's is (on 180+, during the year, on <180): the same name
    `AddlnDeprOnLessThan180DayAdditions` is the second column on one form and the third on the other."""
    def order(form):
        node = itr_schema.resolve(form, B.root_path(form, "ScheduleDPM.PlantMachinery.Rate15.DepreciationDetail"))
        return [k for k in node["properties"] if k.startswith("Addln")]
    assert order("ITR-3") == ["AddlnDeprOnGT180DayAdditions", "AddlnDeprOnLessThan180DayAdditions", "AddlnDeprOnAssetLessThan180Days"]
    assert order("ITR-5") == order("ITR-6") == ["AddlnDeprOnGT180DayAdditions", "AddlnDeprDuringYearAdditions",
                                                "AddlnDeprOnLessThan180DayAdditions"]
    filled = {(b, tuple(forms)) for b, _s, _l, forms in B._DETAIL_FILLED}
    assert ("AddlnDeprOnLessThan180DayAdditions", ("ITR-3",)) in filled
    assert not any(b in ("AddlnDeprOnLessThan180DayAdditions", "AddlnDeprDuringYearAdditions", "RealizationPeriodDuringYear")
                   and ("ITR-5" in forms or "ITR-6" in forms) for b, _s, _l, forms in B._DETAIL_FILLED)


@pytest.mark.parametrize("form", FORMS)
def test_every_row_has_its_summary_box_in_schedule_dep_except_land(form):
    for r in R.rows_for(form):
        path = B._dep_summary_path(r)
        if r.nature == "Land":
            assert path is None
            continue
        node = itr_schema.resolve(form, B.root_path(form, path))
        assert node is not None and node.get("type") == "integer", f"{form}: {r.key} -> {path}"


@pytest.mark.parametrize("form", FORMS)
def test_every_dep_total_box_is_in_the_schema(form):
    for tail, _label, _natures in B._DEP_TOTALS:
        node = itr_schema.resolve(form, B.root_path(form, f"{B._DEP}.{tail}"))
        assert node is not None and node.get("type") == "integer", (form, tail)


# ── a block on its row ───────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("form", FORMS)
def test_a_block_fills_its_row_from_the_engines_working_hand_computed(form):
    dep = B.depreciation(form, _result(_plant(), rows={"P&M 15%": "PlantMachinery.Rate15"}))
    assert [r["row_key"] for r in dep["rows"]] == ["PlantMachinery.Rate15"] and dep["unplaced"] == []
    box = _boxes(dep["rows"][0])
    assert box["WDVFirstDay"] == 10 * L
    assert box["AdditionsGrThan180Days"] == 4 * L
    assert box["RealizationTotalPeriod"] == 1 * L                    # the moneys payable bite the full-rate part first
    assert box["FullRateDeprAmt"] == 13 * L                          # 10 + 4 - 1
    assert box["AdditionsLessThan180Days"] == 2 * L
    assert box["HalfRateDeprAmt"] == 2 * L
    assert box["DepreciationAtFullRate"] == 1_95_000_00              # 15% of 13 lakh
    assert box["DepreciationAtHalfRate"] == 15_000_00                # 7.5% of 2 lakh
    assert box["AddlnDeprOnGT180DayAdditions"] == 80_000_00          # 20% of the 4 lakh machine
    by_hand = {tuple(h["boxes"]): h["amount_paise"] for h in dep["rows"][0]["to_key_by_hand"]}
    if form == "ITR-3":
        # ITR-3's names say what they are, so they are filled.
        assert box["RealizationPeriodLessThan180days"] == 0
        assert box["AddlnDeprOnLessThan180DayAdditions"] == 0
        assert by_hand == {}
    else:
        # ITR-5 and ITR-6 rename those columns and swap two of them, so the working's figures are SHOWN against the possible boxes and
        # written into none of them.
        assert "RealizationPeriodDuringYear" not in box and "AddlnDeprDuringYearAdditions" not in box
        assert "AddlnDeprOnLessThan180DayAdditions" not in box
        assert by_hand == {("RealizationPeriodDuringYear",): 0,
                           ("AddlnDeprDuringYearAdditions", "AddlnDeprOnLessThan180DayAdditions"): 0}
    assert box["TotalDepreciation"] == 2_90_000_00 == box["NetAggregateDepreciation"]
    assert box["CapGainUs50"] == 0
    assert box["WDVLastDay"] == 12_10_000_00                         # 15 lakh before depreciation, less 2.9 lakh
    assert dep["rows"][0]["allowance_paise"] == 2_90_000_00


def test_the_boxes_filled_are_the_rows_own_and_a_box_the_row_lacks_is_not_filled():
    rows_by_form = {f: R.row_by_key(f, "PlantMachinery.Rate45") for f in FORMS}
    for form in FORMS:
        row = rows_by_form[form]
        dep = B.depreciation(form, _result(Block(key="x", rate_percent=45, opening_wdv_paise=4 * L), rows={"x": row.key}))
        filled = {b["box"] for b in dep["rows"][0]["boxes"]}
        assert filled <= row.boxes
        # The 45 per cent row has no columns for additions, so none is filled even though the engine has the figures.
        assert "AdditionsGrThan180Days" not in filled and "WDVFirstDay" in filled
    # ITR-6 has no 115BAC adjustment box on any plant row; the other two forms do. We fill it on none (it is not recorded), and name it
    # on the schedule only where the form has it.
    for form in FORMS:
        dep = B.depreciation(form, _result(_plant(), rows={"P&M 15%": "PlantMachinery.Rate15"}))
        assert "AdjustmentSec115BAC" not in {b["box"] for b in dep["rows"][0]["boxes"]}
        named = "AdjustmentSec115BAC" in {n["box"] for n in dep["not_recorded"]}
        assert named is (form != "ITR-6")


def test_land_takes_a_block_recorded_at_nil_and_fills_two_boxes():
    block = Block(key="Land", rate_percent=0, opening_wdv_paise=30 * L)
    dep = B.depreciation("ITR-3", _result(block, rows={"Land": "Land"}))
    assert dep["unplaced"] == []
    assert _boxes(dep["rows"][0]) == {"WDVFirstDay": 30 * L, "WDVLastDay": 30 * L}
    assert dep["summary"] == [] and dep["rows"][0]["allowance_paise"] == 0


def test_a_section_50_block_fills_the_gain_and_no_depreciation_base():
    # Moneys payable of 6 lakh against a block worth 5: a 1 lakh short-term capital gain, the block closes at nil, nothing depreciated.
    block = Block(key="old", rate_percent=15, opening_wdv_paise=5 * L, deletions=(Deletion("sold", 6 * L),))
    dep = B.depreciation("ITR-3", _result(block, rows={"old": "PlantMachinery.Rate15"}))
    box = _boxes(dep["rows"][0])
    assert box["CapGainUs50"] == 1 * L and box["WDVLastDay"] == 0 and box["TotalDepreciation"] == 0
    assert box["FullRateDeprAmt"] == 0 and box["HalfRateDeprAmt"] == 0 and box["RealizationTotalPeriod"] == 5 * L


# ── a figure of the working that the row has no box for is listed, with its number ───────────────────────────────────────────────
def _row_of(form: str, *blocks: Block, rows: dict) -> dict:
    return B.depreciation(form, _result(*blocks, rows=rows))


@pytest.mark.parametrize("form", FORMS)
def test_the_45_per_cent_row_names_the_half_rate_figures_it_has_no_columns_for(form):
    # Opening 4 lakh; 2 lakh put to use in June (full rate) and 5 lakh in January (half). At 45 per cent: full-rate base 6 lakh gives
    # 2.70 lakh, half-rate base 5 lakh gives 1.125 lakh at 22.5 per cent, 3.825 lakh in all. The row has the full-rate columns and the
    # total, and nothing for the half-rate base, the half-rate depreciation or the additions, which are written here and not derived.
    block = Block(key="x", rate_percent=45, opening_wdv_paise=4 * L,
                  additions=(Addition("a", 2 * L, date(2025, 6, 1)), Addition("b", 5 * L, date(2026, 1, 10))))
    dep = _row_of(form, block, rows={"x": "PlantMachinery.Rate45"})
    row = dep["rows"][0]
    box = _boxes(row)
    assert box["TotalDepreciation"] == 3_82_500_00 and box["DepreciationAtFullRate"] == 2_70_000_00
    assert {f["label"]: f["amount_paise"] for f in row["figures_without_a_box"]} == {
        "Additions put to use for 180 days or more": 2 * L,
        "Additions put to use for less than 180 days": 5 * L,
        "Amount on which depreciation at half the rate is allowed": 5 * L,
        "Depreciation at half the rate": 1_12_500_00,
    }
    # Said in the answer's own list as well, with the figure, so the schedule does not foot silently.
    assert any("Depreciation at half the rate" in g and "1,12,500.00" in g for g in dep["gaps"])
    # And nothing that HAS a box is listed as lacking one.
    assert not {"Written down value on the first day of the year", "Depreciation at the full rate"} & \
        {f["label"] for f in row["figures_without_a_box"]}


@pytest.mark.parametrize("form", FORMS)
def test_a_row_that_has_every_box_the_working_needs_lists_nothing(form):
    dep = _row_of(form, _plant(), rows={"P&M 15%": "PlantMachinery.Rate15"})
    row = dep["rows"][0]
    # On ITR-5 and ITR-6 two columns are shown by hand (renamed); they are not "without a box".
    assert row["figures_without_a_box"] == [] and row["notes"] == []


@pytest.mark.parametrize("form", FORMS)
def test_the_half_rate_columns_shown_by_hand_on_itr_5_and_6_are_not_reported_as_lacking_a_box(form):
    # Opening 1 lakh; 1 lakh put to use in June and 5 lakh in January (both eligible for additional depreciation); 3 lakh realised. The
    # moneys payable bite the full-rate part first (opening 1 + addition 1 = 2 lakh) and the last lakh comes out of the January addition,
    # so the half-rate realization is 1 lakh and the half-rate additional depreciation is not nil: the two figures ITR-5 and ITR-6 print
    # under renamed columns and this module shows by hand.
    block = Block(key="P&M 15%", rate_percent=15, opening_wdv_paise=1 * L,
                  additions=(Addition("a", 1 * L, date(2025, 6, 1), additional_depreciation_eligible=True),
                             Addition("b", 5 * L, date(2026, 1, 10), additional_depreciation_eligible=True)),
                  deletions=(Deletion("sold", 3 * L),))
    result = _result(block, rows={"P&M 15%": "PlantMachinery.Rate15"})
    worked = result["blocks"][0]
    assert worked["realization_against_half_paise"] == 1 * L and worked["additional_on_half_rate_additions_paise"] > 0
    row = B.depreciation(form, result)["rows"][0]
    assert row["figures_without_a_box"] == [], row["figures_without_a_box"]
    if form == "ITR-3":
        assert _boxes(row)["RealizationPeriodLessThan180days"] == 1 * L
        assert _boxes(row)["AddlnDeprOnLessThan180DayAdditions"] == worked["additional_on_half_rate_additions_paise"]
    else:
        shown = {tuple(h["boxes"]): h["amount_paise"] for h in row["to_key_by_hand"]}
        assert shown[("RealizationPeriodDuringYear",)] == 1 * L
        assert shown[("AddlnDeprDuringYearAdditions", "AddlnDeprOnLessThan180DayAdditions")] == worked["additional_on_half_rate_additions_paise"]


def test_land_with_an_addition_names_the_figures_its_two_boxes_cannot_hold():
    block = Block(key="Land", rate_percent=0, opening_wdv_paise=30 * L, additions=(Addition("plot", 5 * L, date(2025, 6, 1)),))
    row = _row_of("ITR-3", block, rows={"Land": "Land"})["rows"][0]
    assert {f["label"]: f["amount_paise"] for f in row["figures_without_a_box"]} == {
        "Additions put to use for 180 days or more": 5 * L, "Amount on which depreciation at the full rate is allowed": 35 * L}


# ── §50: the moneys payable above the block are told, and the form's column is not decided for the CA ───────────────────────────────
def test_a_section_50_excess_says_what_the_realization_boxes_carry_and_what_they_do_not():
    block = Block(key="old", rate_percent=15, opening_wdv_paise=5 * L, deletions=(Deletion("sold", 6 * L),))
    row = _row_of("ITR-3", block, rows={"old": "PlantMachinery.Rate15"})["rows"][0]
    assert len(row["notes"]) == 1
    note = row["notes"][0]
    assert "₹6,00,000.00" in note and "₹5,00,000.00" in note and "₹1,00,000.00" in note and "CA's to confirm" in note
    assert _boxes(row)["RealizationTotalPeriod"] == 5 * L          # unchanged: the box carries what was set against the block
    # The sentence is in the answer's list of what the CA has to settle too, under the row it is about.
    dep = B.depreciation("ITR-3", _result(block, rows={"old": "PlantMachinery.Rate15"}))
    assert f"{row['caption']}: {note}" in dep["gaps"]
    out = B.assemble(form="ITR-3", assessment_year="2026-27", financial_year="2025-26", statements=balanced_statements(),
                     section_32=_result(block, rows={"old": "PlantMachinery.Rate15"}))
    assert f"{row['caption']}: {note}" in out["gaps"]


def test_a_depreciation_box_the_schema_would_refuse_is_said_on_its_row(monkeypatch):
    # No block can come out under a bound today (every figure of the working is non-negative), so the bound is moved to make the path
    # run: the sentence must reach the row and the answer's list the way a balance sheet box's does.
    monkeypatch.setattr(B, "_form_minimum", lambda form, path: 10 ** 9 if path.endswith(".WDVFirstDay") else None)
    dep = B.depreciation("ITR-3", _result(_plant(), rows={"P&M 15%": "PlantMachinery.Rate15"}))
    row = dep["rows"][0]
    assert any("Written down value on the first day of the year" in n and "accepts nothing below" in n for n in row["notes"])
    assert [b["box"] for b in row["boxes"] if "below_form_minimum" in b] == ["WDVFirstDay"]
    assert any(row["notes"][0] in g for g in dep["gaps"])


@pytest.mark.parametrize("deletion", [0, 1 * L, 5 * L])
def test_no_section_50_note_where_the_moneys_payable_fit_the_block(deletion):
    deletions = (Deletion("sold", deletion),) if deletion else ()
    block = Block(key="old", rate_percent=15, opening_wdv_paise=5 * L, deletions=deletions)
    assert _row_of("ITR-3", block, rows={"old": "PlantMachinery.Rate15"})["rows"][0]["notes"] == []


# ── a block that cannot be placed is listed, not dropped ──────────────────────────────────────────────────────────────────────
def _plan_with(row_for_plant, **extra):
    second = Block(key="Furniture", rate_percent=10, opening_wdv_paise=2 * L)
    rows = {"Furniture": "FurnitureFittings.Rate10", **extra}
    if row_for_plant is not None:
        rows["P&M 15%"] = row_for_plant
    return _result(_plant(), second, rows=rows)


@pytest.mark.parametrize("recorded,why", [
    (None, "No row on the return is recorded"),
    ("Building.Rate99", "is not a row of ITR-3"),
    ("PlantMachinery.Rate30", "30 per cent row"),
])
def test_a_block_with_no_usable_row_is_listed_with_its_figures_and_the_reason(recorded, why):
    result = _plan_with(recorded)
    dep = B.depreciation("ITR-3", result)
    assert [r["block_key"] for r in dep["rows"]] == ["Furniture"]
    [u] = dep["unplaced"]
    assert u["block_key"] == "P&M 15%" and why in u["reason"]
    assert u["allowance_paise"] == 2_90_000_00 and u["closing_wdv_paise"] == 12_10_000_00 and u["opening_wdv_paise"] == 10 * L
    rec = dep["reconciliation"]
    assert rec["unplaced_allowance_paise"] == 2_90_000_00
    assert rec["placed_allowance_paise"] + rec["unplaced_allowance_paise"] == rec["section_32_allowance_paise"]
    assert rec["difference_paise"] == 0


def test_two_blocks_of_one_nature_and_rate_are_one_block_and_the_second_is_set_aside():
    a = Block(key="A", rate_percent=15, opening_wdv_paise=1 * L)
    b = Block(key="B", rate_percent=15, opening_wdv_paise=2 * L)
    dep = B.depreciation("ITR-3", _result(a, b, rows={"A": "PlantMachinery.Rate15", "B": "PlantMachinery.Rate15"}))
    assert [r["block_key"] for r in dep["rows"]] == ["A"]
    [u] = dep["unplaced"]
    assert u["block_key"] == "B" and "already on" in u["reason"] and "merge" in u["reason"]
    assert dep["reconciliation"]["difference_paise"] == 0


# ── Schedule DEP ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("form", FORMS)
def test_the_summary_has_one_box_per_row_and_the_form_computes_the_totals(form):
    result = _result(_plant(), Block(key="Furniture", rate_percent=10, opening_wdv_paise=2 * L),
                     Block(key="Shed", rate_percent=10, opening_wdv_paise=3 * L),
                     rows={"P&M 15%": "PlantMachinery.Rate15", "Furniture": "FurnitureFittings.Rate10", "Shed": "Building.Rate10"})
    dep = B.depreciation(form, result)
    summary = {s["json_path"].rsplit(".", 1)[1]: s["amount_paise"] for s in dep["summary"]}
    assert summary == {"DeprBlockTot15Percent": 2_90_000_00, "FurnitureSummary": 20_000_00, "DeprBlockTot10Percent": 30_000_00}
    totals = {c["label"]: c["amount_paise"] for c in dep["checks"]}
    assert totals == {"Total, plant and machinery": 2_90_000_00, "Total, building": 30_000_00, "Total depreciation": 3_40_000_00}
    assert all(c["kind"] == "form_computes" for c in dep["checks"])


# ── the tie-out carries the depreciation checks ──────────────────────────────────────────────────────────────────────────────────
def _books():
    return balanced_statements()


@pytest.mark.parametrize("form", FORMS)
def test_the_whole_assembly_ties_out_with_depreciation_in_it(form):
    result = _plan_with(None)              # one block placed, one left off
    out = B.assemble(form=form, assessment_year="2026-27", financial_year="2025-26", statements=_books(), section_32=result)
    names = {c["name"] for c in out["tie_out"]["checks"]}
    assert {"depreciation_rows_and_unplaced_blocks", "depreciation_summary"} <= names
    assert out["tie_out"]["ok"] is True and out["tie_out"]["difference_paise"] == 0
    assert any("No row on the return is recorded" in u["reason"] for u in out["depreciation"]["unplaced"])


def test_a_depreciation_row_that_does_not_add_to_the_section_32_allowance_is_caught(monkeypatch):
    result = _plan_with("PlantMachinery.Rate15")
    result["allowance_paise"] += 1                                       # the engine's total and the blocks disagree
    out = B.assemble(form="ITR-3", assessment_year="2026-27", financial_year="2025-26", statements=_books(), section_32=result)
    assert out["tie_out"]["ok"] is False
    assert any(c["name"] == "depreciation_rows_and_unplaced_blocks" and c["difference_paise"] == -1 for c in out["tie_out"]["checks"])


def test_the_gaps_the_engine_named_reach_the_schedule_and_the_answer():
    block = Block(key="P&M 15%", rate_percent=15, opening_wdv_paise=1 * L,
                  additions=(Addition("lathe", 1 * L, None),))
    out = B.assemble(form="ITR-3", assessment_year="2026-27", financial_year="2025-26", statements=_books(),
                     section_32=_result(block, rows={"P&M 15%": "PlantMachinery.Rate15"}))
    assert any("no put-to-use date" in g for g in out["depreciation"]["gaps"])
    assert any("no put-to-use date" in g for g in out["gaps"])


# ── the working the engine now carries out is an identity ─────────────────────────────────────────────────────────────────────
_paise = st.integers(min_value=0, max_value=50 * L)
_when = st.dates(min_value=date(2025, 4, 1), max_value=date(2026, 3, 31))


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(opening=_paise, rate=st.integers(0, 100),
       adds=st.lists(st.tuples(_paise, _when, st.booleans()), max_size=4),
       dels=st.lists(_paise, max_size=3), remain=st.sampled_from([True, None, False]))
def test_what_the_working_reports_for_the_rates_adds_to_the_allowance(opening, rate, adds, dels, remain):
    from domain.income_tax.section_32 import compute_block
    block = Block(key="b", rate_percent=rate, opening_wdv_paise=opening,
                  additions=tuple(Addition(f"a{i}", c, d, e) for i, (c, d, e) in enumerate(adds)),
                  deletions=tuple(Deletion(f"d{i}", m) for i, m in enumerate(dels)), assets_remain=remain)
    r = compute_block(block, fy_end=FY_END)
    # The moneys payable are taken out of the two bases and nowhere else: nothing is realised that was not there to realise.
    assert r.realization_against_full_paise + r.realization_against_half_paise <= r.deletions_paise
    survives = r.wdv_before_depreciation_paise >= 0 and remain is not False       # §50 has not closed the block
    if r.wdv_before_depreciation_paise >= 0:
        assert r.realization_against_full_paise + r.realization_against_half_paise == r.deletions_paise
    if r.depreciation_at_full_rate_paise is not None:
        assert r.depreciation_at_full_rate_paise + r.depreciation_at_half_rate_paise == r.depreciation_paise
    if r.additional_on_full_rate_additions_paise is not None:
        assert (r.additional_on_full_rate_additions_paise + r.additional_on_half_rate_additions_paise
                == r.additional_depreciation_paise)
    # The bases are what the rates were applied to: together they are the block's value before depreciation, and nothing where §50
    # closed the block and no depreciation was allowed.
    assert r.depreciation_base_full_paise + r.depreciation_base_half_paise == (r.wdv_before_depreciation_paise if survives else 0)
    assert r.closing_wdv_paise == (max(0, r.wdv_before_depreciation_paise - r.depreciation_paise - r.additional_depreciation_paise)
                                   if survives else 0)
