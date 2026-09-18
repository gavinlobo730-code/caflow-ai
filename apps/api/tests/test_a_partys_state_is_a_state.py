"""
A PARTY'S STATE CODE BECOMES AN INVOICE'S PLACE OF SUPPLY, AND NOTHING CHECKED IT.

`domain/gst/place_of_supply.recipient_place_of_supply` is the four-source chain
CLAUDE.md describes, and its second link — the customer's own recorded state —
returned whatever was stored. The link BELOW it, the GSTIN prefix, has always
been checked against the state list, with a comment saying "so a truncated or
garbage value cannot become a place of supply". Two halves of one chain
disagreeing about the same question, which is the shape `supplier_state_code`
had until 18-09-2026 — and `supplier_state_code`'s own `state_code` branch had
it too, on the other side of the comparison.

And no door refused one. `SalesInvoiceIn.place_of_supply` and
`ReceiptIn.place_of_supply` have been validated against this very list for
months; the same value typed onto the CUSTOMER was stored and then used. So the
place of supply decides CGST+SGST against IGST (IGST §§7, 8) off a field with
no rule on it, and it is a CGST Rule 46(n) particular of the document.

TWO FIXES, DELIBERATELY DIFFERENT IN KIND.

  * The DOORS refuse. `models/parties._state_code_problem` on all four of
    `CustomerIn`, `CustomerUpdateIn`, `VendorIn`, `VendorUpdateIn` — a
    validator on the create door only is one PATCH from being none, which this
    file has now recorded five times.
  * The RESOLVER falls through. It is a fallback chain, so an unusable link is
    exactly what the next one is for; raising there would refuse to build an
    invoice over a field that can be corrected on the customer master, and it
    also repairs rows written before the door existed or straight over
    PostgREST.

THE LIST IS THE PLACE-OF-SUPPLY ONE AND NOT THE GSTIN ONE. It holds 96
(outside India), which is what GSTN requires on an export — the GSTIN list
would refuse exactly the party this field exists to describe. `core/validators`
now names all three lists and what each is for, because the audit that found
this also claimed the third one was dead, and it is not: `derive_state_code`
and `validate_state_code` read it for the FIRM's own registration state.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from domain.gst import place_of_supply as pos
from domain.gst.validator import VALID_STATE_CODES
from models.parties import (
    CustomerIn,
    CustomerUpdateIn,
    VendorIn,
    VendorUpdateIn,
    _state_code_problem,
)

API = Path(__file__).resolve().parents[1]

#: A real GSTIN with a sound check digit; the party models refuse a bad one.
GSTIN_27 = "27AAACI1195H1ZM"
CLIENT = "11111111-1111-1111-1111-111111111111"

#: Parsed once: the AST guard below asks each CLASS's own body, so it needs the
#: module rather than a bound method (whose source is indented and, for a
#: Pydantic validator, wrapped).
_PARTIES = ast.parse((Path(__file__).resolve().parents[1]
                      / "models/parties.py").read_text())


# ── the rule ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", ["27", "07", "96", "97", "38", " 27 "])
def test_a_real_state_code_has_no_problem(code):
    assert _state_code_problem(code) is None


@pytest.mark.parametrize("code", [None, "", "   "])
def test_an_absent_state_code_is_not_a_problem(code):
    """The column is nullable and most customers have no GSTIN either.

    Refusing an absence would make the field mandatory by accident, and the
    resolver has three more links for exactly that case.
    """
    assert _state_code_problem(code) is None


@pytest.mark.parametrize("code", [
    "MH",          # the postal abbreviation
    "Maharashtra", # the name
    "99",          # Centre Jurisdiction: a registration state, not a supply's
    "00",
    "51",
    "2",
    "270",
])
def test_anything_that_is_not_a_state_code_is_REFUSED(code):
    problem = _state_code_problem(code)
    assert problem is not None
    assert "place of supply" in problem, \
        "the CA needs to know what this field decides, not that it is invalid"


def test_the_list_is_the_PLACE_OF_SUPPLY_one_and_holds_96():
    """96 is where an export goes and no registration begins with it.

    Using `domain/gst/gstin`'s list instead would refuse every export
    customer — the exact party a `state_code` of 96 describes.
    """
    assert "96" in VALID_STATE_CODES
    from domain.gst.gstin import VALID_STATE_CODES as REGISTRATION
    assert "96" not in REGISTRATION
    assert _state_code_problem("96") is None


# ── the four doors ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", [CustomerIn, VendorIn])
def test_the_create_doors_refuse(model):
    with pytest.raises(ValueError, match="not a GST state code"):
        model(client_id=CLIENT, name="Acme", state_code="MH")
    assert model(client_id=CLIENT, name="Acme",
                 state_code="27").state_code == "27"


@pytest.mark.parametrize("model", [CustomerUpdateIn, VendorUpdateIn])
def test_the_PATCH_doors_refuse_TOO(model):
    """A validator on the create door only is one PATCH from being none."""
    with pytest.raises(ValueError, match="not a GST state code"):
        model(state_code="Maharashtra")
    assert model(state_code="27").state_code == "27"
    assert model(name="Acme").state_code is None, \
        "a PATCH that does not send the field must not be refused for it"


@pytest.mark.parametrize("model", [CustomerIn, CustomerUpdateIn, VendorIn, VendorUpdateIn])
def test_every_door_asks_the_rule(model):
    """THE RULE, not a list of four spellings.

    Walks each class's own `validate_identifiers` for a call to the shared
    helper, PER CLASS — a module-level scan passes when only one of a
    create/PATCH pair is guarded, which is exactly what these four were.
    """
    cls = next(n for n in _PARTIES.body
               if isinstance(n, ast.ClassDef) and n.name == model.__name__)
    called = {n.func.id for n in ast.walk(cls)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_state_code_problem" in called, \
        f"{model.__name__} does not ask the state-code rule"


def test_the_GSTIN_cross_check_still_fires_and_is_a_DIFFERENT_answer():
    """Two facts about one field, and they were not interchangeable before.

    The models have refused a state_code disagreeing with the GSTIN prefix
    since they were written — a fact about two fields together — and said
    nothing about whether either was a state at all.
    """
    with pytest.raises(ValueError, match="does not match state_code"):
        CustomerIn(client_id=CLIENT, name="Acme", gstin=GSTIN_27,
                   state_code="29")


# ── the resolver ─────────────────────────────────────────────────────────────

def test_a_junk_recorded_state_FALLS_THROUGH_to_the_GSTIN():
    code, source = pos.recipient_place_of_supply(
        stated=None,
        customer={"state_code": "Maharashtra", "gstin": "29AAACI1195H1ZI"},
        supplier_state="07")
    assert (code, source) == ("29", pos.SOURCE_CUSTOMER_GSTIN)


def test_and_then_to_the_SUPPLIER_when_there_is_no_GSTIN_either():
    code, source = pos.recipient_place_of_supply(
        stated=None, customer={"state_code": "ZZ"}, supplier_state="07")
    assert (code, source) == ("07", pos.SOURCE_SUPPLIER_STATE)


def test_a_REAL_recorded_state_is_still_preferred_over_the_GSTIN():
    """The order of the chain is unchanged; only the gate is new."""
    code, source = pos.recipient_place_of_supply(
        stated=None,
        customer={"state_code": "27", "gstin": "29AAACI1195H1ZI"},
        supplier_state="07")
    assert (code, source) == ("27", pos.SOURCE_CUSTOMER_STATE)


def test_the_SUPPLIER_side_gates_its_own_state_too():
    """`is_interstate` compares the two, so junk on either side decides it.

    An unusable supplier state answered True against almost any place of
    supply, so an intra-state supply was charged IGST.
    """
    assert pos.supplier_state_code({"state_code": "Maharashtra"}) is None
    assert pos.supplier_state_code({"state_code": "27"}) == "27"
    assert pos.is_interstate({"state_code": "Maharashtra"}, "27") is None, \
        "unknown, not inter-state — a default that is wrong half the time"


def test_both_halves_of_the_resolver_ask_the_SAME_list():
    """The defect was two halves of one chain answering differently.

    Asserted on the source, because the two functions are one rule and a
    second list in either is how they came apart in the first place.
    """
    src = inspect.getsource(pos)
    assert src.count("_VALID_STATE_CODES()") >= 4, \
        "each branch that returns a state must have gated it"
    assert "VALID_STATE_CODES = " not in src, \
        "place_of_supply must not keep its own copy of the list"


# ── the third list is NOT dead, and that is recorded ─────────────────────────

def test_core_validators_state_list_HAS_READERS():
    """The audit that found the defect above also claimed this list was dead.

    It is not: `validate_state_code` and `derive_state_code` both read it, for
    the FIRM's own registration state and an internal client's — a third
    question, with 99 in it and the place-of-supply list's 96 as well. Deleting
    it would have broken `routers/practice` and `internal_client_service`.
    """
    from core import validators as cv
    src = inspect.getsource(cv)
    assert src.count("_VALID_STATE_CODES") >= 4, "declared, plus its readers"
    assert cv.derive_state_code("27", None, None) == "27"
    assert cv.derive_state_code("ZZ", None, "29AAACI1195H1ZI") == "29"
    assert cv.validate_state_code("MH") is not None


def test_the_three_lists_are_named_where_a_fourth_would_be_added():
    """Written once, in the module the next reader will reach for.

    Three questions — a registration's state, a GSTIN's prefix, a place of
    supply — and they differ by exactly 96 and 99. A reader who finds one of
    them and not the others is the reader who collapses them.
    """
    src = (API / "core/validators.py").read_text()
    for name in ("domain/gst/gstin.VALID_STATE_CODES",
                 "domain/gst/validator.VALID_STATE_CODES",
                 "indianStates.ts"):
        assert name in src, f"{name} is not named beside the list it differs from"
