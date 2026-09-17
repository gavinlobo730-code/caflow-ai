"""Every door that takes a quantity asks `domain.quantity.quantity_violation`.

WHAT WAS WRONG

`quantity_delta`, `running_qty_units`, `stock_qty_units` and `opening_qty_units`
are all NUMERIC(10,3) (migration 188), and `domain/quantity.py` exists to stop a
fourth decimal being accepted and then silently rounded by Postgres — its own
docstring says so. Five doors asked it: the stock adjustment, the count sheet,
the invoice line, the sales-cycle line and the purchase-cycle lines.

THE OPENING-STOCK DOOR DID NOT (INV-09). `ServiceCatalogueIn.opening_qty_units`
and its PATCH twin carried a non-negative check and nothing else, so
`opening_qty_units=1.2345` was ACCEPTED while the identical figure on a stock
adjustment was refused — and `inventory_service.seed_opening_balance` then
derives the opening VALUE from the unrounded figure while the ledger's own
quantity is rounded. Sub-paise per item, and it is the Inventory-control tie-out
CLAUDE.md makes load-bearing.

WHY THE GUARD IS THE RULE AND NOT A LIST OF THE SIX

A list of today's doors is a list somebody has to remember to add the seventh
to, and this defect is what "the dropdown only offers valid values, so new data
is compliant by construction" looked like for a different identifier. So the
door list is DERIVED from the AST: every Pydantic field whose name says it is a
quantity and whose annotation is numeric must be validated by its own class.

PER CLASS, deliberately — a module-level walk passes when only one of a
create/PATCH pair is guarded, which is exactly the shape the two service-catalogue
doors had.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

MODELS = pathlib.Path(__file__).resolve().parent.parent / "models"

#: A field name that says "this is a number of things".
_QUANTITY_NAMES = ("quantity", "_qty", "qty_")

#: The numeric annotations a quantity is ever declared as. A `bool` field such
#: as `quantity_is_provisional` contains "quantity" and is not one.
_NUMERIC = {"float", "int", "Decimal"}


def _is_numeric(node: ast.AST) -> bool:
    """`float`, `Optional[float]`, `float | None`, `Decimal` — not `bool`."""
    if isinstance(node, ast.Name):
        return node.id in _NUMERIC
    if isinstance(node, ast.Subscript):          # Optional[...] / Union[...]
        return _is_numeric(node.slice)
    if isinstance(node, ast.Tuple):
        return any(_is_numeric(e) for e in node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _is_numeric(node.left) or _is_numeric(node.right)
    if isinstance(node, ast.Constant) and node.value is None:
        return False
    return False


def _called_names(fn: ast.AST) -> set[str]:
    return {c.func.id for c in ast.walk(fn)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}


def _asks_the_rule(tree: ast.Module) -> set[str]:
    """Names that reach `quantity_violation` — it, and any module-level helper
    that calls it.

    ONE LEVEL OF INDIRECTION IS ALLOWED, because `models/invoices.py` already
    factors the check into `_validate_quantity` and BOTH line models delegate to
    it, which is the right shape. A scan that saw only the direct call would
    report those two as unguarded and push the next author into copying the
    check back into each validator to satisfy a test.
    """
    reach = {"quantity_violation"}
    for fn in tree.body:
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if "quantity_violation" in _called_names(fn):
                reach.add(fn.name)
    return reach


def _validated_fields(cls: ast.ClassDef, reach: set[str]) -> set[str]:
    """Fields this class validates with something that asks the rule."""
    out: set[str] = set()
    for fn in cls.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not (_called_names(fn) & reach):
            continue
        for dec in fn.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            name = dec.func.attr if isinstance(dec.func, ast.Attribute) else getattr(dec.func, "id", "")
            if name != "field_validator":
                continue
            for a in dec.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    out.add(a.value)
    return out


def _doors() -> list[tuple[str, str, str, bool]]:
    """(module, class, field, is_validated) for every quantity field."""
    found: list[tuple[str, str, str, bool]] = []
    for path in sorted(MODELS.rglob("*.py")):
        tree = ast.parse(path.read_text())
        reach = _asks_the_rule(tree)
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            validated = _validated_fields(cls, reach)
            for st in cls.body:
                if not (isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)):
                    continue
                name = st.target.id
                if not any(k in name for k in _QUANTITY_NAMES):
                    continue
                if not _is_numeric(st.annotation):
                    continue
                found.append((path.name, cls.name, name, name in validated))
    return found


def test_the_scan_still_finds_the_doors_it_is_about():
    """A scan that stops matching keeps passing while checking nothing."""
    doors = _doors()
    assert len(doors) >= 8, (
        f"found only {len(doors)} quantity fields across models/ — the scan is "
        "probably reading the wrong shape, not a shrunken product")
    names = {f"{c}.{f}" for _, c, f, _ in doors}
    for expected in ("StockAdjustmentIn.quantity",
                     "ServiceCatalogueIn.opening_qty_units",
                     "ServiceCatalogueUpdateIn.opening_qty_units"):
        assert expected in names, f"{expected} vanished from the scan"


def test_a_bool_that_mentions_quantity_is_not_a_quantity():
    """`PreInvoiceLineIn.quantity_is_provisional` is a flag. Reading it as a
    door would make this guard demand a decimal check on a boolean, and the
    obvious way to silence that is to narrow the NAME rule until it stops
    catching anything."""
    assert not any(f == "quantity_is_provisional" for _, _, f, _ in _doors())


@pytest.mark.parametrize("module,cls,field", [
    (m, c, f) for m, c, f, _ in _doors()
])
def test_every_quantity_door_asks_the_rule(module, cls, field):
    ok = {(m, c, f) for m, c, f, v in _doors() if v}
    assert (module, cls, field) in ok, (
        f"models/{module}:{cls}.{field} takes a quantity and never asks "
        "domain.quantity.quantity_violation. The column is NUMERIC(10,3): a "
        "fourth decimal is accepted here, rounded by Postgres, and the value "
        "computed from it no longer matches what was stored.\n\n"
        "Add:\n"
        "    @field_validator(\"" + field + "\")\n"
        "    @classmethod\n"
        "    def _quantity(cls, v):\n"
        "        problem = quantity_violation(v)\n"
        "        if problem:\n"
        "            raise ValueError(problem)\n"
        "        return v"
    )
