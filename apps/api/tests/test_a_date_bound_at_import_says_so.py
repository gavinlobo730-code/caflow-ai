"""A DATE BOUND AT IMPORT IS NOT THE CURRENT DAY, AND ITS NAME MUST SAY SO.

`apps/api` runs as a long-lived uvicorn process on Render, and
`.github/workflows/wake-before-scheduler.yml` pings `/health` across the
scheduler window precisely to stop the free tier putting it to sleep. So a
module-level

    today = ist_today()

is evaluated ONCE, when the module is imported, and is the DEPLOY date for as
long as that process lives. Seven modules carried exactly that binding.

**THE DEFECT WAS LIVE, IT WROTE ROWS, AND IT FAILED IN BOTH DIRECTIONS.**
`domain/ai_insight_service.generate_insights_for_client` computed

    days_left = (due - today).days

and then PERSISTED an insight through `ai_insights_repo.create` whose own
description states that figure, behind a `0 <= days_left <= 7` gate. Against a
date frozen N days ago every answer is N too large, so a record genuinely due
in three days reported "due in 13 day(s)" and fell OUTSIDE the gate — the
deadline the panel exists to raise was the one it dropped — while a record due
in a fortnight generated an "approaching" insight that was not. The same
function aged an open risk past seven days off the frozen date, so on a
deployment up for a week nothing ever crossed. `automation_engine`'s
"executions today" counted the boot day's executions for ever, and
`risk_engine` stamped an undated compliance risk with the deploy date.

**THE RULE THIS GUARD STATES IS ABOUT THE NAME, NOT ABOUT THE BINDING.** A
fixture list built at import legitimately wants the day it was built on —
`mock_data`, `notification_fixtures`, `document_intelligence_service` and the
seed script all do, and every one of their readers is called at module level
directly beneath the definition, which a test below proves. Banning the
binding would break them for no gain. What cannot survive is calling it
`today`, because the next author reads that as the current day and writes
exactly the four sites above. So:

  1. a module-level binding of a clock call may not be named for "now";
  2. no function in the LIVE tree — `domain/`, `services/`, `routers/`,
     `jobs/`, `repositories/` — may READ a module-level clock binding at all,
     whatever it is called, because a function is the thing that runs later.

Rule 2 is the one with teeth and rule 1 is what keeps rule 2 readable.
`mock_data.py` and `seed/` are outside rule 2 with their reason recorded and
ASSERTED rather than asserted-by-allowlist: a third test proves every reader in
them is invoked at module level, so the exemption cannot quietly widen.

`mock_data.py` carried the other half of the same clock defect as well —
`date.today()`, the SERVER's day, on a Singapore box, which is the previous day
throughout 00:00–05:30 IST. It asks `ist_today()` now.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

API = pathlib.Path(__file__).resolve().parent.parent

# The call names that read a clock. `now`/`today`/`utcnow` catch the bare
# `date.today()` / `datetime.utcnow()` forms as well as this repo's own
# `ist_today()` / `ist_now()`.
_CLOCK_CALLS = {"ist_today", "ist_now", "today", "now", "utcnow"}

# A name that claims to BE the current day. Compared case-insensitively and
# after stripping a leading underscore, so `TODAY`, `_today` and `Now` all fail.
_NAMES_THAT_CLAIM_NOW = {"today", "now", "date_today", "current_date", "current_day"}

# The directories a request actually runs through. `mock_data.py`, `seed/` and
# `tests/` are outside it — see the module docstring and
# `test_the_exempt_modules_read_their_constant_only_at_import`.
_LIVE_DIRS = ("domain", "services", "routers", "jobs", "repositories", "core", "models")

_EXEMPT_FROM_RULE_2 = {
    "mock_data.py": "the in-memory database: both readers run at import, proved below",
    "seed/seed_data.py": "a CLI script: imported and run in one breath, proved below",
}


def _py_files() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for d in _LIVE_DIRS:
        out.extend(sorted((API / d).rglob("*.py")))
    out.extend(sorted(API.glob("*.py")))
    return [p for p in out if "/tests/" not in str(p)]


def _module_level_clock_bindings(tree: ast.Module) -> dict[str, int]:
    """Names assigned a clock call at MODULE level (not inside any function)."""
    found: dict[str, int] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        fn = node.value.func
        name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
        if name not in _CLOCK_CALLS:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                found[target.id] = node.lineno
    return found


def _parsed() -> list[tuple[pathlib.Path, ast.Module]]:
    out = []
    for p in _py_files():
        try:
            out.append((p, ast.parse(p.read_text(encoding="utf-8"))))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - not expected
            continue
    return out


_PARSED = _parsed()


def test_the_probe_still_reads_a_real_tree():
    """Vacuity floor. Every assertion below is 'nothing found', which is what a
    probe that has stopped matching also reports."""
    assert len(_PARSED) > 400, f"only {len(_PARSED)} modules parsed — the walk is broken"
    with_bindings = [p for p, t in _PARSED if _module_level_clock_bindings(t)]
    assert with_bindings, "no module-level clock binding found at all — the detector is broken"


def test_no_module_level_clock_is_named_for_now():
    """Rule 1. `_FIXTURES_BUILT_ON` is fine; `today` is not."""
    offenders = []
    for path, tree in _PARSED:
        for name, line in _module_level_clock_bindings(tree).items():
            if name.lstrip("_").lower() in _NAMES_THAT_CLAIM_NOW:
                offenders.append(f"{path.relative_to(API)}:{line} — `{name}`")
    assert not offenders, (
        "A module-level clock binding is evaluated once, at import, so it is the "
        "deploy date for the life of the process. Name it for the moment it was "
        "taken (`_FIXTURES_BUILT_ON`, `_SEEDED_ON`), never for 'now':\n  "
        + "\n  ".join(offenders)
    )


def test_no_live_function_reads_a_date_bound_at_import():
    """Rule 2 — the one with teeth. A function is the thing that runs later."""
    offenders = []
    for path, tree in _PARSED:
        rel = str(path.relative_to(API))
        if rel in _EXEMPT_FROM_RULE_2:
            continue
        bound = _module_level_clock_bindings(tree)
        if not bound:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in bound:
                    offenders.append(f"{rel}:{node.lineno} — {fn.name}() reads `{node.id}`")
    assert not offenders, (
        "These functions read a date bound at import, so they read a day that "
        "stopped advancing when the process booted. Call ist_today()/ist_now() "
        "where the day is needed:\n  " + "\n  ".join(sorted(set(offenders)))
    )


@pytest.mark.parametrize("rel", sorted(_EXEMPT_FROM_RULE_2))
def test_the_exempt_modules_read_their_constant_only_at_import(rel: str):
    """The exemption is PROVED, not asserted. Every function in these two that
    reads the constant must itself be called at module level — which is what
    makes reading an import-time date sound there. A reader that stops being
    called at import fails here rather than silently joining the exemption."""
    tree = ast.parse((API / rel).read_text(encoding="utf-8"))
    bound = set(_module_level_clock_bindings(tree))
    assert bound, f"{rel} no longer binds a clock at module level — drop its exemption"

    readers = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(
            isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in bound
            for n in ast.walk(fn)
        ):
            readers.add(fn.name)
    assert readers, f"{rel} reads its constant in no function — drop its exemption"

    called_at_module_level = {
        n.func.id
        for stmt in tree.body
        for n in ast.walk(stmt)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    late = sorted(readers - called_at_module_level)
    assert not late, (
        f"{rel}: {late} read a date bound at import and are NOT called at module "
        "level, so they can run arbitrarily later. Either call ist_today() inside "
        "them or move the call site back to module level."
    )


def test_mock_data_asks_the_indian_clock():
    """The other half of the same defect. `date.today()` is the SERVER's day and
    this one runs in Singapore, so every fixture date was a day behind the
    firm's own throughout 00:00–05:30 IST."""
    src = (API / "mock_data.py").read_text(encoding="utf-8")
    assert "from core.ist_clock import ist_today" in src
    assert "_FIXTURES_BUILT_ON = ist_today()" in src
    # COMMENTS STRIPPED FIRST. The line this guard exists for is explained in a
    # comment directly above the fix, which names the very call it forbids —
    # this assertion failed on its own explanation the first time it was run.
    # Stripping is this repository's standing rule for every source scan.
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    assert "date.today()" not in code, "mock_data must not read the server's own day"


def test_the_two_live_writers_ask_the_clock_at_call_time():
    """Behaviour, not spelling: the two sites whose figure is WRITTEN must call
    the clock inside the function rather than close over a constant."""
    src = (API / "domain" / "ai_insight_service.py").read_text(encoding="utf-8")
    assert "days_left = (due - ist_today()).days" in src
    assert "(ist_today() - date.fromisoformat(" in src

    auto = (API / "domain" / "automation_engine.py").read_text(encoding="utf-8")
    assert "today_str = ist_today().isoformat()" in auto
