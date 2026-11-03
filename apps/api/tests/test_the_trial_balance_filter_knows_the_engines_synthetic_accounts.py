"""The trial balance's search treats the engine's synthetic accounts as accounts, and a computed line as not one (POST-A-136, 2-11-2026).

WHAT WAS WRONG
    `apps/web/lib/accounting/trialBalanceFilter.ts` took every row whose id starts `__` for "not an account": drawn only when nothing is
    filtered, never matched by a search, never counted, never offered as a type. That is right for a line the server COMPUTES (the
    brought-forward surplus on a period trial balance; the retained-earnings line on the Balance Sheet). It is wrong for the two accounts the
    cash-basis projection registers when a chart has no advance control account, "Advance from Customers" and "Advance to Vendors": their ids
    start `__` too, but they are named, typed accounts whose balances are inside the server's totals. So on a cash-basis trial balance a search
    for "advance" answered "No account matches" and "Showing 0 of N accounts" over a table that had an Advance from Customers row in it;
    choosing the type Liability silently left the advance liability out of the rows (and a type only an advance account has was not offered at
    all); and no filter could ever bring the row back.

WHY THIS TEST IS HERE
    The browser now holds the two ids in `SYNTHETIC_ACCOUNT_IDS`. A list of the engine's ids kept in the browser is a copy, and a copy is how
    a third synthetic account added to the projector would be filtered out of the screen again without anyone being told. This package owns
    the vocabulary, so the guard is written on this side (the Schedule III caption lesson: a guard in `apps/web` would assert the browser
    against a copy of itself and pass whenever both drifted together).
"""
from __future__ import annotations

import ast
import pathlib
import re

from domain.reporting import builders, projector

REPO = pathlib.Path(__file__).resolve().parents[3]
FILTER = REPO / "apps" / "web" / "lib" / "accounting" / "trialBalanceFilter.ts"
PROJECTOR = pathlib.Path(projector.__file__)


def _browser_list() -> list[str]:
    source = FILTER.read_text(encoding="utf-8")
    body = re.search(r"export const SYNTHETIC_ACCOUNT_IDS[^=]*=\s*\[(.*?)\]", re.sub(r"//[^\n]*", "", source), re.S)
    assert body, "SYNTHETIC_ACCOUNT_IDS is not in the filter module any more: this guard cannot check what it cannot read"
    return re.findall(r'"([^"]+)"', body.group(1))


def _engines_synthetic_ids() -> set[str]:
    """Every id the projector registers through `_ensure_synthetic`, read from its module-level tuples (id, name, type)."""
    tuples = {name: value[0] for name, value in vars(projector).items()
              if isinstance(value, tuple) and len(value) == 3 and all(isinstance(v, str) for v in value) and value[0].startswith("__")}
    assert tuples, "the projector holds no synthetic account tuple any more: the scan has stopped matching"
    return set(tuples.values())


def test_the_browsers_list_is_the_ids_the_projector_registers():
    assert sorted(_browser_list()) == sorted(_engines_synthetic_ids()), (
        "the trial balance filter's SYNTHETIC_ACCOUNT_IDS and the projector's synthetic accounts differ: an account the cash-basis report "
        "carries would be hidden from a search, or a computed line would be searchable. Update the TypeScript list.")
    assert len(_browser_list()) >= 2, "the two advance accounts are the floor"


def test_every_synthetic_account_the_projector_registers_comes_from_one_of_those_tuples():
    """A call that passed a literal id would register an account this list does not know. Every call spreads a module-level tuple."""
    tree = ast.parse(PROJECTOR.read_text(encoding="utf-8"))
    tuple_names = {n for n, v in vars(projector).items() if isinstance(v, tuple) and len(v) == 3 and isinstance(v[0], str) and v[0].startswith("__")}
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_ensure_synthetic"]
    assert len(calls) >= 4, "the scan found too few registrations to mean anything"
    for call in calls:
        ok = (len(call.args) == 1 and isinstance(call.args[0], ast.Starred) and isinstance(call.args[0].value, ast.Name)
              and call.args[0].value.id in tuple_names)
        assert ok, f"projector.py line {call.lineno} registers a synthetic account that is not one of {sorted(tuple_names)}"


def _string_constants(path: pathlib.Path) -> set[str]:
    """Every string that is, whole, a constant in the code of `path`: a comment is not in the syntax tree, and a docstring is one constant
    holding a whole paragraph, so an id that is only MENTIONED in either is not found."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_a_line_the_builders_compute_is_not_on_the_browsers_list():
    """The computed lines that reach this filter (the period trial balance's brought-forward surplus, and the Balance Sheet's retained
    earnings) stay not-an-account: drawn only when nothing is filtered (the trial balance) or under every filter (a statement). The cash-flow
    statement's `__net_profit__`, `__noncash__` and `__wc__` rows never reach the filter and are not in question."""
    computed = {builders.SURPLUS_BROUGHT_FORWARD_ID, "__retained__"}
    assert computed.isdisjoint(_browser_list()), sorted(computed & set(_browser_list()))
    # each of them really is a constant the builders emit (in code, not in a comment or a docstring), so the pair above is not stale
    emitted = _string_constants(pathlib.Path(builders.__file__))
    for line_id in computed:
        assert line_id in emitted, f"{line_id} is no longer emitted by the builders: update this list"


def test_the_emitted_check_does_not_find_an_id_that_is_only_mentioned(tmp_path):
    """The check above reads the syntax tree: an id in a comment or inside a docstring is not a constant of its own."""
    f = tmp_path / "b.py"
    f.write_text('"""Docs mention "__ghost__" and __ghost__."""\n# "__ghost__" in a comment\nx = {"account_id": "__real__"}\n', encoding="utf-8")
    found = _string_constants(f)
    assert "__real__" in found and "__ghost__" not in found
