"""
GST on bank charges — the tax-inclusive split (Tier 6.4).

Bank charges are the most repetitive line on an Indian statement, they carry
GST, and that GST is input tax credit under s.16 of the CGST Act. Booking the
gross to an expense account — which is what happened before — threw the credit
away every month.

The calculation runs the OPPOSITE way to every other GST split in this codebase:
the statement gives one tax-INCLUSIVE number and the taxable value has to be
backed out of it. Getting that wrong is easy and quiet (₹590 × 18% = ₹106.20
against a ₹590 payment, which does not balance), so it is unit-tested directly,
exhaustively, and for exactness (CLAUDE.md: every financial calculation).
"""
import pytest

from domain.banking.charge_gst import (
    ChargeSplit, split_inclusive_charge, build_charge_lines, ALLOWED_RATES_BPS,
)


# ══════════════════════════════════════════════════════════════════════════════
# The split
# ══════════════════════════════════════════════════════════════════════════════

def test_the_textbook_case():
    """₹590 debited at 18% is ₹500 of charge and ₹90 of GST — not ₹590 + ₹106.20."""
    s = split_inclusive_charge(59000, 1800)
    assert s.taxable_paise == 50000
    assert s.cgst_paise == 4500 and s.sgst_paise == 4500
    assert s.igst_paise == 0
    assert s.tax_paise == 9000


def test_interstate_puts_the_whole_tax_in_igst():
    """IGST Act s.12(12) — place of supply for banking services is the
    recipient's location, so a bank registered in another state is inter-state."""
    s = split_inclusive_charge(59000, 1800, is_interstate=True)
    assert s.taxable_paise == 50000
    assert s.igst_paise == 9000
    assert s.cgst_paise == 0 and s.sgst_paise == 0


def test_a_zero_rated_charge_is_all_taxable():
    """Some bank debits carry no GST at all — interest, certain levies."""
    s = split_inclusive_charge(59000, 0)
    assert s.taxable_paise == 59000 and s.tax_paise == 0
    assert s.has_gst is False


@pytest.mark.parametrize("rate", ALLOWED_RATES_BPS)
@pytest.mark.parametrize("gross", [1, 2, 3, 99, 100, 101, 4999, 59000, 123457, 99999999])
def test_the_split_is_always_exact(gross, rate):
    """THE invariant. taxable + tax must equal what the bank actually took, at
    every rate and every amount — otherwise the journal needs a rounding plug,
    and a rounding plug on a tax head is a wrong return."""
    for interstate in (False, True):
        s = split_inclusive_charge(gross, rate, is_interstate=interstate)
        assert s.taxable_paise + s.tax_paise == gross
        assert s.taxable_paise >= 0 and s.tax_paise >= 0


@pytest.mark.parametrize("gross", [1, 7, 99, 101, 4999, 59001, 123457])
def test_intrastate_halves_never_lose_a_paise(gross):
    """cgst + sgst must equal the whole tax. The odd paise goes to SGST — the
    same convention as the sales-side _compute_line_gst, so both halves of the
    system round the same way."""
    s = split_inclusive_charge(gross, 1800)
    assert s.cgst_paise + s.sgst_paise == s.tax_paise
    assert s.sgst_paise - s.cgst_paise in (0, 1)


def test_an_odd_paise_goes_to_sgst():
    # Chosen so the tax is an odd number of paise.
    s = split_inclusive_charge(101, 1800)
    assert s.tax_paise == 101 - s.taxable_paise
    if s.tax_paise % 2:
        assert s.sgst_paise == s.cgst_paise + 1


def test_taxable_is_floored_so_tax_is_never_understated():
    """Flooring the taxable value means the remainder — the TAX — absorbs the
    rounding. Understating input credit is the safe direction; overstating it is
    a wrong claim."""
    s = split_inclusive_charge(59001, 1800)
    assert s.taxable_paise == (59001 * 10000) // 11800
    assert s.tax_paise == 59001 - s.taxable_paise


@pytest.mark.parametrize("rate,expected_taxable", [
    (500, 100000),      # 5%   on ₹1,050
    (1200, 100000),     # 12%  on ₹1,120
    (1800, 100000),     # 18%  on ₹1,180
    (2800, 100000),     # 28%  on ₹1,280
])
def test_each_allowed_rate_backs_out_correctly(rate, expected_taxable):
    gross = expected_taxable + (expected_taxable * rate) // 10000
    assert split_inclusive_charge(gross, rate).taxable_paise == expected_taxable


# ── Refusals ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("gross", [0, -1, -59000])
def test_a_non_positive_charge_is_refused(gross):
    with pytest.raises(ValueError):
        split_inclusive_charge(gross, 1800)


@pytest.mark.parametrize("rate", [1, 100, 1500, 1801, 5000, -1800])
def test_an_unsupported_rate_is_refused(rate):
    """A typo in a tax head becomes a wrong GSTR-3B, so the vocabulary is closed
    rather than 'whatever the caller sent'."""
    with pytest.raises(ValueError):
        split_inclusive_charge(59000, rate)


# ══════════════════════════════════════════════════════════════════════════════
# The journal lines
# ══════════════════════════════════════════════════════════════════════════════

BANK, EXP, CGST, SGST, IGST = "bank", "charges", "in-cgst", "in-sgst", "in-igst"


def _lines(gross, rate, interstate=False):
    s = split_inclusive_charge(gross, rate, is_interstate=interstate)
    return build_charge_lines(s, bank_account_id=BANK, expense_account_id=EXP,
                              cgst_account_id=CGST, sgst_account_id=SGST,
                              igst_account_id=IGST)


def test_intrastate_lines_are_four_and_balance():
    lines = _lines(59000, 1800)
    assert len(lines) == 4
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines) == 59000
    by_acc = {l["account_id"]: l for l in lines}
    assert by_acc[EXP]["debit_paise"] == 50000
    assert by_acc[CGST]["debit_paise"] == 4500
    assert by_acc[SGST]["debit_paise"] == 4500
    assert by_acc[BANK]["credit_paise"] == 59000


def test_interstate_lines_use_igst_only():
    lines = _lines(59000, 1800, interstate=True)
    assert len(lines) == 3
    by_acc = {l["account_id"]: l for l in lines}
    assert by_acc[IGST]["debit_paise"] == 9000
    assert CGST not in by_acc and SGST not in by_acc


def test_a_zero_rated_charge_produces_the_plain_two_line_entry():
    lines = _lines(59000, 0)
    assert len(lines) == 2
    assert {l["account_id"] for l in lines} == {EXP, BANK}


def test_the_bank_is_always_credited():
    """A bank CHARGE is a debit on the statement, so the bank account is always
    the credit side. Reversing this would book negative input credit."""
    for interstate in (False, True):
        lines = _lines(59000, 1800, interstate)
        bank_line = next(l for l in lines if l["account_id"] == BANK)
        assert bank_line["credit_paise"] == 59000 and bank_line["debit_paise"] == 0


@pytest.mark.parametrize("gross", [1, 7, 99, 4999, 59001, 123457, 99999999])
def test_lines_balance_at_every_amount(gross):
    for interstate in (False, True):
        lines = _lines(gross, 1800, interstate)
        assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines)


def test_gst_lines_cite_the_section():
    """A CA reading the ledger should see why the credit was taken."""
    narrations = " ".join(l["narration"] for l in _lines(59000, 1800))
    assert "s.16" in narrations


def test_missing_tax_accounts_are_refused_not_silently_dropped():
    """Dropping the GST line would leave the entry unbalanced, or worse, silently
    book the whole gross as expense — the bug this feature exists to fix."""
    s = split_inclusive_charge(59000, 1800)
    with pytest.raises(ValueError):
        build_charge_lines(s, bank_account_id=BANK, expense_account_id=EXP)
    inter = split_inclusive_charge(59000, 1800, is_interstate=True)
    with pytest.raises(ValueError):
        build_charge_lines(inter, bank_account_id=BANK, expense_account_id=EXP,
                           cgst_account_id=CGST, sgst_account_id=SGST)


def test_missing_core_accounts_are_refused():
    s = split_inclusive_charge(59000, 1800)
    with pytest.raises(ValueError):
        build_charge_lines(s, bank_account_id="", expense_account_id=EXP,
                           cgst_account_id=CGST, sgst_account_id=SGST)
    with pytest.raises(ValueError):
        build_charge_lines(s, bank_account_id=BANK, expense_account_id="",
                           cgst_account_id=CGST, sgst_account_id=SGST)


def test_the_split_dataclass_is_immutable():
    s = split_inclusive_charge(59000, 1800)
    with pytest.raises(Exception):
        s.taxable_paise = 1  # type: ignore[misc]
    assert isinstance(s, ChargeSplit)
