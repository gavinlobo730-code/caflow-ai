"""
CGST Rule 59(2) — the Invoice Furnishing Facility, for months 1 and 2 of a
QRMP quarter (GST-11's remaining half).

WHAT IS ASSERTED
    1. Every `[S]`-graded figure exactly — the ₹50 lakh cumulative cap, the
       1st-to-13th window, the two months the facility reaches — because none
       of them could be read off the rule from this environment and a drifted
       constant would be invisible.
    2. The facility carries documents to a REGISTERED person and NOTHING else,
       asserted by building one document of every category the GSTR-1 builder
       knows and reading the payload's keys.
    3. Every section `build_gstr1` can emit is either carried or NAMED as not
       carried. Derived from the builder's own source, so a section added
       there without a decision here FAILS rather than falling silently out of
       an early-furnished return.
    4. The third month of a quarter is refused, because its documents are in
       the quarterly GSTR-1 and furnishing them would declare them twice.
    5. The cap REPORTS and never truncates: over ₹50 lakh every document is
       still in the payload and the excess is stated.
    6. An SEZ or deemed-export document with no recipient GSTIN is held out
       and NAMED — the `gaps` discipline, because it IS a supply to a
       registered person that this facility cannot carry.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from domain.gst import iff
from domain.gst.classifier import GSTInvoiceCategory
from domain.gst.gstr1_builder import InvoiceForGSTR1, InvoiceLine

GSTIN = "27AAACT2727Q1ZW"
BUYER = "29AAACT2727Q1Z2"
PERIOD = "052025"   # May — month 2 of Q1


def _doc(ref: str, category: GSTInvoiceCategory, *, gstin: str | None = BUYER,
         taxable: int = 100_000_00, igst: int = 18_000_00,
         txn_type: str = "sales_invoice") -> InvoiceForGSTR1:
    line = InvoiceLine(hsn_sac_code="998314", description="svc", quantity=1.0,
                       unit="NOS", rate_paise=taxable, taxable_paise=taxable,
                       gst_rate=18.0, cgst_paise=0, sgst_paise=0,
                       igst_paise=igst, cess_paise=0)
    return InvoiceForGSTR1(
        id=ref, transaction_type=txn_type, reference_no=ref,
        transaction_date="2025-05-10", party_gstin=gstin, party_name="Acme",
        place_of_supply="29", is_interstate=True,
        taxable_amount_paise=taxable, cgst_paise=0, sgst_paise=0,
        igst_paise=igst, cess_paise=0, is_reverse_charge=False,
        invoice_type="Regular", supply_type="taxable",
        gst_invoice_category=category,
        original_invoice_ref="INV/1" if category is GSTInvoiceCategory.CDNR else None,
        original_invoice_date="2025-04-02" if category is GSTInvoiceCategory.CDNR else None,
        lines=[line])


# ── 1. the [S]-graded figures ────────────────────────────────────────────────

def test_the_cap_is_fifty_lakh_rupees_in_paise():
    """Rule 59(2): "up to a cumulative value of fifty lakh rupees in each
    month". Pinned as an integer so a rupee/paise slip cannot pass."""
    assert iff.CUMULATIVE_CAP_PAISE == 5_000_000_00


def test_the_window_is_the_first_to_the_thirteenth():
    assert (iff.WINDOW_OPENS_DAY, iff.WINDOW_CLOSES_DAY) == (1, 13)


def test_only_the_first_two_months_of_a_quarter_have_one():
    assert iff.MONTHS_IN_QUARTER_WITH_IFF == (1, 2)
    assert iff.month_has_iff(1) and iff.month_has_iff(2)
    assert not iff.month_has_iff(3)


def test_every_figure_is_written_from_knowledge_and_says_so():
    """Egress is refused at this environment's proxy, so nothing above could be
    read off the rule. `VERIFIED` is the claim about PROVENANCE."""
    assert iff.VERIFIED is False


# ── 2. what it carries, and what it does not ─────────────────────────────────

_ONE_OF_EVERYTHING = [
    _doc("INV/1", GSTInvoiceCategory.B2B),
    _doc("INV/2", GSTInvoiceCategory.SEZ_WP),
    _doc("INV/3", GSTInvoiceCategory.SEZ_WOP),
    _doc("INV/4", GSTInvoiceCategory.DEEMED_EXPORT),
    _doc("INV/5", GSTInvoiceCategory.B2CS, gstin=None),
    _doc("INV/6", GSTInvoiceCategory.B2CL, gstin=None),
    _doc("INV/7", GSTInvoiceCategory.EXP_WP, gstin=None),
    _doc("INV/8", GSTInvoiceCategory.NIL_EXEMPT, gstin=None, igst=0),
    _doc("CN/1", GSTInvoiceCategory.CDNR, txn_type="credit_note"),
    _doc("CN/2", GSTInvoiceCategory.CDNA, gstin=None, txn_type="credit_note"),
]


def test_it_carries_supplies_to_a_registered_person_and_nothing_else():
    built = iff.build_iff(_ONE_OF_EVERYTHING, GSTIN, PERIOD, month_in_quarter=2)
    sections = set(built.payload) - {"gstin", "fp"}
    assert sections == {"b2b", "cdnr"}


def test_an_sez_supply_and_a_deemed_export_are_carried():
    """Both recipients ARE registered persons, so the rule reaches them. They
    need no special case: `B2B_SECTION_CATEGORIES` already groups them, which
    is why nothing here restates the membership."""
    built = iff.build_iff(_ONE_OF_EVERYTHING, GSTIN, PERIOD, month_in_quarter=1)
    numbers = {inv["inum"] for g in built.payload["b2b"] for inv in g["inv"]}
    assert {"INV/1", "INV/2", "INV/3", "INV/4"} <= numbers


def test_a_b2c_supply_an_export_and_an_unregistered_note_are_named_not_dropped():
    built = iff.build_iff(_ONE_OF_EVERYTHING, GSTIN, PERIOD, month_in_quarter=1)
    named = {n["section"] for n in built.not_carried}
    assert {"b2cs", "b2cl", "exp", "cdnur", "nil"} <= named
    for entry in built.not_carried:
        assert entry["reason"].strip(), entry


# ── 3. the rule, not a list of sections ──────────────────────────────────────

def _sections_build_gstr1_can_emit() -> set:
    """Every key `build_gstr1` assigns into its payload dict.

    Read off the BUILDER's own source rather than listed here, so a section
    added there is a failure in this file rather than a silent absence from an
    early-furnished return — the discipline `test_the_browser_fallback_speaks_
    the_engines_vocabulary` applies to the Schedule III captions.
    """
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "domain/gst/gstr1_builder.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "build_gstr1")
    out = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "payload"
                    and isinstance(target.slice, ast.Constant)):
                out.add(target.slice.value)
    # The envelope, not a section.
    return out - {"gstin", "fp", "gt", "cur_gt"}


def test_every_gstr1_section_is_either_carried_or_named():
    emitted = _sections_build_gstr1_can_emit()
    assert len(emitted) >= 7, (
        f"only {sorted(emitted)} found — this guard is asserting almost nothing")
    decided = set(iff.SECTIONS_IN_IFF) | set(iff.SECTIONS_NOT_IN_IFF)
    undecided = emitted - decided
    assert not undecided, (
        f"{sorted(undecided)} can be emitted in a GSTR-1 and this module says "
        "nothing about whether Rule 59(2) reaches it. A section that is "
        "neither furnished nor named is one a CA cannot find.")


def test_nothing_is_named_that_the_builder_cannot_emit():
    """The other direction: a reason about a section that does not exist reads
    as a real absence and sends the CA looking for it."""
    emitted = _sections_build_gstr1_can_emit()
    assert set(iff.SECTIONS_NOT_IN_IFF) <= emitted
    assert set(iff.SECTIONS_IN_IFF) <= emitted


def test_the_registered_person_test_is_not_restated_here():
    """`B2B_SECTION_CATEGORIES` decides which categories ride in the `b2b`
    section, and a second list here would disagree with it the first time a
    category was added — which is the whole failure mode this module's value
    rests on avoiding."""
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "domain/gst/iff.py").read_text()
    body = re.sub(r'"""[\s\S]*?"""', "", src)
    assert "B2B_SECTION_CATEGORIES" in body
    for name in ("SEZ_WP", "SEZ_WOP", "DEEMED_EXPORT"):
        assert f"GSTInvoiceCategory.{name}" not in body, (
            f"{name} is named here as well as in B2B_SECTION_CATEGORIES")


# ── 4. the third month ───────────────────────────────────────────────────────

def test_the_third_month_of_a_quarter_is_refused():
    with pytest.raises(ValueError) as e:
        iff.build_iff(_ONE_OF_EVERYTHING, GSTIN, "062025", month_in_quarter=3)
    assert "twice" in str(e.value)


def test_a_month_whose_position_is_unknown_builds_and_says_so():
    """A CA may legitimately ask what a month would furnish before the quarter
    is established. Refusing would be a rule about the caller rather than
    about the Act."""
    built = iff.build_iff(_ONE_OF_EVERYTHING, GSTIN, PERIOD)
    assert built.payload.get("b2b")
    assert any("not established" in n for n in built.notes)


# ── 5. the cap reports, and never truncates ──────────────────────────────────

def test_over_the_cap_every_document_is_still_furnished_and_the_excess_stated():
    """Rule 59(2) lets the supplier furnish 'as he may consider necessary', so
    WHICH documents fit is the CA's choice. Trimming here would furnish a set
    that does not match the sales register with nothing on screen saying what
    was left out."""
    big = [_doc(f"INV/{i}", GSTInvoiceCategory.B2B, taxable=30_00_000_00,
                igst=5_40_000_00) for i in range(3)]
    built = iff.build_iff(big, GSTIN, PERIOD, month_in_quarter=1)
    numbers = {inv["inum"] for g in built.payload["b2b"] for inv in g["inv"]}
    assert numbers == {"INV/0", "INV/1", "INV/2"}, "a document was dropped"
    assert built.cap_exceeded is True
    assert built.cumulative_value_paise == 3 * (30_00_000_00 + 5_40_000_00)
    assert built.excess_paise == built.cumulative_value_paise - iff.CUMULATIVE_CAP_PAISE
    assert any("consider necessary" in n for n in built.notes)


def test_under_the_cap_nothing_is_flagged():
    built = iff.build_iff([_doc("INV/1", GSTInvoiceCategory.B2B)],
                          GSTIN, PERIOD, month_in_quarter=1)
    assert built.cap_exceeded is False and built.excess_paise == 0


def test_the_cap_is_measured_on_the_invoice_value_not_the_taxable_value():
    """Two readings of 'cumulative value' exist and the rule does not settle it
    in the sub-section. The invoice value is the LARGER, so it is the reading
    that cannot silently let a month through — and the module says which it
    used."""
    d = _doc("INV/1", GSTInvoiceCategory.B2B, taxable=100_00, igst=18_00)
    assert iff.document_value_paise(d) == 118_00
    assert "INVOICE VALUE" in iff.CAP_BASIS


# ── 6. what cannot be carried is named ───────────────────────────────────────

def test_an_sez_supply_with_no_recipient_gstin_is_named():
    built = iff.build_iff(
        [_doc("INV/9", GSTInvoiceCategory.SEZ_WP, gstin=None)],
        GSTIN, PERIOD, month_in_quarter=1)
    assert "b2b" not in built.payload
    assert any(n.get("reference_no") == "INV/9" for n in built.not_carried)


def test_amendments_are_named_rather_than_emitted():
    built = iff.build_iff(_ONE_OF_EVERYTHING, GSTIN, PERIOD, month_in_quarter=1)
    assert "b2ba" not in built.payload and "cdnra" not in built.payload
    assert any("Amendments" in n for n in built.notes)
    assert "could not be verified" in iff.AMENDMENTS_NOT_BUILT
