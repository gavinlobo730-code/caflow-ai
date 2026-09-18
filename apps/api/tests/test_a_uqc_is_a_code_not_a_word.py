"""
A UNIT QUANTITY CODE IS A CODE, NOT A WORD.

`models/uqc.py` held CBIC's fixed UQC list and had ZERO importers: three
validators cited `VALID_UQC_CODES` in their COMMENTS and none imported it, so
the one authority for "which unit codes exist" was unreachable from every place
that asks. Meanwhile `gstr1_builder._build_hsn_summary` put `line.unit`
straight into Table 12's `uqc`, so three things reached a return unremarked:

    'PIECES'          the word, where the code is 'PCS'
    None              a JSON null where the schema wants a string
    10 BOX + 5 PCS    summed to 15 and filed as BOX

This module pins the authority, the three answers, and — the part that would
otherwise rot — that the browser's copy of the list still says the same thing.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from domain.gst import uqc
from domain.gst.classifier import GSTInvoiceCategory
from domain.gst.gstr1_builder import (
    InvoiceForGSTR1,
    InvoiceLine,
    _build_hsn_summary,
    _hsn_summary_and_gaps,
    build_gstr1,
)

REPO = Path(__file__).resolve().parents[3]
API = Path(__file__).resolve().parents[1]
WEB = REPO / "apps" / "web"


# ── the authority ────────────────────────────────────────────────────────────

def test_the_list_is_the_forty_five_codes_and_the_set_matches_it():
    """44 -> 45 on 18-09-2026: LTR (LITRES) was missing.

    The list here was transcribed from CBIC's published set and dropped one
    code between KME and MLT. It was found by diffing against NIC's own Master
    Codes on the e-invoice portal, which is the first time this list has been
    compared with a primary source rather than reviewed for plausibility — and
    45 codes all of which look right is exactly what an omission looks like.

    It cost a FALSE gap rather than a wrong figure, which is why nothing caught
    it: Table 12 reported "LTR is not a UQC" on every line of every dairy,
    paint, chemical, oil and beverage client. The dangerous part is the
    SUGGESTION — `closest_code` offered MLT, a thousand times smaller — so a CA
    who took the advice would have declared a quantity three orders of
    magnitude out on a return."""
    assert len(uqc.UQC_CODES) == 45
    assert ("LTR", "LITRES") in uqc.UQC_CODES
    assert len(uqc.VALID_UQC_CODES) == 45, "a duplicated code would shrink the set"
    assert all(c == c.strip().upper() for c, _ in uqc.UQC_CODES)


@pytest.mark.parametrize("value", ["PCS", "pcs", "  PCS  ", "NOS", "OTH", "KGS"])
def test_a_real_code_has_no_problem_however_it_is_typed(value):
    assert uqc.problem_with(value) is None
    assert uqc.is_valid(value)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_an_absent_unit_says_it_is_ABSENT_and_cites_rule_46h(value):
    problem = uqc.problem_with(value)
    assert problem is not None
    assert "No unit" in problem
    assert "46(h)" in problem, "the CA needs to know which rule requires it"
    assert uqc.normalise(value) is None


@pytest.mark.parametrize("word,code", [
    ("PIECES", "PCS"), ("CARTONS", "CTN"), ("BOTTLES", "BTL"),
    ("KILOGRAMS", "KGS"), ("DOZENS", "DOZ"),
])
def test_a_word_is_refused_and_its_code_is_SUGGESTED(word, code):
    problem = uqc.problem_with(word)
    assert problem is not None
    assert "not a Unit Quantity Code" in problem
    assert f"Did you mean {code}?" in problem
    assert uqc.closest_code(word) == code


def test_a_unit_with_no_plausible_code_is_refused_WITHOUT_a_guess():
    # 'HRS' is service hours — the normalisers' own example of a legacy
    # free-text value. There is no hours UQC, and inventing one would be worse
    # than the blank. An edit-distance matcher would have offered 'GRS'.
    problem = uqc.problem_with("HRS")
    assert problem is not None
    assert "Did you mean" not in problem
    assert uqc.closest_code("HRS") is None


def test_an_EXACT_label_beats_a_prefix_match(monkeypatch):
    """The two loops in `closest_code` do not disagree on TODAY's 45 codes —
    every exact label is also caught by the prefix pass — so deleting the
    exact one passes every other test here. It is kept because it is the loop
    that stays right when the list changes, and this pins that property
    directly rather than through a word that happens to exercise it.

    A suggestion that names the WRONG code is worse than no suggestion: the
    CA may take it, and then the return carries a unit they never meant.
    """
    monkeypatch.setattr(uqc, "UQC_CODES", [
        ("AAA", "BOX"),          # a prefix of the word, and listed FIRST
        ("BBB", "BOX OF TEN"),   # the word itself
    ])
    assert uqc.closest_code("BOX OF TEN") == "BBB", (
        "the prefix pass would have answered AAA; the exact pass must win")
    # And the prefix pass is still doing its own job for a partial word.
    assert uqc.closest_code("BOX OF") == "AAA"


def test_the_suggestion_is_never_a_substitution():
    """`closest_code` answers; nothing in the module rewrites the value."""
    source = (API / "domain" / "gst" / "uqc.py").read_text()
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "problem_with")
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    # Every return is either None or a message — never a code from the list.
    for node in returns:
        if node.value is None or isinstance(node.value, ast.Constant) and node.value.value is None:
            continue
        rendered = ast.dump(node)
        assert "VALID_UQC_CODES" not in rendered or "in " in rendered


def test_one_unit_for_reports_a_MIXTURE_and_stays_silent_on_agreement():
    assert uqc.one_unit_for(["BOX", "PCS"]) == ["BOX", "PCS"]
    assert uqc.one_unit_for(["BOX", "box", " BOX "]) is None
    assert uqc.one_unit_for(["BOX"]) is None
    assert uqc.one_unit_for([]) is None


def test_an_UNRECORDED_unit_is_not_counted_as_a_distinct_one():
    """Otherwise one line reports two gaps under two names."""
    assert uqc.one_unit_for([None, "BOX"]) is None
    assert uqc.one_unit_for(["", "BOX", None]) is None
    assert uqc.one_unit_for([None, "BOX", "PCS"]) == ["BOX", "PCS"]


def test_models_uqc_re_exports_the_SAME_objects_not_a_copy():
    from models import uqc as legacy
    assert legacy.UQC_CODES is uqc.UQC_CODES
    assert legacy.VALID_UQC_CODES is uqc.VALID_UQC_CODES


# ── the return ───────────────────────────────────────────────────────────────

def _line(hsn="8471", unit="PCS", qty=1.0, taxable=100_000):
    return InvoiceLine(hsn_sac_code=hsn, description="Widget", quantity=qty,
                       unit=unit, rate_paise=taxable, taxable_paise=taxable,
                       gst_rate=18.0, cgst_paise=9_000, sgst_paise=9_000,
                       igst_paise=0, cess_paise=0)


def _invoice(ref, lines, transaction_type="sales_invoice"):
    return InvoiceForGSTR1(
        id=ref, transaction_type=transaction_type, reference_no=ref,
        transaction_date="2026-06-10", party_gstin="27AAACI1195H1ZT",
        party_name="Acme", place_of_supply="27", is_interstate=False,
        taxable_amount_paise=sum(l.taxable_paise for l in lines),
        cgst_paise=sum(l.cgst_paise for l in lines),
        sgst_paise=sum(l.sgst_paise for l in lines),
        igst_paise=0, cess_paise=0, is_reverse_charge=False,
        invoice_type="Regular", supply_type="B2B",
        gst_invoice_category=GSTInvoiceCategory.B2B,
        original_invoice_ref=None, original_invoice_date=None, lines=lines)


def _build(invoices):
    """Answer the two questions this module is NOT about.

    The turnover is stated so GST-17's HSN digit requirement is satisfied
    rather than reported, and `cancelled_documents=[]` says Table 13's
    cancelled numbers WERE read and there were none — which is true of every
    fixture here. Both leave `out.gaps == []` meaning what it says: a clean
    return reports nothing at all, rather than nothing about units.
    """
    return build_gstr1(invoices, gstin="27AAACI1195H1ZT", period="062026",
                       aggregate_turnover_paise=100_00_00_000,
                       cancelled_documents=[])


def _kinds(payload):
    return {g["kind"] for g in payload.gaps}


def test_a_clean_return_reports_NOTHING():
    out = _build([_invoice("INV/1", [_line(unit="PCS", qty=15.0)])])
    assert out.gaps == []
    assert out.payload["hsn"]["data"][0]["uqc"] == "PCS"


def test_a_word_in_the_unit_field_is_REPORTED_and_still_filed():
    out = _build([_invoice("INV/1", [_line(unit="PIECES")])])
    assert uqc.GAP_UQC_NOT_A_CODE in _kinds(out)
    gap = next(g for g in out.gaps if g["kind"] == uqc.GAP_UQC_NOT_A_CODE)
    assert gap["reference_no"] == "INV/1"
    assert gap["hsn_sc"] == "8471"
    assert "PCS" in gap["reason"]
    # REPORTED, NEVER REFUSED — the row is still built, because refusing the
    # whole return for one line is how a CA learns to skip the validator.
    assert out.payload["hsn"]["data"][0]["uqc"] == "PIECES"


def test_an_absent_unit_is_REPORTED_under_its_own_kind():
    out = _build([_invoice("INV/1", [_line(unit=None)])])
    assert uqc.GAP_UQC_NOT_RECORDED in _kinds(out)
    assert uqc.GAP_UQC_NOT_A_CODE not in _kinds(out), \
        "an absent unit and a wrong one are different things to go and fix"


def test_the_two_wrong_answers_are_NOT_INTERCHANGEABLE():
    absent = next(g for g in _build(
        [_invoice("A", [_line(unit=None)])]).gaps)
    wrong = next(g for g in _build(
        [_invoice("B", [_line(unit="PIECES")])]).gaps)
    assert absent["kind"] != wrong["kind"]
    assert absent["reason"] != wrong["reason"]


def test_one_hsn_supplied_in_two_units_is_REPORTED_with_both_named():
    out = _build([_invoice("INV/1", [_line(unit="BOX", qty=10.0),
                                     _line(unit="PCS", qty=5.0)])])
    assert uqc.GAP_UQC_MIXED_FOR_ONE_HSN in _kinds(out)
    gap = next(g for g in out.gaps
               if g["kind"] == uqc.GAP_UQC_MIXED_FOR_ONE_HSN)
    assert "BOX" in gap["reason"] and "PCS" in gap["reason"]
    # The FIGURE is unchanged: what the portal gets is not silently altered on
    # a reading of a schema this environment cannot fetch. The gap says the
    # quantity is a sum of two units, which is the fact the number hides.
    row = out.payload["hsn"]["data"][0]
    assert row["qty"] == 15.0
    assert row["uqc"] == "BOX"
    assert "sum" in gap["reason"]


def test_the_mixture_is_reported_ACROSS_INVOICES_not_only_within_one():
    out = _build([_invoice("INV/1", [_line(unit="BOX", qty=10.0)]),
                  _invoice("INV/2", [_line(unit="PCS", qty=5.0)])])
    gap = next(g for g in out.gaps
               if g["kind"] == uqc.GAP_UQC_MIXED_FOR_ONE_HSN)
    assert "INV/1" in gap["reference_no"] and "INV/2" in gap["reference_no"]


def test_two_HSNs_each_in_their_own_unit_is_NOT_a_mixture():
    out = _build([_invoice("INV/1", [_line(hsn="8471", unit="BOX"),
                                     _line(hsn="8523", unit="PCS")])])
    assert uqc.GAP_UQC_MIXED_FOR_ONE_HSN not in _kinds(out)


def test_a_line_with_NO_HSN_has_its_UNIT_left_alone():
    """The UNIT gap walk and the row walk must agree about what is in scope.

    A line with no HSN is not in Table 12 at all, so reporting the unit it was
    supplied in would send a CA to fix a line this table does not carry.

    THE DIGIT GAP IS THE OPPOSITE AND DELIBERATELY SO (GST-17): a line with no
    HSN is precisely what the digit requirement is about, and it is missing
    from Table 12 BECAUSE of the thing being reported. Two questions, two
    scopes — the next test is the other half.
    """
    out = _build([_invoice("INV/1", [_line(hsn="", unit="PIECES"),
                                     _line(hsn="8471", unit="PCS")])])
    assert uqc.GAP_UQC_NOT_A_CODE not in _kinds(out)
    assert uqc.GAP_UQC_NOT_RECORDED not in _kinds(out)


def test_a_line_with_NO_HSN_is_reported_for_its_MISSING_CODE():
    from domain.gst.gstr1_builder import GAP_HSN_DIGITS
    out = _build([_invoice("INV/1", [_line(hsn="", unit="PCS"),
                                     _line(hsn="8471", unit="PCS")])])
    assert GAP_HSN_DIGITS in _kinds(out)
    gap = next(g for g in out.gaps if g["kind"] == GAP_HSN_DIGITS)
    assert gap["reference_no"] == "INV/1"


def test_a_credit_notes_lines_are_reported_too():
    """Notes NET against Table 12, so their units are filed in it."""
    note = _invoice("CN/1", [_line(unit="PIECES")],
                    transaction_type="credit_note")
    out = _build([_invoice("INV/1", [_line(unit="PCS")]), note])
    assert uqc.GAP_UQC_NOT_A_CODE in _kinds(out)


def test_case_and_whitespace_alone_are_not_a_gap():
    out = _build([_invoice("INV/1", [_line(unit=" pcs ")])])
    assert out.gaps == []


def test_the_rows_only_wrapper_still_answers_a_plain_list():
    """Three test modules call `_build_hsn_summary` and must keep working."""
    invoices = [_invoice("INV/1", [_line()])]
    rows = _build_hsn_summary(invoices, 100_00_00_000)
    assert isinstance(rows, list)
    assert rows == _hsn_summary_and_gaps(invoices, 100_00_00_000)[0]


def test_the_gaps_ride_the_SAME_list_the_screen_already_renders():
    """`payload_gaps` is rendered by app/gst/gstr1/page.tsx — a new list would
    need a new renderer and would be invisible until somebody wrote one."""
    out = _build([_invoice("INV/1", [_line(unit="PIECES")])])
    assert any(g["kind"] == uqc.GAP_UQC_NOT_A_CODE for g in out.gaps)
    assert all({"kind", "reference_no", "reason"} <= set(g) for g in out.gaps)


# ── the browser's copy, pinned from this side ────────────────────────────────

def test_the_browser_list_is_the_SAME_list_in_the_same_order():
    """THE SCHEDULE III CAPTION LESSON, applied before it costs anything.

    `apps/web/lib/constants/uqc.ts` is the keystroke mirror — seven editors
    render their unit dropdown from it — and its docstring claims it mirrors
    the Python list. Nothing held it to that. The caption list made exactly
    that claim and had drifted in BOTH directions at once, silently discarding
    nine of fifty mapped accounts in production.

    Written on the PYTHON side deliberately: a guard in `apps/web` asserting
    the browser against a copy of itself passes whenever both drift together.
    """
    ts = (WEB / "lib" / "constants" / "uqc.ts").read_text()
    pairs = re.findall(r'\{\s*code:\s*"([A-Z]+)"\s*,\s*label:\s*"([^"]+)"\s*\}', ts)
    assert len(pairs) == 45, (
        f"parsed {len(pairs)} codes out of the browser list, expected 45 — "
        f"a parse that silently finds none would make this test vacuous")
    assert [tuple(p) for p in pairs] == uqc.UQC_CODES, (
        "apps/web/lib/constants/uqc.ts has drifted from domain/gst/uqc.py. "
        "The browser dropdown is what a CA picks from and the Python list is "
        "what the return is checked against; a code in one and not the other "
        "is either an un-pickable valid unit or a pickable invalid one.")


def test_no_THIRD_copy_of_the_list_appears_in_the_repo():
    """One authority and one mirror. A third is what this finding was."""
    holders = []
    for path in list((API / "domain").rglob("*.py")) + \
            list((API / "models").rglob("*.py")) + \
            list((API / "services").rglob("*.py")) + \
            list((API / "routers").rglob("*.py")):
        text = path.read_text()
        # Four distinctive codes; a real second list carries them all.
        if all(f'"{c}"' in text for c in ("BDL", "GYD", "QTL", "TGM")):
            holders.append(path.relative_to(API).as_posix())
    assert holders == ["domain/gst/uqc.py"], (
        f"more than one copy of the UQC list in apps/api: {holders}")


# ── every door asks the authority ────────────────────────────────────────────

_UNIT_FIELDS = {"unit", "uqc"}
_MODELS_WITH_A_UNIT = ["models/service_catalogue.py", "models/invoices.py",
                       "models/firm_hsn_library.py"]


def _classes_taking_a_unit():
    """Every request model with a unit-of-measure field, DERIVED from the code.

    Not a hand-written list: a model added later with a `unit` or `uqc` field
    joins this test by existing, and fails until it delegates. A hand-written
    list is what lets the next door be the one nobody guarded.
    """
    found = []
    for rel in _MODELS_WITH_A_UNIT:
        tree = ast.parse((API / rel).read_text())
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            for stmt in cls.body:
                if isinstance(stmt, ast.AnnAssign) and \
                        isinstance(stmt.target, ast.Name) and \
                        stmt.target.id in _UNIT_FIELDS:
                    found.append((rel, cls.name, stmt.target.id))
    return found


def test_the_derivation_finds_every_door_and_is_not_vacuous():
    doors = _classes_taking_a_unit()
    assert len(doors) >= 5, (
        f"only {len(doors)} doors found — the AST walk has stopped seeing "
        f"fields and every test below it is vacuous: {doors}")
    names = {c for _, c, _ in doors}
    # The pairs that matter: a create door and its PATCH twin.
    assert {"ServiceCatalogueIn", "ServiceCatalogueUpdateIn"} <= names
    assert {"FirmHsnLibraryIn", "FirmHsnLibraryUpdateIn"} <= names


@pytest.mark.parametrize("rel,cls_name,field", _classes_taking_a_unit())
def test_every_door_that_takes_a_unit_DELEGATES_to_the_one_normaliser(
        rel, cls_name, field):
    """Not `v.strip().upper()` spelled a fifth time, and PER CLASS.

    This is the whole shape of the finding restated as a rule. The list had
    zero importers because every door answered the question itself: two
    respelled the normalisation and cited the authority in a comment, and
    `firm_hsn_library` — the door whose value is served as a HINT that
    pre-fills an invoice line, so it propagates — had no validator at all.

    Per CLASS rather than per module, because a module-level walk passes when
    only ONE of a create/PATCH pair is guarded, and this codebase's own rule
    is that a validator on one door is one PATCH away from being none.
    """
    tree = ast.parse((API / rel).read_text())
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == cls_name)

    def guards(node) -> bool:
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            name = getattr(dec.func, "id", None) or getattr(dec.func, "attr", None)
            if name != "field_validator":
                continue
            # EXACT argument. "unit" is a substring of "opening_qty_units",
            # and matching loosely pulled in validators with nothing to do
            # with a unit of measure — which would have made this test fail
            # for the wrong reason, or pass for one.
            if any(isinstance(a, ast.Constant) and a.value == field
                   for a in dec.args):
                return True
        return False

    validators = [n for n in cls.body
                  if isinstance(n, ast.FunctionDef) and guards(n)]
    assert validators, (
        f"{rel}:{cls_name} takes a `{field}` and has no validator on it. "
        f"Every door that accepts a unit of measure must normalise it "
        f"through `domain/gst/uqc.normalise`.")
    for fn in validators:
        body = ast.dump(fn)
        assert "normalise" in body, (
            f"{rel}:{cls_name}.{fn.name} does not ask "
            f"`domain/gst/uqc.normalise`. Respelling the normalisation is how "
            f"the authority came to have zero importers in the first place.")
        assert "'upper'" not in body and '"upper"' not in body, (
            f"{rel}:{cls_name}.{fn.name} still spells the normalisation itself")


def test_no_door_REFUSES_a_unit_outside_the_list():
    """The carve-out the normalisers recorded is still right and still load-
    bearing: a product or a line may carry a legacy free-text unit, and a
    refusal at the API boundary would make that row un-editable for any
    unrelated change. The RETURN reports instead — GST-29's split."""
    from models.firm_hsn_library import FirmHsnLibraryIn
    from models.invoices import InvoiceLineIn
    from models.service_catalogue import ServiceCatalogueIn

    assert ServiceCatalogueIn(client_id="c1", name="X", kind="good",
                              unit="HRS").unit == "HRS"
    assert InvoiceLineIn(description="X", quantity=1, rate_paise=1,
                         service_catalogue_id="s1", unit="HRS").unit == "HRS"
    assert FirmHsnLibraryIn(hsn_code="8471", description="X",
                            hsn_type="goods", uqc="HRS").uqc == "HRS"
