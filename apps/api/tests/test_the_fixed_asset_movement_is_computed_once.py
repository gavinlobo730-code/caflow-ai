"""One movement, two screens (FA-05, FA-15).

WHAT WAS WRONG, ON BOTH SIDES

  FA-05  `routers/year_end_notes.py` computed the Schedule III fixed-assets
         movement correctly — opening, additions, deductions, closing, per
         asset class — and it reached nobody. The year-end PDF renders only
         top-level `note_data` keys ending in `_paise` that are `int`, so
         `classes` (a list) and `totals` (a dict) were dropped; the notes
         screen renders `note.content`, which carries no movement. The CA still
         rebuilt the schedule by hand.

  FA-15  The fixed-asset Reports tab took a `financialYear` and used it in two
         string literals. Its only fetch had no year on it — and no route in
         `routers/fixed_assets.py` accepted one — so "Assets by Category — FY
         2025-26" was every asset the client had ever owned and "No disposals
         this year." was printed over every disposal ever recorded. It then
         re-derived the gross block and accumulated depreciation in the
         BROWSER.

WHY THIS FILE IS ABOUT ONE MODULE AND NOT TWO SCREENS

    The temptation was an FY-aware movement in the FA router beside the one in
    the note. Two implementations of one Schedule III disclosure, over the same
    register, for the same client, in the same year — differing by whichever
    was fixed last, on a table whose entire purpose is that this year's opening
    ties to last year's closing. `domain/reporting/fixed_asset_movement.py` is
    the one implementation; these tests hold it, and hold both callers to it.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from domain.reporting import fixed_asset_movement as fam

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
FA_PAGE = WEB / "app" / "clients" / "[id]" / "fixed-assets" / "page.tsx"

FY = "2025-26"
FY_END = "2026-03-31"


def _strip_comments(src: str) -> str:
    """`//` lines out, so a rule is never satisfied by prose describing it."""
    return "\n".join(l for l in src.splitlines() if not l.strip().startswith("//"))


def _asset(**kw) -> dict:
    base = {
        "asset_category": "Plant & Machinery",
        "purchase_cost_paise": 100_000_00,
        "accumulated_depreciation_paise": 0,
        "purchase_date": "2024-06-01",
        "is_disposed": False,
        "disposal_date": None,
        "depreciation_fy": FY,
        "depreciation_fy_start_accum_paise": 0,
    }
    base.update(kw)
    return base


# ── the label the whole thing hangs off ─────────────────────────────────────

@pytest.mark.parametrize("label,expected", [
    ("2025-26", "2026-03-31"),
    ("2025-2026", "2026-03-31"),
    ("2026-27", "2027-03-31"),
])
def test_a_financial_year_label_becomes_its_last_day(label, expected):
    assert fam.fy_end_for_label(label) == expected


@pytest.mark.parametrize("junk", [None, "", "2025", "FY2025-26", "not-a-year", "abcd-ef"])
def test_a_label_that_is_not_one_is_refused_rather_than_guessed(junk):
    """A report dated to the wrong financial year is worse than one that says
    it has no period — the second is visible."""
    assert fam.fy_end_for_label(junk) is None


def test_the_window_is_april_to_march():
    assert fam.fy_window("2026-03-31") == ("2025-04-01", "2026-03-31")


# ── the movement itself ─────────────────────────────────────────────────────

def test_the_columns_tie_opening_to_closing():
    """The whole reason Schedule III asks for a movement: closing gross must be
    opening plus additions less deductions, or the reader cannot check it
    against last year's statement."""
    rows = [
        _asset(purchase_date="2024-06-01"),                       # held at open
        _asset(purchase_date="2025-09-01", purchase_cost_paise=50_000_00),  # added
        _asset(purchase_date="2022-04-01", purchase_cost_paise=80_000_00,
               is_disposed=True, disposal_date="2025-12-15",
               accumulated_depreciation_paise=40_000_00,
               depreciation_fy_start_accum_paise=35_000_00),      # deducted
    ]
    m = fam.movement_from_rows(rows, FY_END)
    t = m.totals
    assert t["opening_gross_paise"] == 180_000_00
    assert t["additions_paise"] == 50_000_00
    assert t["deductions_paise"] == 80_000_00
    assert t["closing_gross_paise"] == (t["opening_gross_paise"]
                                        + t["additions_paise"]
                                        - t["deductions_paise"])
    assert t["closing_accum_paise"] == (t["opening_accum_paise"]
                                        + t["charge_paise"]
                                        - t["accum_on_deductions_paise"])
    assert t["opening_net_paise"] == t["opening_gross_paise"] - t["opening_accum_paise"]
    assert t["closing_net_paise"] == t["closing_gross_paise"] - t["closing_accum_paise"]


def test_an_asset_sold_in_the_year_is_a_DEDUCTION_and_does_not_vanish():
    """It used to be filtered out as `is_disposed = False`, so last year's
    closing did not tie to this year's opening and the reader had no way to see
    why."""
    m = fam.movement_from_rows([
        _asset(purchase_date="2022-04-01", is_disposed=True,
               disposal_date="2025-12-15", accumulated_depreciation_paise=30_000_00),
    ], FY_END)
    t = m.totals
    assert t["opening_gross_paise"] == 100_000_00
    assert t["deductions_paise"] == 100_000_00
    assert t["accum_on_deductions_paise"] == 30_000_00
    assert t["closing_gross_paise"] == 0


def test_an_asset_sold_AFTER_the_year_is_still_held_at_its_close():
    m = fam.movement_from_rows([
        _asset(purchase_date="2022-04-01", is_disposed=True, disposal_date="2026-08-01"),
    ], FY_END)
    assert m.totals["opening_gross_paise"] == 100_000_00
    assert m.totals["deductions_paise"] == 0
    assert m.totals["closing_gross_paise"] == 100_000_00


def test_an_asset_bought_after_the_year_ends_is_in_neither_column():
    m = fam.movement_from_rows([_asset(purchase_date="2026-07-01")], FY_END)
    assert m.totals["opening_gross_paise"] == 0
    assert m.totals["additions_paise"] == 0
    assert m.totals["closing_gross_paise"] == 0


def test_the_movement_is_per_asset_class():
    m = fam.movement_from_rows([
        _asset(asset_category="Vehicles", purchase_cost_paise=80_000_00),
        _asset(asset_category="Plant & Machinery"),
    ], FY_END)
    assert [c["asset_class"] for c in m.classes] == ["Plant & Machinery", "Vehicles"]
    assert m.totals["opening_gross_paise"] == 180_000_00


def test_an_asset_with_no_category_lands_in_Other_rather_than_being_dropped():
    m = fam.movement_from_rows([_asset(asset_category=None)], FY_END)
    assert [c["asset_class"] for c in m.classes] == ["Other"]


# ── what it refuses ─────────────────────────────────────────────────────────

def test_with_no_financial_year_it_reports_the_register_as_it_stands():
    """Not a zero movement, and not every asset dated into a year nobody
    named. Closing figures only, and it says so."""
    m = fam.movement_from_rows([
        _asset(accumulated_depreciation_paise=20_000_00),
    ], None)
    assert m.windowed is False and m.financial_year is None
    assert m.totals["closing_gross_paise"] == 100_000_00
    assert m.totals["closing_accum_paise"] == 20_000_00
    assert m.totals["opening_gross_paise"] == 0
    assert m.totals["additions_paise"] == 0
    gaps = " ".join(fam.movement_gaps(m, None))
    assert "as it stands" in gaps


def test_an_asset_last_depreciated_in_another_year_makes_the_split_unknown():
    """`accumulated_depreciation_paise` less `depreciation_fy_start_accum_paise`
    speaks only for the asset's CURRENT depreciation FY. For any other year the
    row cannot say how much of its accumulated depreciation belongs here, and a
    class split that quietly omits it is a wrong disclosure."""
    m = fam.movement_from_rows([
        _asset(depreciation_fy="2023-24", accumulated_depreciation_paise=40_000_00),
    ], FY_END)
    assert m.split_known is False
    assert "different financial year" in " ".join(fam.movement_gaps(m, None))


def test_a_ledger_that_disagrees_with_the_register_is_STATED():
    m = fam.movement_from_rows([
        _asset(accumulated_depreciation_paise=30_000_00,
               depreciation_fy_start_accum_paise=10_000_00),
    ], FY_END)
    assert m.totals["charge_paise"] == 20_000_00
    gaps = " ".join(fam.movement_gaps(m, 25_000_00))
    assert "25,000.00" in gaps and "20,000.00" in gaps and "5,000.00" in gaps


def test_a_ledger_that_agrees_says_nothing():
    m = fam.movement_from_rows([
        _asset(accumulated_depreciation_paise=30_000_00,
               depreciation_fy_start_accum_paise=10_000_00),
    ], FY_END)
    assert fam.movement_gaps(m, 20_000_00) == []


def test_a_ledger_that_could_not_be_read_is_a_GAP_and_never_a_ZERO():
    """A zero would be a claim that nothing was charged."""
    m = fam.movement_from_rows([_asset()], FY_END)
    gaps = " ".join(fam.movement_gaps(m, None))
    assert "could not be read from the ledger" in gaps


def test_the_caveat_does_not_call_itself_a_note():
    """It is rendered on the fixed-asset Reports tab too, which is not one.
    Wording shared between two screens cannot describe only one of them."""
    m = fam.movement_from_rows([_asset(depreciation_fy_start_accum_paise=0,
                                       accumulated_depreciation_paise=1)], FY_END)
    assert "this note" not in " ".join(fam.movement_gaps(m, 999))


# ── one implementation, and both callers on it ──────────────────────────────

def test_the_year_end_note_does_not_carry_its_own_movement():
    import routers.year_end_notes as yen
    src = inspect.getsource(yen._compute_fixed_assets_note_data)
    assert "fa_movement.movement_from_rows(" in src
    assert "fa_movement.movement_gaps(" in src
    for own in ("held_at_open", "accum_on_deductions_paise +=", "by_class"):
        assert own not in src, (
            f"the note is building the movement itself again ({own!r}) — it will "
            f"drift from the Reports tab exactly as the Reports tab drifted from it")


def test_the_fixed_asset_route_does_not_carry_its_own_either():
    import routers.fixed_assets as fa
    src = inspect.getsource(fa.fixed_asset_movement)
    assert "fa_movement.movement_from_rows(" in src
    assert "fa_movement.movement_gaps(" in src
    for own in ("held_at_open", "by_class", "opening_gross_paise +="):
        assert own not in src, f"a second movement implementation ({own!r})"


def test_the_route_reads_disposed_assets_too():
    """Filtering them out is defect (2) all over again, and it is one keyword."""
    import routers.fixed_assets as fa
    src = inspect.getsource(fa.fixed_asset_movement)
    assert '.eq("is_disposed"' not in src, (
        "an asset sold during the year is a DEDUCTION; excluding it makes this "
        "year's opening fail to tie to last year's closing")
    assert 'is_("deleted_at", "null")' in src, (
        "a soft-deleted row was created by mistake (migration 351) and was "
        "never in the register")


def test_the_route_pages_its_read():
    import routers.fixed_assets as fa
    assert "fetch_all(" in inspect.getsource(fa.fixed_asset_movement)


def test_the_route_takes_a_validated_financial_year():
    """CLAUDE.md: `fy: FYLabel = Query(...)` validates NOTHING — FastAPI builds
    the field from `Query()` in the default position and discards the Annotated
    metadata carrying the validator, silently."""
    import routers.fixed_assets as fa
    src = inspect.getsource(fa.fixed_asset_movement)
    assert "Annotated[Optional[FYLabel], Query()]" in src


def test_the_ledger_read_moved_with_the_movement():
    """A router importing another router's private function is not a shared
    implementation, it is a shortcut to one."""
    import routers.fixed_assets as fa
    src = inspect.getsource(fa.fixed_asset_movement)
    assert "fa_movement.posted_depreciation_paise(" in src
    assert "from routers.year_end_notes import" not in src
    assert callable(fam.posted_depreciation_paise)


# ── and the screen reads it rather than deriving it ─────────────────────────

def test_the_reports_tab_asks_for_the_year_it_is_titled_with():
    src = FA_PAGE.read_text()
    assert "/api/fixed-assets/movement?client_id=" in src
    assert "financial_year=${encodeURIComponent(financialYear)}" in src


def test_the_reports_tab_no_longer_derives_the_block_in_the_browser():
    """`grossBlock`/`accumDep` were `active.reduce(...)` over the asset list —
    a Schedule III figure computed in the frontend, over every asset the client
    ever owned, under a heading naming one financial year."""
    src = FA_PAGE.read_text()
    for derived in ("const grossBlock = active.reduce",
                    "const accumDep   = active.reduce",
                    "const byCategory = active.reduce"):
        assert derived not in src, f"still deriving in the browser: {derived}"


def test_the_reports_tab_renders_the_movement_columns():
    src = FA_PAGE.read_text()
    for col in ("opening_gross_paise", "additions_paise", "deductions_paise",
                "closing_gross_paise", "charge_paise", "closing_net_paise"):
        assert col in src, f"the movement's {col} column is not rendered"


def test_the_reports_tab_renders_the_caveats_it_is_given():
    """Showing the figures without the sentence is how a CA comes to trust a
    number the note itself qualifies.

    Asserted on the MAP, not on the word. The first version of this checked
    `"statutory_gaps" in src` and passed with the rendering deleted, because
    the type declaration and the length guard both still spell it — the
    money-parser mistake in miniature, inside a guard written to prevent it.
    """
    src = _strip_comments(FA_PAGE.read_text())
    assert "statutory_gaps: string[]" in src, "the field must be declared"
    assert "statutory_gaps.map(" in src, (
        "the tab declares the caveats and renders none of them — the figures "
        "then read as unqualified")


def test_the_disposal_panel_is_scoped_to_the_year_it_names():
    """It said "No disposals this year." over every disposal ever recorded."""
    src = FA_PAGE.read_text()
    assert "No disposals in this financial year." in src
    assert "fyRangeFor" in src, (
        "the year's window must come from lib/dates/periods, not be parsed "
        "out of the label a second time")


def test_the_movement_keys_are_one_tuple():
    """`year_end_notes._FA_MOVEMENT_KEYS` is the domain module's, aliased.

    A second LITERAL is how a column goes missing from one of the two
    renderings, so the assertion is on the source text and not on `is`:
    `tuple(t)` returns `t` itself for a tuple in CPython, so an identity check
    passes against a copy that was never made. What it cannot pass against is
    somebody typing the ten names out again.
    """
    import inspect
    import routers.year_end_notes as yen
    assert yen._FA_MOVEMENT_KEYS is fam.MOVEMENT_KEYS
    src = inspect.getsource(yen)
    # A LIST ELEMENT is `"key",`; an index read is `totals["key"]`, which the
    # note legitimately does to build the four figures it has always carried.
    # Only the first shape is a second key list.
    listed = [k for k in fam.MOVEMENT_KEYS if f'"{k}",' in src]
    assert not listed, (
        f"these are spelled out as a list in year_end_notes as well as in the "
        f"domain module — that is a second key list, and the two diverge the "
        f"first time a column is added: {listed}")
    assert len(fam.MOVEMENT_KEYS) == 10


# ── and the year-end PDF prints it (FA-05's other half) ─────────────────────

_PDF_NOTE = {
    "title": "Fixed Assets", "content": "Movement during the year.",
    "sequence_no": 1,
    "note_data": {
        "gross_block_paise": 150_000_00,
        "classes": [{
            "asset_class": "Plant & Machinery",
            "opening_gross_paise": 100_000_00, "additions_paise": 50_000_00,
            "deductions_paise": 0, "closing_gross_paise": 150_000_00,
            "opening_accum_paise": 10_000_00, "charge_paise": 25_000_00,
            "accum_on_deductions_paise": 0, "closing_accum_paise": 35_000_00,
            "opening_net_paise": 90_000_00, "closing_net_paise": 115_000_00,
        }],
        "totals": {
            "opening_gross_paise": 100_000_00, "additions_paise": 50_000_00,
            "deductions_paise": 0, "closing_gross_paise": 150_000_00,
            "opening_accum_paise": 10_000_00, "charge_paise": 25_000_00,
            "accum_on_deductions_paise": 0, "closing_accum_paise": 35_000_00,
            "opening_net_paise": 90_000_00, "closing_net_paise": 115_000_00,
        },
        "statutory_gaps": ["The ledger carries Rs 20,000.00 of depreciation for "
                           "the year and the register accounts for Rs 25,000.00."],
    },
}


def test_the_pdf_renders_the_movement_rather_than_dropping_it():
    """The generic renderer emits top-level keys ending `_paise` that are
    `int`. `classes` is a list and `totals` a dict, so the movement was on the
    floor and the PDF printed the same four closing figures it always had."""
    from services import year_end_pdf_service as pdf
    tbl = pdf._movement_table(_PDF_NOTE["note_data"])
    assert tbl is not None
    header = [str(c) for c in tbl._cellvalues[0]]
    for col in ("Opening", "Additions", "Deductions", "Closing", "Depn charge"):
        assert any(col in h for h in header), header
    assert str(tbl._cellvalues[-1][0]) == "Total"


def test_a_note_with_no_movement_gets_no_table():
    from services import year_end_pdf_service as pdf
    for empty in ({}, {"gross_block_paise": 1}, {"classes": []},
                  {"classes": [{"asset_class": "X"}]}):
        assert pdf._movement_table(empty) is None


def test_the_pdf_prints_the_caveats_beside_the_figures():
    from services import year_end_pdf_service as pdf
    st = {"note": pdf.getSampleStyleSheet()["Normal"]}
    out = pdf._note_qualifications(_PDF_NOTE["note_data"], st)
    assert out, "statutory_gaps is a list, so the generic renderer never saw it"
    text = " ".join(getattr(p, "text", "") for p in out)
    assert "20,000.00" in text and "25,000.00" in text


def test_both_year_end_pdfs_call_the_same_two_helpers():
    """Two renderers of one note is how the pack and the notes PDF come to
    disagree about the same client's fixed assets."""
    import inspect
    from services import year_end_pdf_service as pdf
    for fn in (pdf.generate_notes_pdf, pdf.generate_complete_pack_pdf):
        src = inspect.getsource(fn)
        assert "_movement_table(" in src, fn.__name__
        assert "_note_qualifications(" in src, fn.__name__


def test_the_notes_pdf_actually_builds_with_a_movement_in_it():
    from services import year_end_pdf_service as pdf
    out = pdf.generate_notes_pdf(
        {"client_name": "Acme Pvt Ltd", "financial_year": "2025-26", "status": "draft"},
        [_PDF_NOTE])
    assert out[:4] == b"%PDF" and len(out) > 2000
