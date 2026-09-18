"""
TABLE 12 HAS TWO IDENTIFIER COLUMNS AND NEITHER HELD AN IDENTIFIER.

Found by the IRP-validation audit of 18-09-2026, against the primary sources
committed under `docs/compliance/sources/e-invoice/`. Three defects, one story:
the HSN column was measured with a rule that could not tell a code from a word,
and the UQC column was filled in by whichever feeder got there first.

A. `hsn_digits.problem_with` COUNTED CHARACTERS, NOT DIGITS

   There was no numeric test anywhere in the module, so 'SAC9983', '998-313'
   and 'abcdef' all satisfied a six-digit requirement and 'ABCD' a four-digit
   one. The gap list was silent about exactly the codes the portal refuses:
   the IRP's own field rule is `HSN_Code ^[0-9]*$` (field regular expressions
   A.1.2.2) and error 2176 is "HSN code(s)-{0} is invalid / Wrong HSN code is
   being passed".

B. THE MIXED-UNIT SENTENCE NAMED THE WRONG UNIT

   `uqc.one_unit_for` returns the units SORTED and the builder interpolated
   `mixed[0]`, saying "X is reported because it was seen first" — while the row
   files the unit on the first line SEEN. The two coincide only when the first
   line's unit happens to sort first, which is what the existing fixture did.
   A CA told the wrong unit was filed converts the quantities the wrong way.

C. `GAP_UQC_NOT_RECORDED` WAS UNREACHABLE FROM PRODUCTION

   Both feeders substituted a unit — `gst_return_service` "OTH" and
   `routers/gst` "NOS" — and both are valid UQCs, so an unrecorded unit
   arrived at the builder indistinguishable from a recorded one and the gap
   could never fire. The `_build_hsn_summary` walk that reports it was live;
   nothing could reach it. `routers/gst`'s "NOS" is the worse of the two: it
   asserts the goods were counted in NUMBERS.

   The substitution still happens, ONCE, where the row is built — Table 12's
   `uqc` is a string in the schema and "OTH" is CBIC's own code for OTHERS, so
   the FILED value is unchanged and only the gap is new.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from domain.gst import hsn_digits, uqc
from domain.gst.classifier import GSTInvoiceCategory
from domain.gst.gstr1_builder import (
    GAP_HSN_DIGITS,
    GAP_HSN_NOT_A_CODE,
    GAP_RETURN_CAVEAT,
    REPORTED_NOT_WITHHELD,
    InvoiceForGSTR1,
    InvoiceLine,
    build_gstr1,
    stamp_withheld,
    withheld_gaps,
)

API = Path(__file__).resolve().parents[1]

#: Above ₹5 crore, so Notification 78/2020 asks for six digits on every supply.
BIG = 100_00_00_000_00


def _line(hsn="998313", unit="PCS", qty=1.0, taxable=100_000):
    return InvoiceLine(hsn_sac_code=hsn, description="Widget", quantity=qty,
                       unit=unit, rate_paise=taxable, taxable_paise=taxable,
                       gst_rate=18.0, cgst_paise=9_000, sgst_paise=9_000,
                       igst_paise=0, cess_paise=0)


def _invoice(ref, lines, category=GSTInvoiceCategory.B2B):
    return InvoiceForGSTR1(
        id=ref, transaction_type="sales_invoice", reference_no=ref,
        transaction_date="2026-06-10", party_gstin="27AAACI1195H1ZT",
        party_name="Acme", place_of_supply="27", is_interstate=False,
        taxable_amount_paise=sum(l.taxable_paise for l in lines),
        cgst_paise=sum(l.cgst_paise for l in lines),
        sgst_paise=sum(l.sgst_paise for l in lines),
        igst_paise=0, cess_paise=0, is_reverse_charge=False,
        invoice_type="Regular", supply_type="B2B",
        gst_invoice_category=category,
        original_invoice_ref=None, original_invoice_date=None, lines=lines)


def _build(invoices, turnover=BIG):
    return build_gstr1(invoices, gstin="27AAACI1195H1ZT", period="062026",
                       aggregate_turnover_paise=turnover,
                       cancelled_documents=[])


def _kinds(out):
    return {g["kind"] for g in out.gaps}


def _req(digits=6):
    return hsn_digits.required_digits(BIG, is_b2b=True, period_start="2026-04-01")


# ── A. an HSN code is digits ─────────────────────────────────────────────────

@pytest.mark.parametrize("code", ["998313", "8471", "84713010", "99", "0"])
def test_a_numeric_code_IS_a_code(code):
    assert hsn_digits.is_a_code(code)


@pytest.mark.parametrize("code", [
    "SAC9983",      # a prefix somebody typed
    "998-313",      # the tariff heading punctuated
    "998 313",      # and spaced
    "abcdef",
    "ABCD",
    "9983.13",
    "",
    None,
    "   ",
])
def test_anything_but_digits_is_NOT_a_code(code):
    assert not hsn_digits.is_a_code(code)


@pytest.mark.parametrize("code", ["²²²²²²", "１２３４５６", "٣٣٣٣٣٣"])
def test_a_unicode_digit_is_not_one_for_this_purpose(code):
    """`str.isdigit()` is True of every one of these and `^[0-9]*$` is not.

    A `.isdigit()` test would accept a code the IRP refuses, which is the
    whole failure this module exists to stop — so the rule is the regex.
    """
    assert code.isdigit(), "premise: Python would call this a digit string"
    assert not hsn_digits.is_a_code(code)


@pytest.mark.parametrize("code", ["SAC998", "99-313", "abcdef", "9983.1"])
def test_a_six_CHARACTER_non_code_no_longer_satisfies_six_DIGITS(code):
    """The headline. Each of these is six characters and satisfied the old test."""
    assert len(code) == 6, "premise: the character count is exactly the requirement"
    problem = hsn_digits.problem_with(code, _req())
    assert problem is not None
    assert "not a code" in problem
    assert "2176" in problem, "the CA needs the error the portal will return"


def test_the_two_hsn_answers_are_NOT_INTERCHANGEABLE():
    short = hsn_digits.problem_with("9983", _req())
    junk = hsn_digits.problem_with("SAC9983", _req())
    absent = hsn_digits.problem_with("", _req())
    assert len({short, junk, absent}) == 3
    assert "digits are required" in absent
    assert "has 4 digits" in short
    assert "not a code" in junk


def test_a_junk_code_is_reported_even_where_HSN_IS_OPTIONAL():
    """A nil requirement makes the code optional and not a wrong one acceptable.

    B2C at or below ₹5 crore owes no HSN under Notification 78/2020 — but
    Table 12 files whatever IS recorded, so a junk code still reaches the
    portal and still comes back as 2176.
    """
    nil = hsn_digits.required_digits(1_00_00_000_00, is_b2b=False,
                                     period_start="2026-04-01")
    assert nil.digits == 0, "premise: this supply owes no HSN"
    assert hsn_digits.problem_with("SAC-9983", nil) is not None
    assert hsn_digits.problem_with("", nil) is None, \
        "an absent code under a nil requirement is exactly what is permitted"


def test_the_rule_is_the_REGEX_and_never_str_isdigit():
    """`'²'.isdigit()` is True and `^[0-9]*$` does not admit it.

    Stated on the module rather than on one function, because the next reader
    reaching for a digit test is as likely to add it to `is_a_code` as to
    `problem_with`, and either would accept a code the IRP refuses.
    """
    src = inspect.getsource(hsn_digits)
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert ".isdigit()" not in body
    assert '^[0-9]+$' in body, "the rule is the IRP's own field expression"


# ── A, through the builder ───────────────────────────────────────────────────

def test_a_junk_code_reaches_the_gap_list_under_ITS_OWN_KIND():
    out = _build([_invoice("INV/1", [_line(hsn="SAC9983")])])
    assert GAP_HSN_NOT_A_CODE in _kinds(out)
    assert GAP_HSN_DIGITS not in _kinds(out), \
        "a six-character non-code is not 'below the requirement'"
    gap = next(g for g in out.gaps if g["kind"] == GAP_HSN_NOT_A_CODE)
    assert gap["reference_no"] == "INV/1"
    assert gap["hsn_sc"] == "SAC9983"


def test_an_ABSENT_code_keeps_the_DIGITS_kind():
    out = _build([_invoice("INV/1", [_line(hsn="")])])
    assert GAP_HSN_DIGITS in _kinds(out)
    assert GAP_HSN_NOT_A_CODE not in _kinds(out), \
        "nothing recorded is the notification's question, not the field rule's"


def test_a_short_numeric_code_keeps_the_DIGITS_kind():
    out = _build([_invoice("INV/1", [_line(hsn="9983")])])
    assert GAP_HSN_DIGITS in _kinds(out)
    assert GAP_HSN_NOT_A_CODE not in _kinds(out)


def test_the_junk_code_is_still_FILED_exactly_as_recorded():
    """REPORTED, NEVER REFUSED and never corrected.

    Truncating or substituting would file a code the client did not issue,
    and refusing the build for one line is how a CA learns to skip the
    validator — GST-29's split, and `uqc`'s.
    """
    out = _build([_invoice("INV/1", [_line(hsn="SAC9983")])])
    assert out.payload["hsn"]["data"][0]["hsn_sc"] == "SAC9983"


def test_the_new_kind_is_REPORTED_not_WITHHELD():
    """The document is in the payload, so the kind belongs in that set.

    Left out, `withheld_gaps` would tell three test modules and the GSTR-1
    screen that a document had been held back when it had not.
    """
    assert GAP_HSN_NOT_A_CODE in REPORTED_NOT_WITHHELD


# ── B. the mixed-unit sentence names the unit the row carries ────────────────

def test_the_mixed_unit_sentence_names_the_unit_ACTUALLY_FILED():
    """PCS first, BOX second — so first-seen and alphabetically-first DIFFER.

    The existing fixture in `test_a_uqc_is_a_code_not_a_word` builds BOX
    before PCS, where the two coincide, which is why the old sentence passed
    while naming `mixed[0]`.
    """
    out = _build([_invoice("INV/1", [_line(unit="PCS", qty=5.0),
                                     _line(unit="BOX", qty=10.0)])])
    gap = next(g for g in out.gaps
               if g["kind"] == uqc.GAP_UQC_MIXED_FOR_ONE_HSN)
    row = out.payload["hsn"]["data"][0]
    assert row["uqc"] == "PCS", "premise: the row files the unit seen first"
    assert uqc.one_unit_for(["PCS", "BOX"])[0] == "BOX", \
        "premise: sorted() puts the OTHER unit first"
    assert f"{row['uqc']} is reported" in gap["reason"]
    assert "BOX is reported" not in gap["reason"]


def test_both_units_are_still_NAMED_whichever_is_filed():
    out = _build([_invoice("INV/1", [_line(unit="PCS", qty=5.0),
                                     _line(unit="BOX", qty=10.0)])])
    gap = next(g for g in out.gaps
               if g["kind"] == uqc.GAP_UQC_MIXED_FOR_ONE_HSN)
    assert "PCS" in gap["reason"] and "BOX" in gap["reason"]
    assert "sum" in gap["reason"]


def test_where_the_first_line_records_NO_unit_the_sentence_says_so():
    """The one case where no named unit is the filed one.

    `one_unit_for` deliberately does not count an unrecorded unit as a
    distinct value, so a group of (None, PCS, BOX) reports a mixture of two —
    and the row carries neither. Saying "PCS is reported, the unit on the
    first line seen" would be false twice over.
    """
    out = _build([_invoice("INV/1", [_line(unit=None, qty=1.0),
                                     _line(unit="PCS", qty=5.0),
                                     _line(unit="BOX", qty=10.0)])])
    gap = next(g for g in out.gaps
               if g["kind"] == uqc.GAP_UQC_MIXED_FOR_ONE_HSN)
    assert "records no unit of its own" in gap["reason"]
    assert out.payload["hsn"]["data"][0]["uqc"] == "OTH"


# ── C. nobody invents a unit ─────────────────────────────────────────────────

def test_an_unrecorded_unit_is_REPORTED_and_still_filed_as_OTH():
    out = _build([_invoice("INV/1", [_line(unit=None)])])
    assert uqc.GAP_UQC_NOT_RECORDED in _kinds(out)
    assert out.payload["hsn"]["data"][0]["uqc"] == "OTH", \
        "Table 12's uqc is a string in the schema, so it still carries a code"


def test_a_recorded_OTH_and_an_unrecorded_unit_are_TOLD_APART():
    """The whole of defect C in one assertion.

    Both file OTH. One is a CA saying OTHERS and one is nobody having said
    anything, and before this they were the same row by the time the builder
    saw them.
    """
    recorded = _build([_invoice("A", [_line(unit="OTH")])])
    unrecorded = _build([_invoice("B", [_line(unit=None)])])
    assert recorded.payload["hsn"]["data"][0]["uqc"] == "OTH"
    assert unrecorded.payload["hsn"]["data"][0]["uqc"] == "OTH"
    assert uqc.GAP_UQC_NOT_RECORDED not in _kinds(recorded)
    assert uqc.GAP_UQC_NOT_RECORDED in _kinds(unrecorded)


@pytest.mark.parametrize("module,func", [
    ("services/gst_return_service.py", None),
    ("routers/gst.py", "_parse_invoice_line"),
])
def test_no_feeder_substitutes_a_unit(module, func):
    """THE RULE, not a spelling of it.

    Walks the AST for the `unit=` keyword on an `InvoiceLine(...)` call and
    fails any default that is a non-empty string literal. `or "OTH"` and
    `or "NOS"` were two different inventions in two files; a third would be a
    third, and a grep for either spelling would not find it.
    """
    tree = ast.parse((API / module).read_text())
    found = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "InvoiceLine"):
            continue
        for kw in node.keywords:
            if kw.arg != "unit":
                continue
            found += 1
            # A column NAME is a string constant too — `r.get("unit")` — and
            # it is not a substitution, so the arguments of every call inside
            # the expression are excluded before the rest are judged.
            keys = {c.value for call in ast.walk(kw.value)
                    if isinstance(call, ast.Call)
                    for c in call.args
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)}
            for lit in ast.walk(kw.value):
                if not (isinstance(lit, ast.Constant)
                        and isinstance(lit.value, str)):
                    continue
                if lit.value in keys:
                    continue
                assert lit.value.strip() == "", (
                    f"{module} substitutes {lit.value!r} for an unrecorded "
                    f"unit, which makes uqc.GAP_UQC_NOT_RECORDED "
                    f"unreachable from this feeder")
    assert found == 1, f"{module}: expected exactly one InvoiceLine(unit=...)"


def test_the_router_feeder_passes_an_absent_unit_THROUGH():
    """The AST rule above, exercised.

    A guard that only reads the source is one refactor from being vacuous, so
    the one feeder that can be called without a database is called.
    """
    from routers.gst import _parse_invoice_line
    assert _parse_invoice_line({}).unit is None
    assert _parse_invoice_line({"unit": "   "}).unit is None
    assert _parse_invoice_line({"unit": " pcs "}).unit == "pcs"


def test_the_substitution_happens_where_the_ROW_is_built():
    """One place, and it is the builder's.

    A feeder that substitutes destroys the fact; the builder substitutes
    beside the gap that records it. Asserted on the source so the two cannot
    drift back apart.
    """
    src = (API / "domain/gst/gstr1_builder.py").read_text()
    assert 'uqc.normalise(line.unit) or "OTH"' in src


# ── D. the two kinds of gap reach the screen as two kinds ────────────────────
#
# Found while wiring C: `Gstr1Findings` heads the WHOLE gap list "Not declared
# in this return", which is what a `REPORTED_NOT_WITHHELD` gap is not — and
# their own reasons say so. The server has made the distinction since GST-18
# and nothing carried it across the wire.


def test_every_gap_says_which_of_the_two_kinds_it_is():
    stamped = stamp_withheld([
        {"kind": GAP_HSN_NOT_A_CODE, "reference_no": "A", "reason": "x"},
        {"kind": "SEZ_WOP", "reference_no": "B", "reason": "y"},
    ])
    assert [g["withheld"] for g in stamped] == [False, True]
    assert all("kind" in g and "reason" in g for g in stamped), \
        "the stamp adds a key and never replaces the gap"


def test_the_stamp_and_the_filter_are_ONE_definition():
    """Two readings of the same set, asserted to agree over the whole set.

    `withheld_gaps` is what three test modules use and `stamp_withheld` is
    what the screen renders; a second list in either is how the Schedule III
    caption vocabulary came to offer five captions the engine had not heard of.
    """
    gaps = ([{"kind": k, "reference_no": "", "reason": ""}
             for k in REPORTED_NOT_WITHHELD]
            + [{"kind": k, "reference_no": "", "reason": ""}
               for k in ("SEZ_WOP", "DEEMED_EXPORT", "CDNUR", "")])
    kept = {id(g) for g in withheld_gaps(gaps)}
    for original, stamped in zip(gaps, stamp_withheld(gaps)):
        assert stamped["withheld"] == (id(original) in kept)


def test_a_RETURN_CAVEAT_is_reported_and_not_withheld():
    """The kind `gst_return_service` emits for a quarterly filer's two
    sentences. It used to emit the literal string "REPORTED_NOT_WITHHELD",
    which is the NAME of the set and is not a member of it — so both were
    counted as documents held out of the payload, the opposite of the word
    somebody reached for.
    """
    assert GAP_RETURN_CAVEAT in REPORTED_NOT_WITHHELD
    assert "REPORTED_NOT_WITHHELD" not in REPORTED_NOT_WITHHELD
    assert withheld_gaps([{"kind": GAP_RETURN_CAVEAT}]) == []


def test_the_service_emits_the_KIND_and_not_the_name_of_the_set():
    src = (API / "services/gst_return_service.py").read_text()
    assert '"kind": "REPORTED_NOT_WITHHELD"' not in src
    assert 'gstr1_builder.GAP_RETURN_CAVEAT' in src
    assert 'gstr1_builder.stamp_withheld(payload.gaps)' in src, \
        "the distinction has to cross the wire or the screen cannot make it"
