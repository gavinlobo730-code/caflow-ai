"""Per-address limits on the routes a stranger can reach (ops-30).

WHAT WAS WRONG
    The only limiters in the API were `middleware/rate_limit` (the AI routes, keyed on a signed-in firm
    and user), a private window inside `routers/demo_request.py`, a failure counter in front of the
    scheduler trigger and an unsigned-request counter behind each signed webhook. Everything else that
    needs no login had NO limit at all: the three engagement-letter signing routes (a view, a signature
    and a decline, each a round trip to Postgres in another country), the employee activation route (a
    bearer token turned into a real Supabase session), and the three accept-invite routes. The signing
    token is 256 bits, so GUESSING one is not the risk. The risk is capacity: the API is one worker, and
    one caller in a loop spends it for everybody, signed-in staff included.

WHAT THIS DOES
    `public_limit(bucket)` is a FastAPI dependency a route (or a whole router) declares. It keys on the
    caller's address as `core.client_ip.client_ip` resolves it (the Nth entry from the RIGHT of
    X-Forwarded-For, never the first one the caller typed; nothing here reads that header) and refuses
    the request past the bucket's budget with a 429, `Retry-After`, and the house envelope
    `{success: false, data: null, error: <sentence>}` (the handler is `too_many_requests_handler`,
    registered in main.py, so the refusal travels back out through CORSMiddleware and the browser can
    read it; an app without that handler still answers a plain 429 with the header, because the
    exception IS an `HTTPException`).

    It is declared BEFORE any authentication dependency on the routes that have one (the accept-invite
    routes), so a flood of bad tokens or expired sessions is refused before it costs a JWT check.

WHO IT DOES NOT TOUCH
    A signed-in user's own requests. Nothing here is on a route that needs a staff, portal or employee
    session, with four exceptions that are the calls a person makes BEFORE they have an account: the
    three accept-invite routes (a login plus a one-time invite token) and firm creation (a login, once
    per person). Every other authenticated route is untouched, and
    `tests/test_every_public_route_is_rate_limited.py` derives which routes are in scope from the route
    table, so a fifth cannot appear unlimited.

THE NUMBERS, AND WHY NO REAL CA IS REFUSED
    The unit is requests per address, because an office is one address. Each is chosen so a whole practice
    behind one NAT acting at once stays inside it, and so a script is stopped within a second:

        esign   120 / 60 s   a prospect's page makes one view and one signature; two a minute is a
                             very busy human. 120 is two a SECOND for a minute, a hundred times what a
                             household needs and far below a loop.
        invite  120 / 60 s   an employer who emails every employee an activation link and watches them
                             click it from one office: two requests each (activation, accept), so sixty
                             people inside the same minute fit.
        form    120 / 60 s   the marketing site's demo form reads the options once and posts once. The
                             demo POST ALSO keeps its own three-per-fifteen-minutes cap inside the handler;
                             this is the capacity valve in front of the requests that cap never sees (a
                             honeypot hit or a bad address returns before it counts).
        signup  60 / 1 h     creating a firm. A person does it once; a training class of thirty from one
                             network is inside it.

    A mis-keyed address is the other way this could hurt, and the budgets are the answer to it: if
    `TRUSTED_PROXY_HOPS` were too small, every caller would key on the proxy's address and share one
    window, and 120 a minute across the WHOLE public surface is still far above what it carries (a few
    signatures a day). That is the reason the figures are generous and not tight.

WHAT IT CANNOT DO — and the documents say the same
    The windows live in THIS process, like every limiter here: right for the one worker the service runs
    today, wrong for several (each would allow the full budget) and forgotten on a restart. There is no
    shared store and none is built. It does not stop a flood from many addresses; that is what the edge
    rules in `docs/operations/edge-protection.md` are for, and they are NOT APPLIED until a person does it
    in the Cloudflare account. And the body of a POST is read before a dependency runs (FastAPI parses it
    first), so a caller sending large bodies costs that read; `middleware/body_limit.py` is the bound on it.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Dict, Tuple

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from core.client_ip import client_ip
from core.rate_window import SlidingWindowLimiter
from models.common import api_response

_logger = logging.getLogger("caflow.public_rate_limit")

#: bucket -> (requests per address, window in seconds). See the module header for what each is for.
BUCKETS: Dict[str, Tuple[int, int]] = {
    "esign": (120, 60),
    "invite": (120, 60),
    "form": (120, 60),
    "signup": (60, 3600),
}

_limiters: Dict[str, SlidingWindowLimiter] = {
    name: SlidingWindowLimiter(max_events, window) for name, (max_events, window) in BUCKETS.items()
}

_refused_lock = threading.Lock()
_refused_total = 0


class TooManyRequests(HTTPException):
    """A 429 that carries how long to wait. An `HTTPException` on purpose: the handler in main.py shapes it
    into the envelope, and an app that never registered that handler still sends a correct 429."""

    def __init__(self, retry_after: int, bucket: str) -> None:
        super().__init__(
            status_code=429,
            detail=(f"Too many requests from this network just now. Please wait {retry_after} "
                    f"second{'s' if retry_after != 1 else ''} and try again."),
            headers={"Retry-After": str(retry_after)},
        )
        self.retry_after = retry_after
        self.bucket = bucket


async def too_many_requests_handler(request: Request, exc: TooManyRequests) -> JSONResponse:
    """The refusal in `{success, data, error}`, with `Retry-After`. Registered for `TooManyRequests` in main.py."""
    return JSONResponse(
        status_code=429,
        content=api_response(False, None, exc.detail),
        headers=dict(exc.headers or {}),
    )


def refused_total() -> int:
    """How many requests this process has refused. For a test and for a person reading a log."""
    return _refused_total


def reset() -> None:
    """Forget every window and the counter. For tests: the windows are process-wide, so without this a test
    that spends a bucket starves the next one that uses it."""
    global _refused_total
    for limiter in _limiters.values():
        limiter.reset()
    with _refused_lock:
        _refused_total = 0


def check(bucket: str, request: Request) -> None:
    """Count one request from this caller's address against `bucket`; raise `TooManyRequests` if it is over."""
    limiter = _limiters.get(bucket)
    if limiter is None:
        # A programming error and never a free pass: an unknown bucket must not mean "unlimited".
        raise KeyError(f"unknown public rate-limit bucket {bucket!r}")
    wait = limiter.hit_or_wait((client_ip(request) or "unknown")[:64])
    if wait is None:
        return
    global _refused_total
    with _refused_lock:
        _refused_total += 1
        count = _refused_total
    # First ten, then every hundredth: a flood is one line, not a million. The bucket only: no path (the
    # signing token is a path segment) and no address.
    if count <= 10 or count % 100 == 0:
        _logger.warning("public rate limit: refused #%d in bucket %s (retry after %ds)", count, bucket, wait)
    raise TooManyRequests(wait, bucket)


def public_limit(bucket: str) -> Callable:
    """A dependency that limits a route to `bucket`, per caller address:

        @router.post("/{token}/sign", dependencies=[Depends(public_limit("esign"))])

    Declared as the route's (or the router's) `dependencies`, FastAPI resolves it before the endpoint's own
    parameters, so on a route with a login dependency the limit is asked first.
    """
    if bucket not in BUCKETS:
        raise KeyError(f"unknown public rate-limit bucket {bucket!r}")

    async def _dependency(request: Request) -> None:
        check(bucket, request)

    # The marker tests/test_every_public_route_is_rate_limited reads off the route's dependency tree.
    _dependency._public_limit_bucket = bucket  # type: ignore[attr-defined]
    return _dependency
