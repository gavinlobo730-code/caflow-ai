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
from typing import Callable, Optional

import sentry_sdk
from sentry_sdk.integrations.logging import ignore_logger

_logger = logging.getLogger("caflow.observability")

# THE ERROR LOG BELOW IS FOR RENDER'S LOG STREAM, NOT FOR SENTRY (ops-10).
# Sentry's default logging integration turns every ERROR record into an event, and
# `_capture` logs at ERROR with exc_info BEFORE it reports — so the record's event
# was the one that reached Sentry, carrying none of the tags and not the fingerprint,
# and the explicit capture that does carry them was then dropped as a duplicate of
# the same exception. Every alert rule built on `posting_operation` or
# `soft_operation` would have matched nothing, and every posting failure would have
# grouped by stack trace instead of by operation. Measured with the real SDK on
# 30-09-2026: one event, `tags: None`, `fingerprint: None`. The tests that existed
# replaced `sentry_sdk.capture_exception` and `new_scope` with fakes, which is why
# none of them could see it. Ignoring THIS logger leaves the line in the log stream
# and lets the tagged capture be the only event.
ignore_logger(_logger.name)

# The one-line-per-request record (middleware/request_context.py) is INFO below 500 and WARNING from it, and
# neither is an event; ignoring the logger also keeps a line per request out of every event's breadcrumbs.
from core.request_context import ACCESS_LOGGER  # noqa: E402
ignore_logger(ACCESS_LOGGER)


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


# ── starting it, and saying whether it started ──────────────────────────────────

def init_error_reporting(
    dsn: Optional[str],
    *,
    environment: str = "production",
    traces_sample_rate: float = 0.0,
    transport: Optional[Callable] = None,
) -> bool:
    """Start Sentry if there is a DSN; say whether it started. Called once, from main.py.

    It lives here rather than inline in main.py so a test can start it with a capturing
    transport and look at what would have left the process — the only way to test
    what a third party receives.

    THIS IS AN ERROR-REPORTING INSTALL, NOT AN APM ONE. Tracing is off by default: at
    1.0 every request became a transaction and the scheduler alone ticks once a minute
    — roughly 43k a month before a single user request, against a free-tier allowance
    of about 10k — and an exhausted quota makes Sentry DROP events, including the
    errors this is here for. Raise it deliberately, with a paid plan, if anyone wants
    latency data.

    WHAT LEAVES THE PROCESS IS CHOSEN HERE, and three options do it. `send_default_pii`
    is off, but it does not govern the other two, and the comment this replaced —
    "No request bodies, headers or user records" — was false of both, measured with the
    real SDK on 30-09-2026 against an endpoint that raised:

      * `max_request_body_size="never"`: the SDK attached the request's JSON body to
        the event regardless of the PII flag, so a 500 from a deductee or payroll
        endpoint sent `{"pan": "ABCDE1234F", "amount_paise": 12500000}` to a third
        party. Headers were already filtered (`Authorization` and `Cookie` arrive as
        `[Filtered]`); the body was not.
      * `include_local_variables=False`: every frame of the stack carries its local
        variables by default — the PAN, the amount, the customer's name in the failing
        function. The posting-failure TAGS chosen in `_capture` below are the only
        application data that should reach Sentry, and these two defaults were the
        rest of it.

    Returns False, and starts nothing, when `dsn` is empty.
    """
    if not dsn:
        return False
    options = dict(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
    )
    if transport is not None:
        options["transport"] = transport
    sentry_sdk.init(**options)
    return True


def error_reporting_enabled() -> bool:
    """True if a Sentry client with a DSN is live in this process.

    Asked of the SDK rather than of the environment: `SENTRY_DSN` being set says
    somebody typed a value, and `init` having run says it is being used. `/health`
    serves the answer so the state can be confirmed with one `curl` — the repo cannot
    see Render's dashboard, which is where `SENTRY_DSN` is set (`sync: false`).
    """
    try:
        client = sentry_sdk.get_client()
        # `is_active()` alone is True for ANY client `init` built, including one built with no DSN —
        # which drops every event while reporting itself active — so the DSN and the transport it
        # opens are asked too.
        return bool(client.is_active() and client.dsn and client.transport is not None)
    except Exception:
        return False


def boot_notice(dsn: Optional[str], app_env: Optional[str]) -> tuple[int, str]:
    """(log level, sentence) for the boot log — pure, so the wording is tested.

    Nothing said whether error reporting was on, so an unset DSN in production was
    silent: a swallowed financial-posting failure would reach Render's log stream and
    nobody's phone. That is the one configuration where the sentence must be a
    WARNING. In development an unset DSN is normal and stays an INFO.
    """
    if dsn:
        return logging.INFO, "Error reporting: Sentry is ON."
    if (app_env or "production") == "production":
        return logging.WARNING, (
            "Error reporting: Sentry is OFF because SENTRY_DSN is not set. Swallowed "
            "financial-posting failures reach this log stream only — nobody is alerted."
        )
    return logging.INFO, f"Error reporting: Sentry is off (SENTRY_DSN is not set; APP_ENV={app_env})."
