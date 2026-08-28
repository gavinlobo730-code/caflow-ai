"""Every keyset-paginated query must select the column it pages on.

WHAT WAS WRONG
    Eleven modules hold a copy of the same helper:

        def _paginate_all(make_query, key="id"):
            ...
            rows = q.order(key).limit(PAGE).execute().data or []
            if len(rows) < PAGE: break
            cursor = rows[-1][key]          # <- a hard index

    A caller whose .select() omits `key` works perfectly until the 1000th row
    and then raises KeyError. PostgREST is happy to ORDER BY a column it was
    not asked to return, so nothing complains earlier.

    The shape of that failure is the problem. It cannot happen on a small
    client, a fixture, or any test that hands back fewer rows than a page — it
    happens only on a client busy enough to need a second page, which is the
    client whose GST return, stock ledger or receivables ageing most needs to
    be right. It surfaces as a bare 500 on a screen a CA is trying to file from.

    Six call sites were in this state: five in reconciliation_service (stock
    ledger against sales and purchases, the running-cost walk, receivables and
    payables ageing) and one added to gst_return_service the same day this test
    was written, fetching GSTR-2A records for the Rule 36(4) cap.

WHY A SCANNER AND NOT SIX FIXES
    Nothing about `.select("a, b")` looks wrong, the helper is copied into
    eleven files, and the consequence is invisible until production. A reviewer
    cannot be expected to hold "does this select include id?" in their head for
    every new query. So the rule is checked mechanically, once, for all of them.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]

# The helpers that keyset-paginate and index rows[-1][key].
PAGINATORS = {"_paginate_all", "_fetch_all"}

SKIP_DIRS = {"tests", ".venv", "__pycache__", "migrations"}


def _sources():
    for f in sorted(API_ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        yield f


def _call_sites():
    """(file, line, key, selected_columns) for every paginated call whose
    select list is a readable string literal."""
    out = []
    for f in _sources():
        try:
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (OSError, SyntaxError):                     # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "id", "") in PAGINATORS):
                continue
            seg = ast.get_source_segment(src, node) or ""
            m = re.search(r'\.select\(\s*"([^"]*)"', seg)
            if not m:
                continue
            key = "id"
            for kw in node.keywords:
                if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                    key = kw.value.value
            cols = [c.strip() for c in m.group(1).split(",")]
            out.append((f.relative_to(API_ROOT), node.lineno, key, cols))
    return out


# ── the scan has to actually find things ─────────────────────────────────────

def test_the_scan_finds_the_paginated_call_sites():
    """Guard: an empty scan would make the rule below hold vacuously, which is
    exactly the state the codebase was already in."""
    sites = _call_sites()
    assert len(sites) >= 20, f"only found {len(sites)} paginated selects"
    files = {str(f) for f, _, _, _ in sites}
    assert any("gst_return_service" in x for x in files), files
    assert any("reconciliation_service" in x for x in files), files


def test_the_scan_can_tell_a_missing_key_from_a_present_one():
    """Guard on the checker itself, so a broken parser cannot pass everything."""
    src = (
        'def f(db):\n'
        '    a = _paginate_all(lambda: db.table("t").select("id, x").eq("f", 1))\n'
        '    b = _paginate_all(lambda: db.table("t").select("x, y").eq("f", 1))\n'
        '    c = _paginate_all(lambda: db.table("t").select("k, x"), key="k")\n'
    )
    tree = ast.parse(src)
    got = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") in PAGINATORS:
            seg = ast.get_source_segment(src, node) or ""
            m = re.search(r'\.select\(\s*"([^"]*)"', seg)
            key = "id"
            for kw in node.keywords:
                if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                    key = kw.value.value
            cols = [c.strip() for c in m.group(1).split(",")]
            got.append(key in cols or cols == ["*"])
    assert got == [True, False, True], got


# ── the rule ─────────────────────────────────────────────────────────────────

def test_every_paginated_select_includes_its_cursor_column():
    missing = [
        f"{f}:{line} pages on {key!r} but selects {cols}"
        for f, line, key, cols in _call_sites()
        if cols != ["*"] and key not in cols
    ]
    assert not missing, (
        "These queries page on a column they do not fetch. Each works until the "
        "1000th row and then raises KeyError on rows[-1][key] — a 500 that only "
        "ever appears for a client with a busy month:\n  "
        + "\n  ".join(missing))
