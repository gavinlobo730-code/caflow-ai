"""
INV-03's other two conveniences and INV-09's part 3, which each finding
deferred to the other so neither was built (migration 409).

THE THREE RULES THIS PINS

  1. A quantity typed in the ALTERNATE unit is converted at the door and the
     stock ledger never learns a second unit exists. The conversion REFUSES
     where three decimals cannot hold it, because truncating understates what
     moved and rounding up overstates it and neither direction is safe on a
     stock position.

  2. An ABSENT reorder level is its own state and is never read as zero. Zero
     is a real answer — "tell me when it runs out" — so the two must not
     produce the same report row.

  3. An unrecorded item GROUP is its own group, never folded into another and
     never dropped.
"""
from __future__ import annotations

import ast
import pathlib
from decimal import Decimal

import pytest

from domain.inventory import reorder
from domain.inventory.units import (
    AlternateUnit, Conversion, describe, problem_with_pair, to_alternate, to_primary,
)

_API = pathlib.Path(__file__).resolve().parents[1]


# ── 1. the conversion ────────────────────────────────────────────────────────

def test_a_quantity_in_the_alternate_unit_becomes_primary_units():
    assert to_primary("3.5", AlternateUnit("BOX", Decimal(12))).quantity == Decimal("42.0")


def test_a_conversion_needing_a_fourth_decimal_is_refused_not_rounded():
    """The whole argument for the module. Truncating 0.0012 to 0.001 leaves
    stock on the books that has gone; rounding to 0.002 writes off stock that
    is there. Neither is safe, so it refuses and names the figure."""
    answer = to_primary("0.0001", AlternateUnit("BOX", Decimal(12)))
    assert answer.quantity is None
    assert "0.0012" in answer.refusal
    assert "3 decimals" in answer.refusal


def test_a_conversion_answer_never_carries_both_or_neither():
    for qty, unit in [("3", AlternateUnit("BOX", Decimal(12))),
                      ("0.0001", AlternateUnit("BOX", Decimal(12))),
                      ("x", AlternateUnit("BOX", Decimal(12))),
                      ("3", AlternateUnit("BOX", Decimal(0)))]:
        a = to_primary(qty, unit)
        assert isinstance(a, Conversion)
        assert (a.quantity is None) != (a.refusal is None), (qty, unit)


def test_the_display_direction_may_be_fractional_and_stores_nothing():
    """10 PCS of a 12-PCS box really is 0.833 of a box. A screen that refused
    to say so would be less useful than one that rounds the label — and
    nothing stores this."""
    assert to_alternate(10, AlternateUnit("BOX", Decimal(12))) == Decimal("0.833")


def test_the_sentence_says_which_way_the_factor_points():
    assert describe(AlternateUnit("BOX", Decimal(12)), "PCS") == "1 BOX = 12 PCS"


@pytest.mark.parametrize("primary,alternate,factor,fragment", [
    ("PCS", "BOXES", 12, "not a Unit Quantity Code"),
    ("PCS", "PCS", 12, "same as the primary unit"),
    ("PCS", "BOX", None, "must be a number"),
    ("PCS", "BOX", 0, "greater than zero"),
    ("PCS", "BOX", -1, "greater than zero"),
    (None, "BOX", 12, "needs a primary unit"),
    ("PCS", None, 12, "no alternate unit"),
])
def test_the_pair_is_refused_with_its_own_reason(primary, alternate, factor, fragment):
    problem = problem_with_pair(primary, alternate, factor)
    assert problem and fragment in problem, (primary, alternate, factor, problem)


def test_no_alternate_unit_at_all_is_fine():
    """The state every row is in before migration 409, and the right answer for
    most items for ever."""
    assert problem_with_pair("PCS", None, None) is None
    assert problem_with_pair(None, None, None) is None


def test_the_stock_ledger_never_learns_a_second_unit_exists():
    """The discipline migration 398 took about a batch, restated: a column that
    COULD change what is stored is the one that eventually does. `record_stock_
    out` and the position reader must not mention the alternate unit."""
    for name in ("domain/inventory_service.py", "domain/reporting/stock_position.py",
                 "domain/inventory/costing.py"):
        src = (_API / name).read_text(encoding="utf-8")
        assert "alternate_unit" not in src, name
        assert "units_per_alternate" not in src, name


# ── 2. the reorder level ─────────────────────────────────────────────────────

def _goods(**over):
    row = {"id": "a", "name": "Cement", "kind": "good", "unit": "BAG",
           "category": "Raw Material"}
    row.update(over)
    return [row]


def test_an_absent_level_is_its_own_state_and_is_not_zero():
    absent = reorder.assess(_goods(), {"a": "0"})
    assert absent["groups"][0].lines[0].state == reorder.NOT_SET
    assert absent["groups"][0].lines[0].note == reorder.NO_LEVEL_RECORDED
    assert absent["no_level_recorded"] == 1
    assert absent["to_reorder"] == 0

    recorded = reorder.assess(_goods(reorder_level_units="0"), {"a": "0"})
    assert recorded["groups"][0].lines[0].state == reorder.AT
    assert recorded["to_reorder"] == 1
    assert recorded["no_level_recorded"] == 0


def test_at_the_level_counts_as_needing_a_reorder():
    """A strict `<` would hold the order until the item is already short."""
    at = reorder.assess(_goods(reorder_level_units="100"), {"a": "100"})
    assert at["groups"][0].lines[0].state == reorder.AT
    assert at["to_reorder"] == 1


def test_an_oversold_position_is_below_every_level_including_zero():
    out = reorder.assess(_goods(reorder_level_units="0"), {"a": "-5"})
    line = out["groups"][0].lines[0]
    assert line.state == reorder.BELOW
    assert line.shortfall_units == Decimal(5)


def test_an_item_that_has_never_moved_is_nil_on_hand_not_skipped():
    out = reorder.assess(_goods(reorder_level_units="10"), {})
    assert out["groups"][0].lines[0].on_hand_units == Decimal(0)
    assert out["to_reorder"] == 1


def test_a_service_and_an_archived_item_are_not_stock():
    out = reorder.assess(
        [{"id": "s", "name": "Audit", "kind": "service"},
         {"id": "x", "name": "Old", "kind": "good", "is_active": False}], {})
    assert out["items_considered"] == 0


# ── 3. the item group ────────────────────────────────────────────────────────

def test_two_spellings_of_one_group_are_one_group_and_keep_the_first_spelling():
    out = reorder.assess(
        [{"id": "a", "name": "A", "kind": "good", "category": "Raw Material"},
         {"id": "b", "name": "B", "kind": "good", "category": "raw  material"}], {})
    assert len(out["groups"]) == 1
    assert out["groups"][0].group == "Raw Material"


def test_an_unrecorded_group_is_its_own_row_and_sorts_last():
    out = reorder.assess(
        [{"id": "a", "name": "A", "kind": "good", "category": None},
         {"id": "b", "name": "B", "kind": "good", "category": "Raw Material"}], {})
    assert [g.group for g in out["groups"]] == ["Raw Material", reorder.NOT_GROUPED]


# ── 4. the doors ─────────────────────────────────────────────────────────────

def test_both_catalogue_doors_ask_the_authority_about_the_pair():
    """A validator on the create door only is one PATCH from being none — the
    shape `opening_qty_units` was in until INV-09 part 1."""
    src = (_API / "models/service_catalogue.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    for door in ("ServiceCatalogueIn", "ServiceCatalogueUpdateIn"):
        body = ast.dump(classes[door])
        assert "units_per_alternate" in body, door
        assert "reorder_level_units" in body, door
        assert "quantity_violation" in body or "a_stored_quantity_keeps_three_decimals" in body, door
    # The PATCH door cannot settle the pair from the request alone, so the
    # router asks the same authority against the merged row.
    router = (_API / "routers/service_catalogue.py").read_text(encoding="utf-8")
    assert "problem_with_pair" in router
    assert "model_fields_set" in router


def _code_only(path: pathlib.Path) -> str:
    """The module's CODE with every docstring removed.

    A guard that matches a WORD trips on prose stating that very rule — this
    module's own docstring explains why `stock_qty_units` is not read, and a
    plain substring scan fails on the explanation. Seventh time this pattern
    has been hit in this repository; strip the prose, keep the rule.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and ast.get_docstring(node):
            node.body = node.body[1:]
    return ast.dump(tree)


def test_the_reorder_report_reads_the_ledger_and_not_the_cached_column():
    """Migration 188 documents that cached column as a cache. A purchasing
    prompt off a drifted one says there is stock there is not."""
    path = _API / "services/reorder_service.py"
    assert "stock_position_service" in path.read_text(encoding="utf-8")
    assert "stock_qty_units" not in _code_only(path)


def test_the_docstring_strip_does_not_make_the_scan_vacuous():
    """The negative control for the helper above: it must still SEE code."""
    code = _code_only(_API / "services/reorder_service.py")
    assert "stock_position_service" in code
    assert "reorder" in code
