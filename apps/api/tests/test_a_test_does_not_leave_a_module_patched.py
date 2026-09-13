"""A test may not rebind another module's `_db` — use `monkeypatch.setattr`.

FOUND BY A NEW TEST FAILING FOR SOMEBODY ELSE'S REASON.

`tests/test_r232_fixed_asset_depreciation.py` did

    fa_router._db = lambda: db

eleven times, as a plain assignment. Plain assignment is not undone when the
test ends, so from that module onwards EVERY test in the same process saw
`routers.fixed_assets._db` returning test_r232's own database double — a
different fake, with a different query builder, seeded with test_r232's rows.

`tests/test_fixed_asset_disposal.py` did the same eleven more times, and two
banking modules once each.

Nothing failed, for two reasons. The tests that came after happened to patch
`core.supabase_client.get_supabase` and reach the database a different way, or
they happened to run BEFORE the leak alphabetically. Both are luck. The first
test to want a real `create_asset` after `test_r232` — the Rule 43 one, FA-19
— died on `'_Q' object has no attribute 'like'`, which is another module's
fake failing inside a third module's production code. That is an hour to
diagnose and says nothing about the code under test.

WHY THIS ATTRIBUTE AND NOT A GENERAL RULE

`_db` is a router's whole database. Rebinding it redirects every read and
write in that module for the rest of the process, and it is the single
attribute this codebase's routers all expose under the same name — so the
rule is exact, mechanical, and has a one-line alternative that already works.
A general "never assign a module attribute" rule would have to judge every
save-and-restore pair, and a guard that needs judgement is a guard that gets
an exemption list.

`monkeypatch.setattr(mod, "_db", ...)` costs the same to write and pytest
undoes it at the end of the test, including when the test fails.
"""
from __future__ import annotations

import ast
import pathlib

TESTS = pathlib.Path(__file__).resolve().parent

#: The names a router's database accessor goes by. `_prod_db` is
#: routers/accounting.py's spelling of the same thing.
DB_ATTRS = {"_db", "_prod_db"}


def _offending_assignments(path: pathlib.Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:                       # not ours to police
        return []
    out: list[str] = []
    for node in ast.walk(tree):
        targets: list = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for t in targets:
            # `a.b = ...` and the tuple form `a.b, c.d = ...`, which is how
            # the two banking modules spelled their restore.
            flat = t.elts if isinstance(t, ast.Tuple) else [t]
            for el in flat:
                if (isinstance(el, ast.Attribute) and el.attr in DB_ATTRS
                        and isinstance(el.value, ast.Name)
                        # `self._db = …` inside a database double is an
                        # instance attribute of that double, not a module's.
                        and el.value.id not in ("self", "cls")):
                    out.append(f"line {node.lineno}: {el.value.id}.{el.attr} = …")
    return out


def test_no_test_rebinds_a_routers_database():
    bad: dict[str, list[str]] = {}
    for f in sorted(TESTS.glob("test_*.py")):
        if f.name == pathlib.Path(__file__).name:
            continue
        hits = _offending_assignments(f)
        if hits:
            bad[f.name] = hits
    assert not bad, (
        "These tests rebind a router's database with a plain assignment, which "
        "is never undone and leaks into every test that runs after them in the "
        "same process:\n"
        + "\n".join(f"  {name}\n    " + "\n    ".join(v) for name, v in bad.items())
        + "\n\nUse monkeypatch.setattr(<module>, \"_db\", lambda: db) instead — "
          "pytest undoes it at the end of the test, including on failure."
    )


def test_the_helpers_do_not_do_it_either():
    """`e2e_harness.py` and the other named helpers are imported by dozens of
    modules, so a leak there would reach further than any single test's."""
    bad = {}
    for f in sorted(TESTS.glob("*.py")):
        if f.name.startswith("test_"):
            continue
        hits = _offending_assignments(f)
        if hits:
            bad[f.name] = hits
    assert not bad, bad


def test_the_check_actually_sees_the_shape_it_is_looking_for():
    """A guard that matches nothing passes for ever. This is the exact source
    that leaked, parsed by the same function."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "sample.py"
        p.write_text("def test_x():\n"
                     "    fa_router._db = lambda: db\n"
                     "    rb.bank_posting_service, rb._db = real_svc, real_db\n")
        hits = _offending_assignments(p)
    assert len(hits) == 2, hits
    assert "fa_router._db" in hits[0]
    assert "rb._db" in hits[1]


def test_monkeypatch_setattr_is_not_flagged():
    """The alternative the failure message names must pass, or the guard is
    telling people to write something it rejects."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "sample.py"
        p.write_text('def test_x(monkeypatch):\n'
                     '    monkeypatch.setattr(fa_router, "_db", lambda: db)\n')
        assert _offending_assignments(p) == []
