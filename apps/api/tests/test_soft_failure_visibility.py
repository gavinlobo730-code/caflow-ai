"""
A fail-soft block must be quiet, not silent.

WHAT WAS WRONG
    routers/health.py wrapped every query in `except Exception: pass`. That
    fail-soft design is right — one broken dimension must not take down a whole
    client's health score — but it was also SILENT, and that is what let four
    phantom-column bugs live in the file indefinitely. PostgREST rejected those
    queries at parse time, on every call, for every firm, and the engine went on
    returning a confident number: ai_risk_signals scored a flat 100 for every
    client in the product, and two hard overrides could never fire.

    Nothing raised, nothing logged, nothing reached Sentry. The only trace was
    in the database's own logs, which is where they were eventually found —
    after the fact, by someone looking for something else.

WHAT IS ASSERTED
    That the reporting helper never raises (it runs inside paths that are
    fail-soft by design, so a failure to report must not become the failure),
    that it keeps posting and non-posting failures in separate Sentry groups,
    and that health.py no longer swallows anything without saying so.

    Plus a ratchet on the rest of the backend: 171 bare `except …: pass` blocks
    remain outside health.py, and that number may only go down.
"""
from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from core.observability import capture_posting_failure, capture_soft_failure  # noqa: E402


# ── The helper's contract ────────────────────────────────────────────────────

def test_capture_soft_failure_never_raises():
    """It is called from paths that already decided not to fail. If reporting
    could raise, it would turn a degraded read into a 500 — strictly worse than
    the silence it replaces."""
    capture_soft_failure(ValueError("boom"), operation="test.op",
                         firm_id="f1", client_id="c1")


def test_it_survives_context_that_cannot_be_stringified():
    class Hostile:
        def __str__(self): raise RuntimeError("nope")
        def __repr__(self): raise RuntimeError("nope")

    capture_soft_failure(ValueError("boom"), operation="test.op", weird=Hostile())


def test_it_survives_a_broken_sentry(monkeypatch):
    import core.observability as obs

    def explode(*_a, **_k):
        raise RuntimeError("sentry is down")

    monkeypatch.setattr(obs.sentry_sdk, "new_scope", explode)
    capture_soft_failure(ValueError("boom"), operation="test.op")


def test_it_logs_at_error_so_it_is_visible_without_sentry(caplog):
    """SENTRY_DSN is optional. If the only report were the Sentry event, a
    deployment without it would be exactly as blind as before."""
    with caplog.at_level(logging.ERROR, logger="caflow.observability"):
        capture_soft_failure(ValueError("boom"), operation="health.dim_x", client_id="c1")
    assert any(r.levelno >= logging.ERROR for r in caplog.records)
    assert any("health.dim_x" in r.getMessage() for r in caplog.records)


def test_posting_and_soft_failures_group_separately(monkeypatch):
    """A broken health dimension and a missing COGS journal need different
    responses, so they must not land in one Sentry issue."""
    seen: list[list[str]] = []

    class Scope:
        def set_tag(self, *_a): pass
        def set_extra(self, *_a): pass
        @property
        def fingerprint(self): return []
        @fingerprint.setter
        def fingerprint(self, v): seen.append(v)

    import contextlib
    import core.observability as obs
    monkeypatch.setattr(obs.sentry_sdk, "new_scope",
                        lambda: contextlib.nullcontext(Scope()))
    monkeypatch.setattr(obs.sentry_sdk, "capture_exception", lambda _e: None)

    capture_posting_failure(ValueError("x"), operation="post_cogs")
    capture_soft_failure(ValueError("x"), operation="post_cogs")

    assert seen == [["posting-failure", "post_cogs"], ["soft-failure", "post_cogs"]], (
        "same operation name must still produce two distinct fingerprints"
    )


# ── The health engine says something now ─────────────────────────────────────

def _silent_handlers(path: Path) -> list[int]:
    """Line numbers of `except …: pass` blocks — a swallow with no report."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.ExceptHandler)
            and len(n.body) == 1 and isinstance(n.body[0], ast.Pass)]


def test_the_health_engine_no_longer_swallows_anything_silently():
    silent = _silent_handlers(API_ROOT / "routers" / "health.py")
    assert not silent, (
        f"routers/health.py swallows without reporting at lines {silent}. "
        "Every query in that file feeds a number a CA is shown; a silent "
        "failure there is a confident wrong answer."
    )


def test_every_health_swallow_names_the_operation_it_lost():
    """A report with no operation name groups everything into one Sentry issue
    and tells you nothing about which dimension broke."""
    src = (API_ROOT / "routers" / "health.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "capture_soft_failure"]
    assert len(calls) >= 25, f"only {len(calls)} reports in health.py — wiring likely regressed"
    for c in calls:
        ops = [k.value for k in c.keywords
               if k.arg == "operation" and isinstance(k.value, ast.Constant)]
        assert ops, f"capture_soft_failure at line {c.lineno} has no literal operation"
        assert ops[0].value.startswith("health."), (
            f"line {c.lineno}: operation {ops[0].value!r} should be namespaced 'health.'"
        )


# ── Ratchet on the rest ──────────────────────────────────────────────────────

# Bare `except …: pass` blocks outside routers/health.py. This may only SHRINK.
# It is not a target to drive to zero mechanically — some swallows are correct
# and want no report — but a new one should be a deliberate act that shows up
# in a diff, not something that accretes.
MAX_SILENT_SWALLOWS_ELSEWHERE = 171

_SCAN_DIRS = ("routers", "services", "domain", "repositories", "jobs", "core")


def test_silent_swallows_elsewhere_do_not_grow():
    total = 0
    worst: list[tuple[int, str]] = []
    for d in _SCAN_DIRS:
        for path in sorted((API_ROOT / d).rglob("*.py")):
            if path.name == "health.py" and path.parent.name == "routers":
                continue
            n = len(_silent_handlers(path))
            total += n
            if n:
                worst.append((n, str(path.relative_to(API_ROOT))))
    worst.sort(reverse=True)
    assert total <= MAX_SILENT_SWALLOWS_ELSEWHERE, (
        f"{total} silent swallows, budget {MAX_SILENT_SWALLOWS_ELSEWHERE}. "
        f"Worst files: {worst[:5]}. Use capture_soft_failure(exc, operation=…) "
        "rather than `pass`, or raise the budget in the same commit and say why."
    )
