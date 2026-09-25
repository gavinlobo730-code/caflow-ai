"""The s.393 payment-code table was a named, blanket gap (`payment_code_gap()`,
`vocabulary_for(...).gaps()`) for every Income-tax Act 2025 period. A confirmed
subset is held now (25-09-2026), read from a PRIMARY SOURCE — the file-format
specification Protean (formerly NSDL) publishes for the renumbered statements
themselves (Form 138/140/144, "Q1 to Q3/Q4 Version 1.1/1.2, for Tax Year
2026-27 onwards"). Each entry below is transcribed from that document's own
Annexure 2 ("Nature of Payment | Section | Section code to be used in the
return"), not from the Act's text and not from memory.

WHY SOME CONFIRMED SECTIONS ARE ABSENT FROM THIS FILE, DELIBERATELY. Several
1961-Act keys this registry already holds turned out to split FURTHER under
the new table on a fact no rate difference had exposed — s.194A by the payee's
age and the payer's kind (1020/1021/1022), s.194J's professional-fee limb
between an ordinary professional fee and a director's remuneration sharing one
citation but two different codes (1027 vs 1028). Recording either would be
the exact guess this module exists to refuse, so both stay named gaps and are
tested as such below, not silently omitted from this file's coverage.
"""
import pytest

from domain.tds import vocabulary as v


CONFIRMED = {
    # (section_1961, rate_bps or None) -> (expected code, the Annexure 2 row)
    ("192", None): ("1002", "Form 138 Annexure 2: 'Payments made to employees "
                             "other than Govt. employees'"),
    ("193", None): ("1019", "Form 140 Annexure 2, s.393(1) Table Sl. No. 5(i): "
                             "'Any income by way of Interest on securities'"),
    ("194", None): ("1029", "Form 140 Annexure 2, s.393(1) Table Sl. No. 7: "
                            "'Any dividends (including on preference shares) "
                            "declared.'"),
    ("194B", None): ("1058", "Form 140 Annexure 2, s.393(3) Table Sl. No. 1: "
                             "winnings from lottery/crossword/card game/"
                             "gambling"),
    ("194D", None): ("1005", "Form 140 Annexure 2, s.393(1) Table Sl. No. "
                             "1(i): 'Commission or brokerage - insurance'"),
    ("194G", None): ("1063", "Form 140 Annexure 2, s.393(3) Table Sl. No. 4: "
                             "lottery-ticket stocking/distributing/selling "
                             "commission"),
    ("194H", None): ("1006", "Form 140 Annexure 2, s.393(1) Table Sl. No. "
                             "1(ii): 'Commission or Brokerage - others'"),
    ("194I(A)", None): ("1008", "Form 140 Annexure 2, s.393(1) Table Sl. No. "
                                "2(ii).D(a): 'Rent on machinery etc.- "
                                "specified person'"),
    ("194I(B)", None): ("1009", "Form 140 Annexure 2, s.393(1) Table Sl. No. "
                                "2(ii).D(b): 'Rent other than machinery etc.- "
                                "specified person'"),
    ("194J(A)", None): ("1026", "Form 140 Annexure 2, s.393(1) Table Sl. No. "
                                "6(iii).D(a): technical services / cinema "
                                "royalty / call-centre operator"),
    ("194LA", None): ("1012", "Form 140 Annexure 2, s.393(1) Table Sl. No. "
                              "3(iii): 'Payment of Compensation on "
                              "Acquisition of Certain Immovable Property'"),
    ("194Q", None): ("1031", "Form 140 Annexure 2, s.393(1) Table Sl. No. "
                             "8(ii): 'Any sum for purchase of any goods'"),
    ("194T", None): ("1067", "Form 140/144 Annexure 2, s.393(3) Table Sl. "
                             "No. 7: partner's salary/remuneration/"
                             "commission/bonus/interest"),
    ("194C", 100): ("1023", "Form 140 Annexure 2, s.393(1) Table Sl. No. "
                            "6(i).D(a): contractor is individual or HUF"),
    ("194C", 200): ("1024", "Form 140 Annexure 2, s.393(1) Table Sl. No. "
                            "6(i).D(b): contractor other than individual/"
                            "HUF"),
}

#: Confirmed sections a lower-case or padded key must still resolve through —
#: the same normalisation `section_code()` already applies.
_CASE_VARIANTS = ["194i(a)", " 194I(A) ", "194I(a)"]


@pytest.mark.parametrize("section,rate_bps,expected", [
    (s, r, code) for (s, r), (code, _cite) in CONFIRMED.items()
])
def test_a_confirmed_code_is_the_one_the_spreadsheet_states(section, rate_bps, expected):
    code, gap = v.payment_code_for(section, rate_bps=rate_bps)
    assert code == expected, CONFIRMED[(section, rate_bps)][1]
    assert gap is None


def test_every_confirmed_entry_is_inside_the_stated_range():
    lo, hi = v.PAYMENT_CODE_RANGE
    for (code, _cite) in CONFIRMED.values():
        n = int(code)
        assert lo <= n <= hi, code


def test_the_confirmed_table_matches_the_module_constant_exactly():
    """The test file and the module must name the SAME fourteen sections —
    a mismatch either way means one of them silently drifted."""
    module_keys = set(v._PAYMENT_CODES_CONFIRMED) | {"194C"}
    test_keys = {s for (s, _r) in CONFIRMED}
    assert module_keys == test_keys


@pytest.mark.parametrize("section", _CASE_VARIANTS)
def test_lookup_is_case_and_whitespace_insensitive(section):
    code, gap = v.payment_code_for(section)
    assert code == "1008"
    assert gap is None


def test_194c_without_a_rate_is_a_named_gap_not_a_guess():
    code, gap = v.payment_code_for("194C")
    assert code is None
    assert gap is not None
    assert "1023" in gap.note and "1024" in gap.note


def test_194c_with_an_unrecognised_rate_is_a_named_gap():
    """A rate that is neither 194C's individual (1%) nor company (2%) figure
    must never silently resolve to either code."""
    code, gap = v.payment_code_for("194C", rate_bps=999)
    assert code is None
    assert gap is not None
    assert "999" in gap.note


@pytest.mark.parametrize("section", [
    "194A",     # splits by payee age AND payer kind (1020/1021/1022) — no
                # single rate in this registry distinguishes them
    "194J(B)",  # professional fee (1027) vs a director's fee (1028) share
                # one Sl. No. 6(iii).D(b) citation and 194J(B) cannot tell
                # them apart
    "194K",     # absent from every annexure this pass read
    "206C",     # TCS — reported on a different statement (27EQ/143), whose
                # own table this pass did not open
    "195",      # non-resident payments; 27Q/144's own table has different
                # codes per nature of remittance, not read here
    "",         # blank
    "999ZZ",    # not a section this codebase has ever held
])
def test_an_unconfirmed_section_is_a_named_gap_never_a_guess(section):
    code, gap = v.payment_code_for(section)
    assert code is None
    assert gap is not None
    assert gap.field == "tds_payment_code"


def test_the_gap_note_names_the_section_asked_about():
    _code, gap = v.payment_code_for("194A")
    assert "194A" in gap.note


# ── Vocabulary.payment_code() — the bundled, period-aware entry point ───────

def test_a_1961_act_period_has_no_payment_code_and_no_gap_either():
    """The old forms cite the alphabetic section code, never a numeric
    payment code — so a 1961-Act period is not MISSING one, it simply has
    none to hold, which is a different fact from a gap."""
    vocab = v.vocabulary_for("2025-26")
    code, gap = vocab.payment_code("194I(A)")
    assert code is None
    assert gap is None


def test_a_2025_act_period_resolves_the_confirmed_subset():
    vocab = v.vocabulary_for("2026-27")
    code, gap = vocab.payment_code("194Q")
    assert code == "1031"
    assert gap is None


def test_a_2025_act_period_still_refuses_what_is_unconfirmed():
    vocab = v.vocabulary_for("2026-27")
    code, gap = vocab.payment_code("194A")
    assert code is None
    assert gap is not None


def test_a_2025_act_period_still_carries_the_blanket_gap_too():
    """payment_code() narrows the picture per line; gaps() must still warn at
    the return level, because most of the table remains unconfirmed and a
    caller checking only gaps() must not be told the statement is complete."""
    vocab = v.vocabulary_for("2026-27")
    notes = [g.note for g in vocab.gaps()]
    assert any("393" in n for n in notes)


def test_194c_through_the_vocabulary_still_needs_the_rate():
    vocab = v.vocabulary_for("2026-27")
    code, gap = vocab.payment_code("194C", rate_bps=100)
    assert code == "1023"
    code, gap = vocab.payment_code("194C")
    assert code is None and gap is not None
