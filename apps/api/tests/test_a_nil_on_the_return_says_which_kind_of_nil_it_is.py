"""
GSTR-3B: a row that is nil because nothing here can derive it SAYS SO.

THE TWO NILS
    On a filed return, 0.00 means "this client had none". Four rows of this
    product's GSTR-3B mean something else — "this product cannot see it" — and
    on the form the two are indistinguishable:

      3.1.1(i)  and  3.1.1(ii)   §9(5) e-commerce supplies. Nothing marks a
                                 supply as made through an operator, so a
                                 restaurant's aggregator sales are counted in
                                 3.1(a) like any other outward supply.
      5                          exempt / nil-rated / non-GST INWARD supplies.
                                 A purchase bill is not classified that way here.
      4(D)(2)                    ineligible under §16(4) and the PoS rules,
                                 neither of which is tracked.

    Each already carried its reason — in a SOURCE COMMENT, beside the literal
    zero. That is the right place for the next programmer and no place at all
    for the CA about to file.

AND THE ONE THAT WAS ALREADY NAMED REACHED NOBODY
    `table_4a_gaps` has been in the response since GST-24 and no screen ever
    rendered it, so the 4(A)(4) ISD sentence was written, served and never
    seen. `_undeclarable_rows` is the superset that one panel renders.

WHAT THIS DOES NOT DO
    It changes no figure. Every row stays exactly as computed — nil — because
    the fix for an underivable row is a document this product does not model,
    not a number written from memory. The sentence travels BESIDE the payload,
    since a GSTN payload has nowhere to carry one: the same shape as
    `payload_gaps` on the GSTR-1 side and `cess_gaps`.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

API = pathlib.Path(__file__).resolve().parents[1]

from services.gst_return_service import _table_4a_gaps, _undeclarable_rows  # noqa: E402

EXPECTED_ROWS = ["4(A)(4)", "3.1.1(i)", "3.1.1(ii)", "5", "4(D)(2)"]


def test_every_underivable_row_is_named():
    assert [g["row"] for g in _undeclarable_rows()] == EXPECTED_ROWS


def test_the_4a_list_stays_the_authority_for_its_own_rows():
    """A superset by CONSTRUCTION, not by coincidence: _undeclarable_rows calls
    _table_4a_gaps rather than restating it, so PUR-18 removing IMPG from one
    cannot leave the other declaring a gap that no longer exists."""
    rows = _undeclarable_rows()
    for gap in _table_4a_gaps():
        assert gap in rows, f"{gap['row']} is in the 4(A) list and not in the superset"
    assert rows[:len(_table_4a_gaps())] == _table_4a_gaps()


@pytest.mark.parametrize("gap", _undeclarable_rows(), ids=lambda g: g["row"])
def test_each_gap_says_something(gap):
    assert gap["label"].strip()
    # Long enough to be a REASON rather than a restatement of the label. A
    # one-liner like "not modelled" is what this whole file argues against.
    assert len(gap["reason"]) > 80, f"{gap['row']}'s reason is too thin to act on"
    assert gap["reason"].strip().endswith("."), "a sentence, not a fragment"


def test_no_two_rows_share_a_reason():
    """3.1.1(i) and 3.1.1(ii) are the same GAP seen from two sides and the CA
    has different work to do about each — (ii) is the one that asks whether
    3.1(a) already carries the figure. A shared sentence would lose that."""
    reasons = [g["reason"] for g in _undeclarable_rows()]
    assert len(set(reasons)) == len(reasons)


def test_no_figure_is_asserted():
    """The reasons explain a nil; they must never state a rate, a threshold or
    an amount, because every one of these rows is underivable precisely
    because the document behind it is not modelled."""
    import re
    for gap in _undeclarable_rows():
        assert not re.search(r"\d+(\.\d+)?\s*(%|per cent)", gap["reason"]), (
            f"{gap['row']}'s reason states a rate")
        assert "₹" not in gap["reason"] and "Rs." not in gap["reason"], (
            f"{gap['row']}'s reason states an amount")


def test_the_computer_still_declares_every_one_of_them_nil():
    """The point is the SENTENCE, not a new figure. If a later change starts
    deriving one of these rows, this test fails and the row should leave the
    list rather than carry a gap that is no longer true."""
    src = (API / "domain/gst/gstr3b_computer.py").read_text()
    assert 'eco_zero = {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}' in src, (
        "3.1.1 is no longer a structural nil — remove its rows from _undeclarable_rows")
    assert '{"ty": "GST", "inter": 0, "intra": 0}' in src, (
        "Table 5 inward is no longer a structural nil — remove row 5")


def test_the_computers_comments_point_at_the_authority():
    """Each zero carries its reason in a comment AND names where the CA-facing
    sentence lives, so an edit to either one finds the other. Without this the
    two drift and the screen keeps explaining a nil that has been fixed."""
    src = (API / "domain/gst/gstr3b_computer.py").read_text()
    assert src.count("_undeclarable_rows") >= 3, (
        "a structurally-nil block no longer points at the gap authority")


def test_the_response_serves_the_superset_and_not_only_the_4a_slice():
    """The key the screen reads. Asserted on the SOURCE rather than by building
    a return, because compute_gstr3b needs a whole client's books; what matters
    here is that the key exists and is wired to the superset."""
    src = (API / "services/gst_return_service.py").read_text()
    tree = ast.parse(src)
    keys = {
        k.value for node in ast.walk(tree) if isinstance(node, ast.Dict)
        for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }
    assert "undeclarable_rows" in keys, "the response no longer serves the superset"
    assert '"undeclarable_rows": _undeclarable_rows(),' in src, (
        "the key is served from something other than the authority")
