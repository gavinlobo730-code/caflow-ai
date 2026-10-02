"""Response headers every API answer should carry, and the rule that keeps them from overwriting a route's own (security_privacy-05).

WHAT WAS MISSING
    Nothing in the API set a response header of its own beyond CORS and the request id: no
    `X-Content-Type-Options`, no `Strict-Transport-Security`, and a JSON answer carrying a client's books or a
    payslip had no `Cache-Control` at all, so a shared cache or a browser's back button was free to keep it.

WHAT IT ADDS
    * `X-Content-Type-Options: nosniff` on every response. A browser must take the declared type at its word,
      so a JSON body or an uploaded file served back is never reinterpreted as script or markup.
    * `Cache-Control: no-store` on a JSON response. Every JSON body from this API is a person's data behind a
      login, or an envelope about it, and none is meant to be reused from a cache.
    * `Strict-Transport-Security: max-age=2592000` (30 days) — see "HSTS" below.

THE RULE: A HEADER A ROUTE SET IS NEVER OVERWRITTEN
    Each header is added only when the response does not already carry it (`setdefault`, by case-insensitive
    name). The payslip door says `Cache-Control: private, no-store` on purpose, a download sets its own
    `Content-Disposition` and may set a cache policy, and a future route may set something stricter or
    something looser on purpose; this layer is the default and never the last word. Only JSON gets
    `Cache-Control` from here: a PDF, a spreadsheet or a zip is a file the caller asked to keep, and its route
    decides how.

HSTS — ONLY WHERE IT IS TRUE, AND NOT AS STRONG AS IT COULD BE
    Sent only when `APP_ENV` is literally "production" (`core.security_config.is_production`, the one reading of
    it) AND the request reached us over TLS as far as our own proxy says: the ASGI scheme is https, or the
    RIGHT-most `X-Forwarded-Proto` entry (the one the nearest proxy wrote, the same side `core.client_ip` reads)
    is https. The service sits behind Render's TLS terminator, so the scheme the app sees is `http`, and the
    forwarded protocol is what says otherwise. A local run (no APP_ENV, or `development`), the container's own
    health check over plain http, and a request nothing says was secure never get it.

    The value is 30 days and carries NO `includeSubDomains` and NO `preload`. A browser that has been told
    HSTS refuses plain http to the host for the whole period, and cannot be told otherwise short of waiting it
    out, so the first value is modest on purpose; raising it is one constant. `includeSubDomains` would bind
    every sibling hostname to https and nobody has shown that each is; `preload` is a permanent entry in the
    browsers' own lists and is not a thing to do without being sure.

PURE ASGI, NOT `BaseHTTPMiddleware`, AND WHERE IT SITS
    The same record as `body_limit.py` and `request_context.py` (CLAUDE.md): the other kind re-dispatches the
    request through a task group, buffers, and changes what a chunked body does. This one wraps `send` and
    nothing else; it reads no body and no header but the two above.

    Those two layers sit INSIDE `CORSMiddleware` because they GENERATE responses (a 413, a 500) and a response
    built outside CORS reaches the browser with no `Access-Control-Allow-Origin`. This one generates none: it
    only adds headers to what passes through. So it sits OUTSIDE CORS, which is what lets it cover the
    answers CORS itself produces (a preflight is answered by `CORSMiddleware`, never reaching a route) and the
    errors every inner layer produces, while leaving every CORS header exactly as CORS wrote it.

NOT COVERED
    An exception that escapes every layer is answered by Starlette's outermost handler, which is outside this
    one and carries none of these headers. `main._errors_with_cors` converts nearly every failure before it
    gets there, so what is left is a 500 that no cache keeps.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from core.security_config import is_production

#: 30 days. No `includeSubDomains`, no `preload`: see the module header.
HSTS_VALUE = "max-age=2592000"

_NOSNIFF = (b"x-content-type-options", b"nosniff")
_NO_STORE = (b"cache-control", b"no-store")
_HSTS = (b"strict-transport-security", HSTS_VALUE.encode("ascii"))


def _is_json(content_type: bytes | None) -> bool:
    """`application/json`, or a structured-syntax `+json` type, ignoring parameters (`; charset=utf-8`)."""
    if not content_type:
        return False
    media = content_type.split(b";", 1)[0].strip().lower()
    return media == b"application/json" or media.endswith(b"+json")


def hsts_applies(scope: dict) -> bool:
    """Whether this request may be answered with HSTS. See the module header: production, and secure."""
    if not is_production():
        return False
    if scope.get("scheme") in ("https", "wss"):
        return True
    for name, value in scope.get("headers", []):
        if name == b"x-forwarded-proto":
            last = value.decode("latin-1").split(",")[-1].strip().lower()
            return last == "https"
    return False


class SecurityHeadersMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive: Callable[[], Awaitable[dict]], send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        with_hsts = hsts_applies(scope)

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                content_type = next((v for k, v in headers if k.lower() == b"content-type"), None)
                if _NOSNIFF[0] not in present:
                    headers.append(_NOSNIFF)
                if with_hsts and _HSTS[0] not in present:
                    headers.append(_HSTS)
                if _is_json(content_type) and _NO_STORE[0] not in present:
                    headers.append(_NO_STORE)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
