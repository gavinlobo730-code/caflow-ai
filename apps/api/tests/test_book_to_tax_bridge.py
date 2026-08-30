"""
The book-to-tax bridge — profit per the accounts down to taxable income.

The pieces existed separately and nothing joined them: disallowances were
detected (§40A(3), §43B), losses were tracked (§72), depreciation was charged
under the Companies Act, and book profit was taken as an INPUT by the
minimum-tax engine precisely because nothing derived it. Missing was the
statement that puts them in one column and makes them add up — the document the
client reads and an assessing officer asks for.
"""
import pytest

from domain.income_tax.book_to_tax_bridge import build_bridge

L = 1_00_000_00


# ── The arithmetic property ──────────────────────────────────────────────────

def test_the_bridge_actually_gets_from_book_profit_to_taxable_income():
    """A bridge whose lines do not add up is not a bridge. 50 + 3 + 8 − 12 − 5."""
    b = build_bridge(book_profit_paise=50 * L, disallowances_paise=3 * L,
                     depreciation_per_books_paise=8 * L,
                     depreciation_under_section_32_paise=12 * L,
                     brought_forward_loss_set_off_paise=5 * L)
    assert b.foots() is True
    assert b.taxable_income_paise == 44 * L


def test_a_bridge_with_no_adjustments_lands_on_book_profit():
    b = build_bridge(book_profit_paise=20 * L,
                     depreciation_under_section_32_paise=0)
    assert b.taxable_income_paise == 20 * L
    assert b.foots() is True


def test_a_book_loss_carries_through():
    b = build_bridge(book_profit_paise=-10 * L, disallowances_paise=2 * L,
                     depreciation_under_section_32_paise=0)
    assert b.taxable_income_paise == -8 * L
    assert b.foots() is True


# ── Depreciation: the line this product cannot yet compute ───────────────────

def test_a_missing_section_32_figure_makes_the_bridge_incomplete():
    """Nothing in this codebase implements §32 block depreciation. The figure
    has to be supplied, and its absence is reported."""
    b = build_bridge(book_profit_paise=50 * L, depreciation_per_books_paise=8 * L)
    assert b.is_complete is False
    assert "Depreciation allowable under IT Act §32" in b.missing


def test_a_missing_section_32_figure_omits_BOTH_depreciation_lines():
    """The dangerous alternatives, both rejected: adding back the book charge
    and allowing nothing overstates income by the whole depreciation; netting
    the two to zero makes the bridge foot perfectly while understating the
    difference to nil. A bridge that reconciles and lies is worse than one that
    refuses to reconcile."""
    b = build_bridge(book_profit_paise=50 * L, depreciation_per_books_paise=8 * L)
    assert not any("epreciation" in l.label for l in b.lines)
    assert b.taxable_income_paise == 50 * L


def test_the_reason_explains_that_they_are_two_systems_not_two_rates():
    b = build_bridge(book_profit_paise=50 * L, depreciation_per_books_paise=8 * L)
    joined = " ".join(b.reasons)
    assert "blocks of assets" in joined
    assert "Schedule II" in joined
    assert "assumed equal" in joined


def test_both_depreciation_lines_appear_once_the_figure_is_supplied():
    b = build_bridge(book_profit_paise=50 * L, depreciation_per_books_paise=8 * L,
                     depreciation_under_section_32_paise=12 * L)
    labels = [l.label for l in b.lines]
    assert "Depreciation charged in the accounts" in labels
    assert "Depreciation allowable" in labels
    book_line = next(l for l in b.lines if l.label.endswith("accounts"))
    tax_line = next(l for l in b.lines if l.label == "Depreciation allowable")
    assert book_line.direction == "add"
    assert tax_line.direction == "deduct"


def test_the_section_32_line_is_marked_as_not_derived():
    """It came from a human, not from these books, and the statement says so."""
    b = build_bridge(book_profit_paise=50 * L,
                     depreciation_under_section_32_paise=12 * L)
    tax_line = next(l for l in b.lines if l.label == "Depreciation allowable")
    assert tax_line.derived is False
    assert "§32" in tax_line.reference


def test_a_nil_section_32_figure_is_supplied_not_missing():
    """Zero is an answer — a client with no assets has nil §32 depreciation.
    Treating it as "not supplied" would make every such bridge incomplete."""
    b = build_bridge(book_profit_paise=50 * L,
                     depreciation_under_section_32_paise=0)
    assert b.is_complete is True
    assert b.missing == ()


# ── Order matters: §72 goes last ─────────────────────────────────────────────

def test_the_brought_forward_loss_is_set_off_after_every_other_adjustment():
    """§72 sets off against the business income OF THE YEAR, which is the
    figure after all other adjustments. Setting it off earlier would let a
    later add-back resurrect income the loss had already absorbed."""
    b = build_bridge(book_profit_paise=50 * L, disallowances_paise=3 * L,
                     depreciation_under_section_32_paise=0,
                     brought_forward_loss_set_off_paise=5 * L)
    assert b.lines[-1].label == "Brought-forward business loss set off"
    assert b.lines[-1].reference == "IT Act 1961, §72"


# ── Adjustments the product does not detect ──────────────────────────────────

def test_a_ca_may_add_adjustments_this_product_does_not_detect():
    b = build_bridge(book_profit_paise=50 * L,
                     depreciation_under_section_32_paise=0,
                     other_add_backs=[("Expenditure relating to exempt income",
                                       2 * L, "IT Act 1961, §14A")],
                     other_deductions=[("Additional depreciation", 1 * L,
                                        "IT Act 1961, §32(1)(iia)")])
    assert b.taxable_income_paise == 51 * L
    assert b.foots() is True
    supplied = [l for l in b.lines if not l.derived]
    assert len(supplied) == 2, [l.label for l in supplied]


def test_a_complete_bridge_still_says_it_is_the_cas_to_review():
    """Complete means every adjustment this product knows of has a figure. It
    does not mean every adjustment exists — adjustments it cannot detect are
    not adjustments that are not there."""
    b = build_bridge(book_profit_paise=50 * L,
                     depreciation_under_section_32_paise=0)
    assert b.is_complete is True
    assert any("not adjustments that do not exist" in x for x in b.reasons)


# ── Presentation ─────────────────────────────────────────────────────────────

def test_every_line_cites_the_section_it_is_made_under():
    """A bridge a CA cannot check against the Act is a list of numbers."""
    b = build_bridge(book_profit_paise=50 * L, disallowances_paise=3 * L,
                     depreciation_per_books_paise=8 * L,
                     depreciation_under_section_32_paise=12 * L,
                     brought_forward_loss_set_off_paise=5 * L)
    for line in b.lines:
        assert line.reference.strip(), line.label


def test_amounts_are_positive_with_the_direction_carried_separately():
    """A statement shows an add-back as a positive figure in an "add" column,
    not as a negative in one column. Signing the amount instead would make the
    printed statement read wrongly."""
    b = build_bridge(book_profit_paise=50 * L, disallowances_paise=3 * L,
                     depreciation_under_section_32_paise=0,
                     brought_forward_loss_set_off_paise=5 * L)
    for line in b.lines:
        assert line.amount_paise >= 0
    deduction = next(l for l in b.lines
                     if l.direction == "deduct" and l.amount_paise)
    assert deduction.amount_paise > 0
    assert deduction.signed_paise < 0


def test_every_amount_is_integer_paise():
    b = build_bridge(book_profit_paise=1_23_45_678, disallowances_paise=9_876,
                     depreciation_under_section_32_paise=1_234)
    for line in b.lines:
        assert isinstance(line.amount_paise, int)
    assert isinstance(b.taxable_income_paise, int)


def test_a_nil_adjustment_produces_no_line():
    """A statement does not print rows of zeros. A supplied nil is still
    supplied — completeness is tracked separately from whether a line appears."""
    b = build_bridge(book_profit_paise=50 * L, disallowances_paise=0,
                     depreciation_per_books_paise=0,
                     depreciation_under_section_32_paise=0,
                     brought_forward_loss_set_off_paise=0)
    assert b.lines == ()
    assert b.is_complete is True
    assert b.taxable_income_paise == 50 * L
