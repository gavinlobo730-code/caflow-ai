"""
Schedule III, Division I, General Instructions para 4 — rounding off.

    "The figures appearing in the Financial Statements shall be rounded off as
     given below:
        (a) total income less than one hundred crore rupees — to the nearest
            hundreds, thousands, lakhs or millions, or decimals thereof;
        (b) total income of one hundred crore rupees or more — to the nearest
            lakhs, millions or crores, or decimals thereof.
     Provided that once a unit of measurement is used, it shall be used
     uniformly in the Financial Statements."

MCA amended this on 24 March 2021, w.e.f. 1 April 2021, and changed two things
that these tests pin: the test became TOTAL INCOME where the 2013 text said
TURNOVER, and "may be rounded off" became "SHALL be rounded off".
"""
import pytest

from domain.reporting.schedule_iii import (
    HUNDRED_CRORE_PAISE,
    ROUNDING_LABELS,
    ROUNDING_UNITS,
    default_rounding_unit,
    permitted_rounding_units,
    round_section,
    round_to_unit,
)

CRORE = 1_00_00_000_00      # one crore rupees, in paise
LAKH = 1_00_000_00          # one lakh rupees, in paise


# ── The threshold ────────────────────────────────────────────────────────────

def test_one_hundred_crore_is_the_threshold_and_it_is_in_paise():
    """A units mistake here silently moves every client across the boundary."""
    assert HUNDRED_CRORE_PAISE == 100 * CRORE
    assert HUNDRED_CRORE_PAISE // 100 == 1_000_000_000     # rupees


def test_exactly_one_hundred_crore_falls_in_the_upper_limb():
    """Para 4(b) reads 'one hundred crore rupees OR MORE', so the boundary
    belongs to the coarser set. A > test instead of >= would hand a company
    sitting exactly on it the finer options the statute withholds."""
    assert permitted_rounding_units(HUNDRED_CRORE_PAISE) == [
        "lakhs", "millions", "crores"]
    assert permitted_rounding_units(HUNDRED_CRORE_PAISE - 1) == [
        "hundreds", "thousands", "lakhs", "millions"]


def test_the_permitted_sets_are_exactly_what_para_4_lists():
    below = permitted_rounding_units(50 * CRORE)
    above = permitted_rounding_units(500 * CRORE)
    assert below == ["hundreds", "thousands", "lakhs", "millions"]
    assert above == ["lakhs", "millions", "crores"]
    # Rupees to the unit is NOT among them. Before the 2021 amendment a
    # company could decline to round and show full figures; "shall" removed
    # that, and the least coarse unit on offer is now the nearest hundred.
    assert "units" not in below and "rupees" not in below


def test_every_permitted_unit_has_a_divisor_and_a_caption():
    """The caption goes on the face of the statements — a rounded figure with
    no unit named is not a Schedule III presentation, it is an unlabelled
    number."""
    for unit in set(permitted_rounding_units(0)) | set(permitted_rounding_units(500 * CRORE)):
        assert unit in ROUNDING_UNITS
        assert unit in ROUNDING_LABELS
        assert "₹" in ROUNDING_LABELS[unit]


def test_the_divisors_are_the_indian_magnitudes():
    assert ROUNDING_UNITS["hundreds"] == 100_00
    assert ROUNDING_UNITS["thousands"] == 1_000_00
    assert ROUNDING_UNITS["lakhs"] == 1_00_000_00           # 1,00,000 rupees
    assert ROUNDING_UNITS["millions"] == 10_00_000_00       # 10,00,000 rupees
    assert ROUNDING_UNITS["crores"] == 1_00_00_000_00       # 1,00,00,000 rupees


# ── The default unit ─────────────────────────────────────────────────────────

def test_the_default_is_always_one_the_statute_permits():
    for income in (0, 5_000_00, 50 * LAKH, 99 * CRORE, HUNDRED_CRORE_PAISE, 5000 * CRORE):
        assert default_rounding_unit(income) in permitted_rounding_units(income)


def test_the_default_keeps_the_headline_figure_readable():
    """Coarsest unit that still leaves three significant digits. A statement
    whose total income reads '2' has thrown away what the reader came for."""
    assert default_rounding_unit(50 * LAKH) == "thousands"      # reads 5,000
    assert default_rounding_unit(12_50_00_000 * 100) == "millions"
    assert default_rounding_unit(2500 * CRORE) == "crores"      # reads 2,500


def test_a_dormant_client_still_gets_a_permitted_unit():
    """Every unit swallows the figure. It must not fall through to None or to
    an unpermitted 'rupees'."""
    assert default_rounding_unit(0) == "hundreds"
    assert default_rounding_unit(500_00) == "hundreds"


# ── Rounding a single figure ─────────────────────────────────────────────────

def test_half_rounds_away_from_zero_on_both_signs():
    """Half AWAY FROM ZERO, not half up. A loss and a profit of the same size
    must round to the same size — asymmetric rounding would make a comparative
    column of losses drift against the profits beside it."""
    assert round_to_unit(150_00, "hundreds") == 2
    assert round_to_unit(-150_00, "hundreds") == -2
    assert round_to_unit(149_99, "hundreds") == 1
    assert round_to_unit(-149_99, "hundreds") == -1


def test_rounding_is_exact_integer_arithmetic():
    """CLAUDE.md: every rupee calculation uses integer paise, never float."""
    # 1_23_45_678 paise is Rs 1,23,456.78. In thousands of rupees that is
    # 123.45678, which rounds to 123.
    result = round_to_unit(1_23_45_678, "thousands")
    assert isinstance(result, int)
    assert result == 123
    # The same figure in hundreds: 1,234.5678 -> 1,235.
    assert round_to_unit(1_23_45_678, "hundreds") == 1_235
    assert round_to_unit(0, "lakhs") == 0


def test_an_unknown_unit_is_refused_by_name():
    with pytest.raises(ValueError, match="rounding unit"):
        round_to_unit(100, "furlongs")


# ── Rounding a section, so the statement foots ───────────────────────────────

def test_a_section_still_adds_up_after_rounding():
    """Rounding each line independently is the obvious implementation and it
    is wrong: three lines of 33,333.33 each round to 33 thousands, summing to
    99 against a true total of 1,00,000 that rounds to 100. The column would
    not add up on the page."""
    section = {"a": 33_333_33, "b": 33_333_33, "c": 33_333_34}
    rounded = round_section(section, "thousands")
    assert sum(rounded.values()) == round_to_unit(sum(section.values()), "thousands")


def test_no_line_moves_more_than_one_unit_from_its_own_value():
    """The residual is handed out by largest remainder, so a line is nudged by
    at most one unit — never bulk-dumped onto a single 'balancing figure'
    line, which would misstate that line to make the column work."""
    section = {f"l{i}": 1_500_00 + i for i in range(9)}   # every line on a half
    rounded = round_section(section, "thousands")
    for name, paise in section.items():
        assert abs(rounded[name] - round_to_unit(paise, "thousands")) <= 1


def test_the_balance_sheet_still_balances_after_rounding():
    """The property that matters most. Both sides are rounded from their own
    true totals, and those totals are equal, so their rounded totals are equal
    — the sheet cannot be knocked out of balance by presentation alone."""
    assets = {"cash": 3_33_333_33, "receivables": 6_66_666_67}
    equity_liab = {"capital": 5_00_000_00, "payables": 5_00_000_00}
    assert sum(assets.values()) == sum(equity_liab.values())
    ra = round_section(assets, "thousands")
    re_ = round_section(equity_liab, "thousands")
    assert sum(ra.values()) == sum(re_.values())


def test_an_empty_section_rounds_to_nothing_rather_than_raising():
    assert round_section({}, "lakhs") == {}


def test_negative_lines_round_with_the_section():
    """An accumulated loss sits in Reserves and Surplus as a negative figure
    (Schedule III, Division I, Part I), so a section can carry both signs."""
    section = {"reserves": -2_50_000_00, "capital": 10_00_000_00}
    rounded = round_section(section, "lakhs")
    assert rounded["reserves"] < 0
    assert sum(rounded.values()) == round_to_unit(sum(section.values()), "lakhs")


def test_the_apportionment_is_deterministic():
    """Ties break on the line name, so the same input gives the same statement
    every time. Dict-ordering would make a re-render differ from the PDF a CA
    already signed."""
    section = {"z": 1_500_00, "a": 1_500_00, "m": 1_500_00}
    first = round_section(section, "thousands")
    again = round_section(dict(reversed(list(section.items()))), "thousands")
    assert first == again


# ── The PDF presents in the rounded unit, and says which ─────────────────────
#
# ReportLab compresses its content streams, so the rendered text cannot be
# grepped out of the bytes. These target _presentation instead — the seam that
# actually decides which figures and which caption reach the page — and assert
# separately that both shapes still render.

def _statements():
    import services.year_end_financial_service as yefs
    return yefs._mock_statements("C1", "F1", "2024-04-01", "2025-03-31")


def _render(statements: dict) -> bytes:
    from services.year_end_pdf_service import generate_financial_statements_pdf
    return generate_financial_statements_pdf(
        {"id": "ENG1", "financial_year": "2024-25", "status": "approved",
         "client_name": "Test Client"},
        statements)


def test_the_pdf_presents_the_rounded_figures_and_names_the_unit():
    """A rounded figure with no unit named is not a Schedule III presentation,
    it is an unlabelled number. The PDF used to caption every statement "All
    figures in Indian Rupees (₹)" while printing to the rupee — a presentation
    para 4 has not permitted since 1 April 2021."""
    from services.year_end_pdf_service import _presentation, _format_indian
    st = _statements()
    bs, comp_bs, pl, comp_pl, fmt, caption = _presentation(st)

    assert st["rounding"]["label"] in caption
    assert "para 4" in caption
    # The figures handed to the page are the ROUNDED ones, not paise...
    assert bs["total_assets"] == st["rounding"]["current"]["balance_sheet"]["total_assets"]
    assert bs["total_assets"] != st["balance_sheet"]["total_assets_paise"]
    # ...so the formatter must not divide by a hundred again.
    assert fmt is _format_indian


def test_the_rounded_pdf_figures_still_balance_and_foot():
    from services.year_end_pdf_service import _presentation
    bs, _c, _pl, _cp, _f, _cap = _presentation(_statements())
    assert bs["total_assets"] == bs["total_equity_and_liabilities"]
    assert sum(bs["assets"].values()) == bs["total_assets"]
    assert sum(bs["equity_and_liabilities"].values()) == bs["total_equity_and_liabilities"]


def test_a_snapshot_taken_before_rounding_existed_still_renders():
    """Snapshots hold whatever statement_data looked like when they were
    taken, and older ones have no "rounding" block. Refusing to open a
    statement a CA already has would be the worse outcome, so those fall back
    to the old rupee presentation rather than raising."""
    from services.year_end_pdf_service import _presentation, _rs
    st = _statements()
    del st["rounding"]
    bs, _c, _pl, _cp, fmt, caption = _presentation(st)
    assert "Indian Rupees" in caption
    assert fmt is _rs                       # paise -> rupees, as before
    assert bs["total_assets"] == st["balance_sheet"]["total_assets_paise"]
    assert _render(st)[:4] == b"%PDF"


def test_both_presentations_render_a_pdf():
    st = _statements()
    assert _render(st)[:4] == b"%PDF"
    del st["rounding"]
    assert _render(st)[:4] == b"%PDF"
