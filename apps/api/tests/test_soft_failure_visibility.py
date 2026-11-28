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

    Plus a ratchet on the rest of the backend: the bare `except …: pass` blocks
    outside health.py (the budget below), and that number may only go down.
"""
from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path


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
#
# 171 -> 174: core.exceptions.postgres_message guards each of its three reads.
# It runs INSIDE an error path, unwrapping the message from an exception raised
# by code that was already failing, so a report about failing to read the report
# is absurd recursion — and an earlier version of exactly this helper DID raise,
# on an attribute whose getter threw. These three are the correct shape, and
# they are the reason the budget moved rather than the check being ignored.
#
# 174 -> 175: core.exceptions._sqlstate, added beside postgres_message and for
# exactly the same reason. It reads `code` off an exception object built by
# code that was already failing — supabase-py has kept it on the instance and
# in args[0] at different versions, so both are tried — while composing the
# message that explains the original failure. tests/test_document_failures_
# say_what_went_wrong.py::test_an_exception_whose_attributes_raise_is_still_
# reported pins that it survives an object whose getters throw, which is the
# thing the swallow exists for.
#
# 175 -> 124 (POST-A-021, 18-10-2026): forty-six silent handlers on the money and ledger paths now report through
# capture_soft_failure (a best-effort audit, timeline, delivery-log or settings read) or capture_posting_failure (a rollback that
# did not run); tests/test_a_swallowed_failure_on_a_money_path_is_reported_not_silent.py holds those files at zero.
#
# 124 -> 83 (POST-A-021, second slice, 16-11-2026): the engagement-letter router (22) and the lifecycle router (18) report every
# swallow through capture_soft_failure (the count stood at 123 when the slice began: one had gone in between);
# tests/test_a_swallowed_failure_beyond_the_money_paths_is_reported.py holds those files at zero.
#
# 83 -> 57 (POST-A-021, third slice, 16-11-2026): the search router (7), the tasks router (6) and the AI copilot's context (9)
# report through capture_soft_failure, and the memory pipeline's four per-row stamp parses name the errors they expect.
#
# 57 -> 30 (POST-A-021, fourth slice, 17-11-2026): the broad handlers in the documents, branding, DSC, engagement, practice,
# relationship, scheduler-status, task-extras, task-template, year-end-review, portal, knowledge and AI-insight modules report;
# the workflow engine's rule comparison and the request-token reset name what they expect.
#
# 30 -> 16 (POST-A-021, fifth slice, 18-11-2026): fourteen narrow `except ...: pass` handlers were triaged. A stored date or month that
# does not read is reported where a figure falls back on it (credit terms, collections, overdue status, late-filing history, the
# payslip and TDS return month); a check is asked instead of an exception caught where the absence is ordinary (an impossible date
# in a notice's text, a trigger's due date, a mock invoice number); sales_invoices' private copy of the credit-terms rule delegates
# to services/credit_terms; and an always-importable mock store is imported without a guard.
# tests/test_a_narrow_swallow_is_triaged.py holds those files at zero. Left: the compliance builder's nine (taken when its item
# closes) and seven that run inside an error path by design (core/exceptions 3, the AI gateway's error-body parses 2, the mail
# transport 1, the request-token reset 1).
#
# 16 -> 7 (POST-A-021, sixth slice, 28-11-2026): the compliance builder's nine (services/compliance_obligation_service.py 7,
# domain/compliance_record_service.py 2: the audit row and timeline line of a generated, reassigned, escalated or moved obligation, and
# the escalation's in-app notifications) report through capture_soft_failure; tests/test_the_compliance_builders_swallows_are_reported.py
# holds them. What is left is the seven that run inside an error path by design (core/exceptions 3, the AI gateway's error-body
# parses 2, the mail transport 1, the request-token reset 1).
MAX_SILENT_SWALLOWS_ELSEWHERE = 7

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
