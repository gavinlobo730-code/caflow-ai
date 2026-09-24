"""`fetch_all`'s first argument is a CALLABLE, and two call sites were not.

    def fetch_all(make_query, key="id", *, label="", stats=None)

`make_query` is called once per page — its docstring says so, and it has to be,
because a PostgREST builder is stateful and reusing one accumulates each page's
`.gt(key, cursor)` on top of the last. Handing it a BUILDER instead raises
`TypeError: '_Query' object is not callable` on page one, and handing it three
positional arguments raises before the body runs at all.

WHY A GUARD RATHER THAN TWO FIXES

Both live sites failed the same way and neither was visible from its own tests,
for two DIFFERENT reasons — which is what makes this a class rather than a pair:

  * `services/reorder_service._catalogue` passed the builder. The whole reorder
    report has therefore never run against a database: `routers/inventory.
    reorder_report` catches the TypeError and answers "Unable to load the
    reorder report". The mock suite could not see it, because that router's
    `_USE_MOCK` branch passes `db=None` and `assess` short-circuits to an empty
    answer BEFORE reaching the fetch.

  * `services/hub_service._sum_paise` passed three positional arguments. Its
    three tiles are computed inside `_safely`, which swallows a tile's
    exception by design, so the sales, purchases and TDS figures came back
    `None` and the hub rendered "—" against each of them.

So one was hidden by a broad `except` in a router and the other by a deliberate
per-tile one. A call site whose failure is swallowed is exactly the site a
runtime test does not reach, and the shape is checkable without running
anything — which is what this does.

IT IS THE RULE, NOT A SPELLING OF IT. The check is on the ARGUMENTS at every
call site rather than on a list of modules known to be correct, so a call
written next year in a module nobody thought of is covered on the day it is
written. It deliberately does NOT try to prove the callable returns a fresh
builder — that is a semantic property an AST cannot see — and the two defects
it does catch are the two that actually occurred.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

API = pathlib.Path(__file__).resolve().parent.parent

#: A first argument that can be called: a bound name (`one_page`, a lambda
#: assigned earlier), a lambda written inline, or an attribute (`self._page`).
_CALLABLE_NODES = (ast.Name, ast.Lambda, ast.Attribute)


def _modules():
    for p in sorted(API.rglob("*.py")):
        rel = p.relative_to(API)
        if rel.parts[0] in ("tests", "migrations", ".venv", "venv"):
            continue
        yield p, rel


def _calls(path: pathlib.Path):
    """Every `fetch_all(...)` call in the file, with its line number."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:                                  # pragma: no cover
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "fetch_all":
            yield node


ALL_CALLS = [(rel, c) for p, rel in _modules() for c in _calls(p)]


def test_the_guard_actually_found_the_call_sites():
    """Vacuity floor. `fetch_all` is the codebase's one pager and is read from
    dozens of services; a guard that finds a handful has stopped parsing."""
    assert len(ALL_CALLS) >= 40, (
        f"only {len(ALL_CALLS)} fetch_all call sites found — the AST walk is "
        "probably not resolving the module tree any more."
    )


def test_every_fetch_all_is_handed_something_callable():
    offenders = []
    for rel, call in ALL_CALLS:
        if not call.args:
            offenders.append(f"{rel}:{call.lineno} — no positional argument")
            continue
        first = call.args[0]
        if isinstance(first, ast.Call):
            offenders.append(
                f"{rel}:{call.lineno} — the first argument is a BUILDER "
                "expression. fetch_all calls it once per page, so it must be a "
                "function returning a fresh builder: `def one_page(): return "
                "db.table(...)...` then `fetch_all(one_page)`.")
        elif not isinstance(first, _CALLABLE_NODES):
            offenders.append(
                f"{rel}:{call.lineno} — the first argument is a "
                f"{type(first).__name__}, which cannot be called.")
    assert not offenders, "fetch_all is handed something it cannot call:\n  " \
        + "\n  ".join(offenders)


def test_no_fetch_all_passes_more_than_two_positional_arguments():
    """`label` and `stats` are keyword-only. A third positional argument is a
    TypeError raised before the body runs — which is how `hub_service` came to
    have three permanently dead money tiles."""
    offenders = [
        f"{rel}:{call.lineno} — {len(call.args)} positional arguments "
        "(fetch_all takes make_query and key; label and stats are keyword-only)"
        for rel, call in ALL_CALLS if len(call.args) > 2
    ]
    assert not offenders, "\n  ".join(offenders)


def test_a_paged_projection_still_carries_its_cursor():
    """The sibling rule, restated where the callable now hides it.

    `tests/test_paginated_selects_carry_their_key.py` states this for the
    codebase; it is asserted here for the two modules this change touched,
    because moving a projection inside a nested function is exactly the edit
    that could drop `id` from the select list without anything noticing until
    the thousandth row.
    """
    for mod in ("services/hub_service.py", "services/reorder_service.py"):
        src = (API / mod).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "select"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                continue
            cols = node.args[0].value
            if "count" in ast.dump(node):      # a COUNT does not page
                continue
            names = {c.strip() for c in cols.split(",")}
            assert "id" in names, (
                f"{mod}:{node.lineno} selects {cols!r} with no `id` — that is "
                "the keyset cursor fetch_all pages on.")
