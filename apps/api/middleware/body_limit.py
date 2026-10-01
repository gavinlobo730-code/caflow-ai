"""A request-body limit in front of the app (SECURITY-PRIVACY-20).

WHY IT IS NOT JUST THE PER-ROUTE CAP
    `core/uploads.read_limited` bounds what a route READS into memory, but by the
    time a route runs, Starlette has already parsed the multipart body and spooled
    it to a temporary file. A 2 GB POST therefore costs 2 GB of disk and the time
    to receive it before any route gets to say no. This refuses the request from
    its `Content-Length` header before the parser is started, and counts the bytes
    of one that declares none (a chunked body) so it cannot simply omit the header.

WHAT THE LIMIT IS
    `MAX_REQUEST_BODY_BYTES` — 32 MB. The largest file any route accepts is 10 MB
    (statements, invoices, attachments, documents), multipart framing adds a few
    hundred bytes, and the biggest JSON bodies are bulk imports parsed in the
    browser. It is deliberately roomy: the job here is to stop a stranger, and the
    per-route caps are what enforce the real numbers.

WHERE IT SITS, AND WHY THAT MATTERS
    INSIDE `CORSMiddleware` (see the ordering note in main.py). The API is on a
    different origin from the web app, so a 413 sent from outside CORS carries no
    Access-Control-Allow-Origin header and the browser shows an opaque "Failed to
    fetch" instead of "that file is too large". main.py's own comment records the
    same lesson for unhandled exceptions.

WHAT IT CANNOT DO
    Stop the bytes of a request whose headers already said they were small and
    lied — that is what the byte counter is for — or of a caller who never
    finishes sending. Render's proxy owns timeouts and its own ceiling above this.
"""
from __future__ import annotations

import json
from typing import Awaitable, Callable

from fastapi import HTTPException

MAX_REQUEST_BODY_BYTES = 32 * 1024 * 1024

_MESSAGE = "That request is too large (the limit is {mb} MB)."


class BodySizeLimitMiddleware:
    """Pure ASGI, not `BaseHTTPMiddleware`: it has to refuse BEFORE the body is
    touched, and the latter buffers and re-dispatches the request."""

    def __init__(self, app, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive: Callable[[], Awaitable[dict]], send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = None
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
                break
        if declared is not None and declared > self.max_bytes:
            await self._refuse(send)
            return

        seen = 0

        async def counted_receive() -> dict:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    # RAISE, and stop reading. Answering from here instead (send a
                    # 413, then report a disconnect) was tried and is worse: the app
                    # then fails with ClientDisconnect, which the catch-all in main.py
                    # logs with a traceback at ERROR — one Sentry event per refused
                    # request, for traffic that is abusive by construction. Raised
                    # inside a route's own body read, this reaches FastAPI, which
                    # answers 4xx and logs nothing. Through the BaseHTTPMiddleware
                    # layers it arrives wrapped in an ExceptionGroup, so FastAPI
                    # says 400 "There was an error parsing the body" rather than
                    # 413 — accepted: what matters for a chunked body is that the
                    # bytes stop being consumed, and the Content-Length check above
                    # gives every ordinary client the readable 413.
                    raise HTTPException(
                        status_code=413,
                        detail=_MESSAGE.format(mb=self.max_bytes // (1024 * 1024)))
            return message

        await self.app(scope, counted_receive, send)

    async def _refuse(self, send) -> None:
        body = json.dumps({
            "success": False, "data": None,
            "error": _MESSAGE.format(mb=self.max_bytes // (1024 * 1024)),
        }).encode()
        await send({
            "type": "http.response.start", "status": 413,
            "headers": [(b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        # The caller is mid-upload; do not wait for the rest of it.
                        (b"connection", b"close")],
        })
        await send({"type": "http.response.body", "body": body})
