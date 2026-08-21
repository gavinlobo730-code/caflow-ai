"""
Structured Sentry capture for fail-soft financial-posting code (task #244).

Many domain/services functions are DELIBERATELY "never raises" — a failure to
post a downstream GL entry (COGS, inventory receipt, bank match, receipt
settlement, ...) must never block the primary document (a sale, a purchase, a
receipt) that triggered it. That fail-soft design is correct; the problem is
what happens next. Before this module, every one of those except-blocks did
nothing but `_logger.warning(...)` or `_logger.error(...)` — and Sentry's
default logging integration only turns ERROR+ log records into events, so a
`.warning()` catch (the majority of them) was invisible to Sentry even though
`sentry_sdk.init()` runs at boot. That is exactly how 5 sales invoices' COGS
journals went missing for weeks with nothing anywhere raising an alert (see
the task #244 audit) — the code did exactly what it was designed to do
(never block the sale) and exactly what it was NOT designed to do (tell
anyone).

capture_posting_failure() is the one call every such except-block should make
before returning/continuing. It always logs at ERROR (so it shows up in
Render's log stream regardless of Sentry configuration) AND reports to
Sentry with structured context — which document, which firm/client, which
operation — so a real posting failure surfaces as a traceable, actionable
alert instead of a line in a log nobody is tailing.
"""
from __future__ import annotations

import logging

import sentry_sdk

_logger = logging.getLogger("caflow.observability")


def _safe_str(value: object) -> str:
    """str(), for a value that may refuse to be one.

    Context comes from callers that are already failing, so it can hold a
    half-built ORM row or a mock whose __str__ raises. That must not become the
    thing that breaks the report — the whole point of this module is that the
    report survives.
    """
    try:
        return str(value)
    except Exception:
        return f"<unprintable {type(value).__name__}>"


def _capture(exc: Exception, *, kind: str, tag: str, operation: str, context: dict) -> None:
    """Shared body. `kind` and `tag` are the Sentry grouping keys and must stay
    stable — changing either splits an existing issue in two."""
    # Rendered BEFORE the log call, not inside its lazy %s formatting: logging
    # formats the record only when a handler accepts it, so an unprintable
    # value raised out of _logger.error() itself — outside every try below.
    safe = {k: _safe_str(v) for k, v in context.items() if v is not None}
    try:
        _logger.error(
            "%s failure in %s: %s | context=%s", kind, operation, exc, safe, exc_info=True
        )
    except Exception:
        _logger.error("%s failure in %s (context unprintable)", kind, operation, exc_info=True)
    try:
        with sentry_sdk.new_scope() as scope:
            scope.set_tag(tag, operation)
            scope.fingerprint = [f"{kind}-failure", operation]
            for key, value in safe.items():
                scope.set_tag(key, value)
                scope.set_extra(key, value)
            sentry_sdk.capture_exception(exc)
    except Exception:
        # Sentry reporting itself must never break a fail-soft path.
        _logger.exception("observability: Sentry reporting itself failed")


def capture_posting_failure(exc: Exception, *, operation: str, **context) -> None:
    """Report a swallowed exception from fail-soft financial-posting code.

    operation: short, stable, machine-readable name of what failed, e.g.
        "post_cogs_journal_entry" — becomes part of the Sentry event's
        fingerprint so repeated failures of the SAME kind group into one
        issue instead of each becoming a separate, hard-to-triage one.
    **context: structured key/values (firm_id, client_id, source_type,
        source_id, reference_no, ...) attached as Sentry tags so a failure
        is immediately traceable to the exact document it came from, not
        just a bare stack trace.

    Never raises — reporting a failure must never itself become a second
    failure in a path that was already fail-soft by design.
    """
    _capture(exc, kind="posting", tag="posting_operation",
             operation=operation, context=context)


def capture_soft_failure(exc: Exception, *, operation: str, **context) -> None:
    """Report a swallowed exception from fail-soft code that is NOT posting.

    Same contract as capture_posting_failure — always logs at ERROR, reports to
    Sentry with structured tags, never raises — but for the other half of the
    fail-soft surface: a read, a lookup, a score, a notification.

    WHY THIS EXISTS SEPARATELY
        The posting variant was written for a failure that loses MONEY. This is
        for a failure that loses TRUTH, which is quieter and lasted longer. Four
        phantom-column bugs in routers/health.py survived indefinitely because
        every query there sits in `except Exception: pass` — PostgREST rejected
        them at parse time, on every call, for every firm, and the engine went
        on returning a confident number. ai_risk_signals scored a flat 100 for
        every client in the product, and two hard overrides could never fire.

        Nothing was raised, nothing was logged, nothing reached Sentry. The
        only trace was in the database's own logs, which is where they were
        eventually found.

    It keeps its own `kind` so a broken health dimension does not group into the
    same Sentry issue as a missing COGS journal. They need different responses.
    """
    _capture(exc, kind="soft", tag="soft_operation",
             operation=operation, context=context)
