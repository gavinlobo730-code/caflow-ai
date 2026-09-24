"""The job that runs everything unattended reads every row, not the first thousand.

── THE DEFECT ───────────────────────────────────────────────────────────────
`jobs/scheduler._all_firm_ids()` is the enumeration the ENTIRE daily sweep
iterates over, and it read `firms` unpaged. PostgREST caps a response at ~1000
rows and reports nothing when it does — no error, no flag, no short-read signal
— so the 1001st firm's every daily job simply never runs: the compliance
calendar, recurring tasks, recurring invoices, recurring purchase bills, the
trusted-rule sweep, the reminders. Nothing anywhere says so.

**The FALLBACK was the read that would have truncated first**, which is the
part worth reading twice. When the `firms` read errors, the function falls back
to `tasks` — a row per TASK rather than per firm — so a single busy practice
fills the cap on its own and every firm whose tasks sort after it disappears
from the sweep. The safety net was the least safe read in the file.

`jobs/bank_trusted_rules_job._clients_with_trusted_rules` is the third: a firm
with 200 clients and a handful of rules each crosses the cap, and a truncated
read there drops whole clients from a sweep that POSTS JOURNALS with nobody
watching.

── WHY THIS IS ITS OWN GUARD ────────────────────────────────────────────────
`tests/test_paginated_selects_carry_their_key.py` holds the rule for a query
that is ALREADY paged — that its projection carries the cursor. This holds the
prior question for `jobs/` specifically: that a read there is paged at all.
The distinction matters because the consequence is different in kind. A screen
that truncates is at least a screen somebody is looking at; an unattended sweep
that truncates is work that silently never happened, discovered a month later
by a CA wondering why a client has no compliance calendar.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

JOBS = Path(__file__).resolve().parents[1] / "jobs"

#: Reads that do not need paging, each with the reason it is bounded. A `.limit()`
#: is self-evidently bounded and is recognised by shape rather than listed.
_BOUNDED_BY_DESIGN = {
    # The sweep writes one row per run; there is nothing to page.
    ("scheduler_runs", "insert"),
}


def _modules() -> list[Path]:
    return sorted(p for p in JOBS.glob("*.py") if p.name != "__init__.py")


def _code(p: Path) -> str:
    """Docstrings and comments blanked in place, so line numbers survive and
    this file's own prose cannot satisfy the scan."""
    s = p.read_text()
    out = list(s)
    for m in re.finditer(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', s):
        for i in range(m.start(), m.end()):
            if out[i] != "\n":
                out[i] = " "
    t = "".join(out)
    for m in re.finditer(r"(?m)^\s*#.*$", t):
        out[m.start():m.end()] = " " * (m.end() - m.start())
    return "".join(out)


_PAGERS = ("fetch_all", "_paginate_all", "_page_all")
_BOUNDED = (".limit(", ".single(", ".maybe_single(")


def _unbounded_reads(p: Path) -> list[tuple[int, str]]:
    """A `.table("x").select(...)` read in a function that neither pages nor
    bounds, reported per FUNCTION.

    ── TWO EARLIER SHAPES OF THIS PROBE WERE WRONG, BOTH IN THE SAFE-LOOKING
    DIRECTION (they reported reads that were already fixed), and both are worth
    recording because the next person will reach for them:

    1. **Forward to the next `.execute(`.** Wrong the moment a read is PAGED,
       because `fetch_all` calls `.execute()` inside itself — so the job's own
       chain has none, the scan ran on into unrelated code, and it reported the
       very reads it had just been satisfied by.
    2. **The enclosing Call node, via `ast.walk`.** `ast.walk` is breadth-first
       and not outside-in, so "the last ancestor containing this node" picks an
       arbitrary one. It missed `.limit(1)` on two bounded reads.

    Per FUNCTION is coarser than per statement and is the granularity that is
    actually correct here, because a bound is routinely applied through a
    rebound variable — `query = db.table(...)...` then `query.limit(1)` — which
    no single-expression scan can follow. ⚠️ The cost is stated rather than
    hidden: a function with TWO reads, one bounded and one not, passes. No
    function in `jobs/` has two today, and `test_the_probe_still_finds_the_reads_
    it_is_about` is what would notice the population changing.
    """
    tree = ast.parse(p.read_text())
    out: list[tuple[int, str]] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = ast.unparse(fn)
        if any(pg + "(" in body for pg in _PAGERS) or any(b in body for b in _BOUNDED):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "table"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and ".select(" in body):
                out.append((node.lineno, node.args[0].value))
    return sorted(set(out))


@pytest.mark.parametrize("mod", _modules(), ids=lambda p: p.name)
def test_no_job_reads_a_table_unbounded(mod: Path):
    found = _unbounded_reads(mod)
    assert not found, (
        f"{mod.name} reads a table with no .limit() and no pager: "
        + ", ".join(f"{t} (line {ln})" for ln, t in found)
        + ".\n  PostgREST caps the response at ~1000 rows and says nothing. In "
        "an unattended sweep that is work which silently never happened. Use "
        "core.db_paging.fetch_all, and put the cursor column in the projection."
    )


def test_the_probe_still_finds_the_reads_it_is_about():
    """A scan that matches nothing passes for ever. `jobs/` does still read
    tables — they are paged or bounded now, which is a different thing from
    the probe having gone blind."""
    total = 0
    for mod in _modules():
        body = _code(mod)
        total += len(re.findall(r'\.table\(\s*"[a-z_0-9]+"\s*\)', body))
    assert total >= 5, (
        f"only {total} table reads found across jobs/; the scan no longer "
        "reads module bodies, or the jobs moved")


def test_a_paged_read_in_a_job_carries_its_cursor():
    """`fetch_all` walks on `id` and reads the next cursor off the last row, so
    a projection without `id` reads one page and cannot advance — which works
    perfectly until the thousandth row, and then silently stops. Derived from
    the AST rather than matched as text, because the call spans lines."""
    for mod in _modules():
        tree = ast.parse(mod.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "fetch_all"):
                continue
            src = ast.unparse(node.args[0]) if node.args else ""
            sel = re.search(r'\.select\(\s*[\'"]([^\'"]*)[\'"]', src)
            assert sel, f"{mod.name}: a fetch_all whose query has no literal select"
            cols = {c.strip() for c in sel.group(1).split(",")}
            assert "id" in cols or "*" in cols, (
                f"{mod.name}: fetch_all pages on `id` and the projection is "
                f"{sorted(cols)} — the walk cannot read its next cursor, so it "
                "reads one page and stops at exactly 1000 rows")


def test_the_firm_enumeration_and_its_fallback_are_both_paged():
    """Named, because these two are the whole sweep's population and the
    fallback is the one that would have truncated first — a row per TASK."""
    body = _code(JOBS / "scheduler.py")
    for table in ("firms", "tasks"):
        m = re.search(rf'table\("{table}"\)', body)
        assert m, f"the {table} read has moved; point this guard at it"
        window = body[max(0, m.start() - 400):m.start()]
        assert "fetch_all" in window, (
            f"the {table} read in _all_firm_ids is no longer paged. That read "
            "is the population the entire daily sweep iterates over.")
