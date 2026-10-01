"""Deep readiness — does the database answer, and does it accept our key? (ops-05)

WHY THIS IS NOT /health
    `/health` answers 200 without touching the database after boot, and that is
    deliberate and pinned: Render's deploy health check gave a new instance a
    fixed window to answer, three cross-region round trips at import time blew
    through it on every deploy for weeks, and the slow half of startup now runs
    on a thread so `/health` can answer at once (main._lifespan). A `/health`
    that called Postgres would put that failure back — and would make Render
    PULL a healthy instance out of rotation on a database blip, which turns an
    outage of one dependency into an outage of the whole service.

    The price of keeping it cheap is that it cannot see a Postgres or PostgREST
    outage at all. An external monitor pointed at it says "all fine" while every
    screen fails. `/ready` is the other half: the question a MONITOR asks, never
    the question Render's `healthCheckPath` asks. `render.yaml` stays on
    `/health`, and `tests/test_ready_touches_the_database_and_health_does_not.py`
    asserts it.

WHAT IT PROBES, AND WHY ONE REQUEST CHECKS TWO THINGS
    One bounded `GET /rest/v1/firms?select=id&limit=1` with the SERVICE-ROLE key,
    which is the request that reaches network, PostgREST, Postgres and the key
    in one go. The answer then tells them apart, because what a person on call
    does next differs:

      * `config`   — SUPABASE_URL or the key is not set. Nothing was sent.
      * `database` — the host did not answer in time, refused, or PostgREST or
                     Postgres is failing (timeout, unreachable, 5xx, or the probe
                     table is absent or unreadable by the service role — the 403
                     that "57 tables never granted to service_role" produced).
      * `auth`     — the gateway answered 401: the service-role key was rotated or
                     mistyped. The database is fine and restarting it helps nobody.

    It reads `firms`, the tenant table, because it is the one every request
    resolves a caller against; a service role that cannot read it could not
    serve anything.

    It builds its OWN short-lived `httpx` client instead of borrowing
    `core.supabase_client._service_client()`: that client is shared, carries the
    library's default 120 s timeout, and changing either for the sake of a probe
    would change every other caller's behaviour. A fresh client also means a
    fresh connection, so a pool full of stale sockets cannot make a dead database
    look alive. HTTP/2 is left off (httpx's default) for the reason
    `_force_http1` records.

THE DEADLINE IS THE POINT
    A readiness probe that can hang is worse than none: the monitor times out
    instead of being told. httpx's timeouts are per PHASE, not total, so they are
    chosen to SUM to four seconds — connect 1.5 + write 0.5 + read 2.0 — which
    keeps the worst case under the five seconds the monitor is told to allow. DNS
    resolution sits inside the connect phase.

WHY THE ANSWER IS CACHED FOR FIVE SECONDS
    This route is unauthenticated (a monitor has no JWT) on a public repository,
    and it spends a database round trip. Without a cache, anybody who can reach
    the API can turn it into a steady query load on a free-tier database. The
    lock also stops a stampede: concurrent callers wait for the one probe that is
    in flight and share its answer. Five seconds is short enough that a recovered
    database reads as recovered almost at once, and the body says when an answer
    was reused.

WHAT IT NEVER SAYS
    No URL, no key, no exception text — only which of the three things failed and
    a fixed sentence. The endpoint is open to the internet.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import httpx

_logger = logging.getLogger("caflow.readiness")

#: The table the probe reads. The tenant table: every request resolves its
#: caller against it, so a service role that cannot read it serves nothing.
PROBE_TABLE = "firms"

#: Per-phase limits that SUM to 4.0 s. See "THE DEADLINE IS THE POINT".
CONNECT_SECONDS = 1.5
WRITE_SECONDS = 0.5
READ_SECONDS = 2.0
PROBE_DEADLINE_SECONDS = CONNECT_SECONDS + WRITE_SECONDS + READ_SECONDS

#: How long one answer is reused. See "WHY THE ANSWER IS CACHED".
CACHE_TTL_SECONDS = 5.0

# Which thing failed. A closed vocabulary: a monitor keys its alert text on it.
FAILED_CONFIG = "config"
FAILED_DATABASE = "database"
FAILED_AUTH = "auth"

#: One sentence per failure, fixed so nothing about the deployment leaks.
_SENTENCES = {
    FAILED_CONFIG: "The database connection is not configured on this server.",
    FAILED_DATABASE: "The database did not answer the readiness probe.",
    FAILED_AUTH: "The database answered but refused this server's service key.",
}


@dataclass(frozen=True)
class ReadinessResult:
    ready: bool
    failed: Optional[str]      # FAILED_* or None
    reason: Optional[str]      # short machine word: timeout, unreachable, http_503 ...
    latency_ms: int

    @property
    def sentence(self) -> Optional[str]:
        return _SENTENCES.get(self.failed) if self.failed else None


def _ms(started: float) -> int:
    return int(round((time.monotonic() - started) * 1000))


def probe(url: str, key: str) -> ReadinessResult:
    """One bounded request. Never raises: every failure is an answer."""
    started = time.monotonic()
    timeout = httpx.Timeout(
        connect=CONNECT_SECONDS, write=WRITE_SECONDS,
        read=READ_SECONDS, pool=WRITE_SECONDS,
    )
    endpoint = f"{url.rstrip('/')}/rest/v1/{PROBE_TABLE}"
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.get(
                endpoint,
                params={"select": "id", "limit": "1"},
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
    except httpx.TimeoutException:
        return ReadinessResult(False, FAILED_DATABASE, "timeout", _ms(started))
    except httpx.InvalidURL:
        return ReadinessResult(False, FAILED_CONFIG, "invalid_url", _ms(started))
    except httpx.TransportError:
        return ReadinessResult(False, FAILED_DATABASE, "unreachable", _ms(started))
    except Exception:                                        # noqa: BLE001
        # A probe that raises is a probe that cannot answer. Anything we did not
        # foresee is reported as the database failing, never as success.
        _logger.exception("readiness probe raised unexpectedly")
        return ReadinessResult(False, FAILED_DATABASE, "error", _ms(started))

    code = response.status_code
    if 200 <= code < 300:
        return ReadinessResult(True, None, None, _ms(started))
    if code == 401:
        return ReadinessResult(False, FAILED_AUTH, "http_401", _ms(started))
    # 403 (no GRANT for the service role), 404 (probe table absent), 5xx
    # (PostgREST or Postgres failing), and anything else unexpected.
    return ReadinessResult(False, FAILED_DATABASE, f"http_{code}", _ms(started))


def check_now(
    environ: Optional[dict] = None,
) -> ReadinessResult:
    """Read the connection settings and probe. No cache — `check` is the door."""
    env = os.environ if environ is None else environ
    url = (env.get("SUPABASE_URL") or "").strip()
    key = (env.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        return ReadinessResult(False, FAILED_CONFIG, "not_set", 0)
    return probe(url, key)


_lock = threading.Lock()
_cached: Optional[tuple[float, ReadinessResult]] = None


def reset_cache() -> None:
    """For tests, and for an operator who has just fixed something."""
    global _cached
    with _lock:
        _cached = None


def check(clock: Callable[[], float] = time.monotonic) -> tuple[ReadinessResult, bool]:
    """(result, reused). The lock is held across the probe on purpose."""
    global _cached
    with _lock:
        now = clock()
        if _cached is not None and now - _cached[0] < CACHE_TTL_SECONDS:
            return _cached[1], True
        result = check_now()
        _cached = (clock(), result)
    if not result.ready:
        _logger.warning("readiness failed: %s (%s) after %d ms",
                        result.failed, result.reason, result.latency_ms)
    return result, False


def readiness_payload(result: ReadinessResult, reused: bool) -> dict:
    """The `data` half of the standard envelope. Booleans, words and a number."""
    return {
        "status": "ready" if result.ready else "not_ready",
        "checked": ["database", "service_key"],
        "failed": result.failed,
        "reason": result.reason,
        "latency_ms": result.latency_ms,
        "deadline_seconds": PROBE_DEADLINE_SECONDS,
        "reused": reused,
    }
