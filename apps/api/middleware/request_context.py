"""An id on every request, in the response, in the log and on the Sentry event; one JSON line each (ops-11).

WHAT IT DOES, IN ORDER
    1. Takes the caller's `X-Request-ID` if it is safe to log, else makes one (core/request_context).
    2. Binds it for the rest of the request, tags it on the Sentry scope, and leaves it on the ASGI scope for
       the catch-all that runs outside this layer.
    3. Puts `X-Request-ID` on every response that starts — a 200, a 404, a refusal, a 500 — replacing any the
       app set itself, so the header and the log line cannot name different requests.
    4. When the response is finished (or the app raised), writes ONE line on `caflow.access` whose message is
       JSON: `{"event":"request","request_id","firm_id"?,"method","route","status","duration_ms"}` (behind the
       log format's own `LEVEL:caflow.access:` prefix, which is not JSON).

THE LINE NEVER CARRIES THE PATH AS REQUESTED
    `route` is the template the router matched (`/api/clients/{client_id}`), or `<unmatched>`. A raw path can
    hold a secret — the engagement-signing token is a path segment — and a query string can hold more, so
    neither is logged. This is also why the Dockerfile no longer passes `--access-logfile`: gunicorn's line is
    the raw request line, once per request, and this one replaces it.

NO PII, EVER
    method, route template, status, duration, the id, and the firm's internal UUID once authentication has
    learnt it. No IP address, no user agent, no user id, no header, no query string, no body.

PURE ASGI, NOT `BaseHTTPMiddleware`
    Same reasoning as `BodySizeLimitMiddleware` and the same record in CLAUDE.md: the latter re-dispatches the
    request through a task group, buffers, and changes what a chunked body does. This only wraps `send`.

WHERE IT SITS
    INSIDE `CORSMiddleware` — so a response it adds the header to still gets the CORS headers, and so a 413 from
    `BodySizeLimitMiddleware` (which is INSIDE this) carries an id and a line — and OUTSIDE the body limit and
    `_errors_with_cors`, so the 500 that middleware converts travels back out through here.

A HEALTH PROBE MUST NOT FLOOD THE LOG
    Render's health check, the container's own HEALTHCHECK, the wake workflow and any uptime monitor call
    `/health` and `/ready` every few seconds, which would make them nearly every line. A SUCCESSFUL call to
    either is not logged (it still gets the id header); one that fails (the 503 an operator is looking for) is.

NEVER ERROR LEVEL
    Sentry's logging integration turns every ERROR record into an event, so a 500 line at ERROR would add a
    second, untagged event beside the traceback the catch-all already reports. The line is INFO below 500 and
    WARNING from 500, and `ignore_logger(ACCESS_LOGGER)` in core/observability keeps it out of breadcrumbs.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Awaitable, Callable, Iterable

from core.request_context import (
    ACCESS_LOGGER,
    REQUEST_ID_HEADER,
    SCOPE_KEY,
    accept_or_generate,
    begin,
    current,
    end,
    route_template,
    tag_sentry,
)

_logger = logging.getLogger(ACCESS_LOGGER)

#: Route templates whose SUCCESSFUL calls are not logged (see the module docstring).
QUIET_ROUTES = frozenset({"/health", "/ready"})

_HEADER_NAME = REQUEST_ID_HEADER.lower().encode("ascii")
#: `.fullmatch`, not `.match`: `$` also matches before a trailing "\n" (see core/request_context._REQUEST_ID).
_METHOD = re.compile(r"^[A-Z]{1,12}$")


def _incoming_request_id(scope) -> str | None:
    """The FIRST `X-Request-ID` header, decoded as latin-1 (what HTTP headers are) and left for the validator."""
    for name, value in scope.get("headers", []):
        if name == _HEADER_NAME:
            try:
                return value.decode("latin-1")
            except Exception:                                # noqa: BLE001
                return None
    return None


def access_line(*, request_id: str, firm_id: str | None, method: str, route: str,
                status: int | None, duration_ms: float) -> str:
    """The JSON line, pure so a test pins its keys. `firm_id` is omitted until authentication has learnt it —
    an absent key and a null one would read the same and mean different things (unauthenticated, or a caller
    this layer was never told about)."""
    body: dict = {
        "event": "request",
        "request_id": request_id,
        "method": method if _METHOD.fullmatch(method or "") else "OTHER",
        "route": route,
        "status": status,
        "duration_ms": duration_ms,
    }
    if firm_id:
        body["firm_id"] = firm_id
    return json.dumps(body, separators=(",", ":"))


class RequestContextMiddleware:
    def __init__(self, app, quiet_routes: Iterable[str] = QUIET_ROUTES) -> None:
        self.app = app
        self.quiet_routes = frozenset(quiet_routes)

    async def __call__(self, scope, receive: Callable[[], Awaitable[dict]], send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = accept_or_generate(_incoming_request_id(scope))
        scope[SCOPE_KEY] = request_id
        token = begin(request_id)
        tag_sentry("request_id", request_id)

        started = time.perf_counter()
        status: int | None = None
        raised = False

        async def send_with_id(message: dict) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != _HEADER_NAME]
                headers.append((_HEADER_NAME, request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            raised = True
            raise
        finally:
            try:
                self._log(scope, request_id, status if status is not None else (500 if raised else None), started)
            except Exception:                                # noqa: BLE001 — a log line must never fail a request
                pass
            end(token)

    def _log(self, scope, request_id: str, status: int | None, started: float) -> None:
        route = route_template(scope)
        if status is not None and status < 400 and route in self.quiet_routes:
            return
        ctx = current()
        line = access_line(
            request_id=request_id,
            firm_id=ctx.firm_id if ctx else None,
            method=scope.get("method", ""),
            route=route,
            status=status,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        _logger.log(logging.WARNING if (status or 0) >= 500 else logging.INFO, line)
