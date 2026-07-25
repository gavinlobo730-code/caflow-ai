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
    _logger.error(
        "posting failure in %s: %s | context=%s", operation, exc, context, exc_info=True
    )
    try:
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("posting_operation", operation)
            scope.fingerprint = ["posting-failure", operation]
            for key, value in context.items():
                if value is not None:
                    scope.set_tag(key, str(value))
                    scope.set_extra(key, value)
            sentry_sdk.capture_exception(exc)
    except Exception:
        # Sentry reporting itself must never break a fail-soft path.
        _logger.exception("capture_posting_failure: Sentry reporting itself failed")
