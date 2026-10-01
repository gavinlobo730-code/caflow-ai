"""
Rate limits for every route that reaches an AI model.

WHAT WAS WRONG (ai-17, security_privacy-22)
    `check_rate_limit` was called from exactly one place — `/api/ai-copilot/chat`,
    which no screen calls. `/api/assistant` was in the table and never checked;
    `/api/copilot/*`, `extract-invoice`, `notices/extract`, the scanned-statement
    read and the statement analysis had no limiter at all, and the vision path can
    send up to 20 pages per upload. One busy or misbehaving firm could run up the
    provider bill or use up the quota for everybody.

HOW IT WORKS NOW
    * `ai_limit(bucket)` is a FastAPI dependency a route adds AFTER its `rbac()`
      dependency (FastAPI resolves dependencies in the order they are declared, so
      a caller who is refused for permission has not spent the firm's budget).
    * Each bucket is a sliding window, counted per FIRM and per USER. The firm
      limit keeps one firm from running up the bill; the user limit keeps one
      person from using the whole of their own firm's allowance.
    * A refusal is a 429 that says how long to wait and carries `Retry-After`.
    * `enforce` is the same check for a route that only SOMETIMES reaches a model
      (a statement upload is a model call only when it is a scan): it is called at
      the point the model is about to be used, not on every upload.

WHAT IT DOES NOT DO — and the finding asks for both
    * The windows live in THIS process. That is correct for one worker and wrong
      for several (each would allow the full limit, and a restart forgets them),
      which is why the module says so rather than implying otherwise. Render runs
      one worker today; when that changes, move `_hit`'s storage to shared memory
      and nothing else here changes.
    * There is no per-firm MONTHLY token or page budget and no usage screen. That
      needs a usage table (and so a migration) fed by every call, and a place for
      a Partner to read it; it is recorded as its own piece of work, not half-built
      here.
"""
from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from typing import Callable, Dict, Optional, Tuple

from fastapi import Depends, HTTPException, Request

from core.auth import get_current_user

_lock = threading.Lock()
# { (scope, id, bucket): [monotonic timestamps] }
_windows: Dict[Tuple[str, str, str], list] = defaultdict(list)

#: name -> (max requests per FIRM, window seconds). The per-USER limit is half of
#: this, never below three, so a firm of several people is not locked out by one.
#:
#: What each bucket is for, because the numbers differ on purpose:
#:   chat          a question to the assistant or copilot. One model call.
#:   intelligence  a generated summary. Cached for hours, but every cache MISS is a
#:                 model call over the whole practice's figures, and a scoped
#:                 caller has its own cache entry.
#:   extract       reading an invoice or a notice. Larger prompts, and a scanned
#:                 PDF is up to three page images.
#:   vision        reading a scanned statement: up to twenty page images a call.
#:   probe         the Partner's "is the AI answering?" check: one tiny call, and a
#:                 failing provider can spend the gateway's whole forty seconds, so
#:                 it is the smallest bucket (a user's share is never under three).
BUCKETS: Dict[str, Tuple[int, int]] = {
    "chat": (20, 60),
    "intelligence": (10, 60),
    "extract": (10, 60),
    "vision": (5, 60),
    "probe": (3, 60),
}

# The prefixes the original limiter matched on, kept so the one existing call
# site (`/api/ai-copilot/chat`) behaves as it did.
_LEGACY_PREFIXES = {
    "/api/ai-copilot": "chat",
    "/api/intelligence": "intelligence",
    "/api/assistant": "chat",
}


def user_limit(firm_limit: int) -> int:
    return max(3, firm_limit // 2)


def reset() -> None:
    """Forget every window. For tests: the windows are process-wide, so without
    this a test that spends a bucket starves the next one that uses it."""
    with _lock:
        _windows.clear()


def _hit(key: Tuple[str, str, str], max_req: int, window: int) -> Optional[int]:
    """Record a request against `key`. Returns None if allowed, else the number
    of seconds until the oldest request in the window ages out."""
    now = time.monotonic()
    cutoff = now - window
    with _lock:
        bucket = _windows[key]
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)
        if len(bucket) >= max_req:
            return max(1, math.ceil(bucket[0] + window - now))
        bucket.append(now)
        return None


def _refuse(max_req: int, window: int, who: str, retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=(f"Too many AI requests from {who}: the limit is {max_req} per "
                f"{window} seconds for this kind of request. Try again in "
                f"{retry_after} second{'s' if retry_after != 1 else ''}."),
        headers={"Retry-After": str(retry_after)},
    )


def enforce(bucket: str, firm_id: str, user_id: Optional[str] = None) -> None:
    """Raise 429 if this firm — or this user — has used up `bucket`."""
    if bucket not in BUCKETS:
        raise KeyError(f"unknown rate-limit bucket {bucket!r}")
    max_req, window = BUCKETS[bucket]
    retry = _hit(("firm", firm_id or "", bucket), max_req, window)
    if retry is not None:
        raise _refuse(max_req, window, "your firm", retry)
    if user_id:
        u_max = user_limit(max_req)
        retry = _hit(("user", user_id, bucket), u_max, window)
        if retry is not None:
            raise _refuse(u_max, window, "you", retry)


def ai_limit(bucket: str) -> Callable:
    """A dependency that limits a route to `bucket`. Add it AFTER rbac():

        current_user: dict = Depends(rbac("ai", "read")),
        _limit: None = Depends(ai_limit("chat")),
    """
    if bucket not in BUCKETS:
        raise KeyError(f"unknown rate-limit bucket {bucket!r}")

    def _dependency(current_user: dict = Depends(get_current_user)) -> None:
        enforce(bucket, current_user.get("firm_id") or "", current_user.get("id"))

    # The marker tests/test_every_route_that_reaches_a_model_is_rate_limited reads.
    _dependency._ai_limit_bucket = bucket  # type: ignore[attr-defined]
    return _dependency


def check_rate_limit(request: Request, firm_id: str) -> None:
    """The original entry point, by path prefix. Kept for `/api/ai-copilot/chat`;
    new routes use `ai_limit`."""
    path = request.url.path
    bucket = next((b for p, b in _LEGACY_PREFIXES.items() if path.startswith(p)), None)
    if bucket:
        enforce(bucket, firm_id)
