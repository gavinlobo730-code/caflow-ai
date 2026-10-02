"""One id per request, the firm it was for, and nothing else about the person (ops-11).

WHY THIS EXISTS
    Logging was `logging.basicConfig(level=INFO)` and a gunicorn access line, so a CA saying "it failed at
    11:05" could be answered only by reading every line near 11:05 and guessing which was theirs. There was no
    id on a request, none in the log line of the traceback it produced, none in the response the browser got,
    and none on the Sentry event. This is the small piece that ties the four together:

      * `middleware/request_context.RequestContextMiddleware` accepts or generates the id, binds it here, puts it
        in the `X-Request-ID` response header and writes ONE JSON line per request;
      * every other log record made while the request is in flight carries it (`install_record_factory`), so the
        traceback of a 500 is found by the same id;
      * `main._failure_response` puts it in the body of a 5xx the catch-all answers;
      * Sentry events carry it as the `request_id` tag, and `firm_id` as a tag once the caller is known.

WHAT IS BOUND, AND WHAT MAY NEVER BE
    The id, and the FIRM id (an internal UUID, which `_capture` in core/observability already tags). Never a
    name, an email, a GSTIN, a PAN, a user id or anything typed by the caller: a log line is read by more
    people and for longer than a database row, and `send_default_pii` is off precisely so that a third party
    receives none of it. `bind_firm` accepts only an identifier-shaped value, so a value that is not one is
    dropped rather than written into a line a person will read.

THE FIRM IS BOUND BY WHOEVER LEARNS IT, THROUGH A MUTABLE HOLDER
    The middleware runs before authentication, so the firm is not known when the context is created. The
    authentication dependencies learn it and call `bind_firm`. A sync dependency runs on a worker thread whose
    contextvar context is a COPY, so setting a plain ContextVar there would never be seen by the middleware
    that writes the line afterwards. The ContextVar therefore holds a small mutable object, and the copy shares
    the object. That is the reason for `RequestContext`, and a test reads the firm back through a sync
    dependency so it cannot be "simplified" into a bare variable.

THE ID IS A CORRELATION HINT, NOT AN IDENTITY
    A caller may send its own `X-Request-ID` (support asks a CA to, and a proxy may add one), so the value is
    validated rather than trusted: 8 to 64 characters of letters, digits, dot, underscore and hyphen. Anything
    else — empty, too short, too long, a space, a newline, a quote — is REPLACED by a generated id, never
    rejected (a bad header must not fail a request) and never written anywhere, so a caller cannot put a line
    break, a JSON fragment or an escape sequence into the log. Two requests that send the same id share it;
    nothing here relies on uniqueness.
"""
from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar, Token
from typing import Optional

_logger = logging.getLogger("caflow.request_context")

REQUEST_ID_HEADER = "X-Request-ID"

#: Where the id lives on the ASGI scope. `_failure_response` reads it from `request.scope` because the
#: Starlette catch-all (`ServerErrorMiddleware`) runs OUTSIDE the middleware that sets the ContextVar, and the
#: scope dict is the one object every layer shares.
SCOPE_KEY = "caflow.request_id"

#: What the route is called in a log line when no route matched (a 404, a scanner's probe). The raw path is
#: never a substitute: it is the one part of a request that can carry a secret the template does not.
UNMATCHED_ROUTE = "<unmatched>"

#: Both patterns are applied with `.fullmatch`, NEVER `.match`: Python's `$` also matches just before a trailing
#: "\n", so `^…$` under `.match` accepts "abcdefgh\n" — a line break in a response header and in a log line, the
#: one thing this validation exists to keep out. The anchors stay in the text because the browser's copy of the
#: id shape (`lib/api/requestReference.ts`, where `$` has no such quirk) is pinned against this very string.
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$")
#: A firm id is a UUID in production and `firm-001` in the dev mode; a value shaped like neither is not logged.
_FIRM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: The logger the one-line-per-request record goes to. Named here so core/observability's `ignore_logger`
#: and the formatter below agree on it.
ACCESS_LOGGER = "caflow.access"


class RequestContext:
    """What is known about the request in flight. Mutable on purpose — see the module docstring."""

    __slots__ = ("request_id", "firm_id")

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.firm_id: Optional[str] = None


_current: ContextVar[Optional[RequestContext]] = ContextVar("caflow_request_context", default=None)


# ── the id ─────────────────────────────────────────────────────────────────────

def new_request_id() -> str:
    """16 hex characters: 64 bits is nowhere near a collision at this product's request rate, and short enough
    that a CA can read it down a telephone."""
    return uuid.uuid4().hex[:16]


def clean_request_id(raw: Optional[str]) -> Optional[str]:
    """The caller's id if it is safe to log and to echo in a header, else None."""
    if not isinstance(raw, str):
        return None
    return raw if _REQUEST_ID.fullmatch(raw) else None


def accept_or_generate(raw: Optional[str]) -> str:
    return clean_request_id(raw) or new_request_id()


# ── the context ────────────────────────────────────────────────────────────────

def begin(request_id: str) -> Token:
    return _current.set(RequestContext(request_id))


def end(token: Token) -> None:
    try:
        _current.reset(token)
    except (ValueError, RuntimeError):
        # Reset from another context (a task that outlived its request): clearing is what matters.
        _current.set(None)


def current() -> Optional[RequestContext]:
    return _current.get()


def current_request_id() -> Optional[str]:
    ctx = _current.get()
    return ctx.request_id if ctx else None


def current_firm_id() -> Optional[str]:
    ctx = _current.get()
    return ctx.firm_id if ctx else None


def tag_sentry(key: str, value: str) -> None:
    """Put a tag on this request's Sentry scope. Never raises, and turns nothing on: with no DSN the client
    is disabled and this writes to a scope nothing reads."""
    try:
        import sentry_sdk
        sentry_sdk.get_isolation_scope().set_tag(key, value)
    except Exception:                                        # noqa: BLE001 — reporting must not break a request
        _logger.debug("could not tag the Sentry scope with %s", key, exc_info=True)


def bind_firm(firm_id: object) -> None:
    """Record which firm this request is for. A no-op outside a request and for a value that is not an
    identifier. Called by the authentication dependencies once the caller is known."""
    ctx = _current.get()
    if ctx is None:
        return
    value = str(firm_id) if isinstance(firm_id, (str, uuid.UUID)) else None
    if value is None or not _FIRM_ID.fullmatch(value):
        return
    ctx.firm_id = value
    tag_sentry("firm_id", value)


def route_template(scope: dict) -> str:
    """The matched route as DECLARED (`/api/clients/{client_id}`), never the path as requested.

    FastAPI's route puts itself on the scope when it matches (`child_scope["route"]`), so this is only
    available after routing — which is when the line is written. A request nothing matched is
    `UNMATCHED_ROUTE`: a 404's path is whatever a stranger typed.
    """
    path = getattr(scope.get("route"), "path", None)
    return path if isinstance(path, str) and path else UNMATCHED_ROUTE


def request_id_of(scope: Optional[dict]) -> Optional[str]:
    """The id for a request, from the scope first (every layer shares it) and the ContextVar second."""
    if scope:
        value = scope.get(SCOPE_KEY)
        if isinstance(value, str):
            return value
    return current_request_id()


# ── log records ────────────────────────────────────────────────────────────────

def install_record_factory() -> None:
    """Stamp `request_id`, `firm_id` and a printable `request_context` suffix on EVERY log record.

    A record factory rather than a Filter on one handler: a filter attaches to a handler or a logger, and a
    record from a logger that propagates to a different handler (or from a test's capture handler) would miss
    it. The factory runs where the record is made, in the thread that logged, which is why the ContextVar's
    copy into the worker thread matters.
    """
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_caflow_request_context", False):
        return

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        ctx = _current.get()
        record.request_id = ctx.request_id if ctx else None
        record.firm_id = ctx.firm_id if ctx else None
        if ctx is None:
            record.request_context = ""
        elif ctx.firm_id:
            record.request_context = f" [request_id={ctx.request_id} firm_id={ctx.firm_id}]"
        else:
            record.request_context = f" [request_id={ctx.request_id}]"
        return record

    factory._caflow_request_context = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


class RequestContextFormatter(logging.Formatter):
    """The existing plain format, plus ` [request_id=… firm_id=…]` on a line written during a request.

    The suffix is skipped for the access line, which is JSON and already carries both. A record that was made
    before the factory was installed has no `request_context`; it formats as it always did.
    """

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "request_context"):
            record.request_context = ""
        text = super().format(record)
        if record.name == ACCESS_LOGGER or not record.request_context:
            return text
        # A traceback is the LAST thing in `text`; the suffix belongs on the first line, where a search for the
        # id finds the message, not after the stack.
        first, newline, rest = text.partition("\n")
        return f"{first}{record.request_context}{newline}{rest}"


def configure_logging(level: int = logging.INFO) -> None:
    """What main.py used to do with `logging.basicConfig(level=INFO)`, plus the request id on every line.

    The format string is basicConfig's own default (`%(levelname)s:%(name)s:%(message)s`), so no existing line
    changes shape: a log search that worked yesterday works today. Idempotent.
    """
    install_record_factory()
    root = logging.getLogger()
    already = list(root.handlers)
    logging.basicConfig(level=level)
    # Only the handler basicConfig itself just added: a handler somebody else put on the root (a test's
    # capture handler, a library's) keeps the formatter it was given.
    for handler in root.handlers:
        if handler not in already:
            handler.setFormatter(RequestContextFormatter("%(levelname)s:%(name)s:%(message)s"))
