"""The daily run, triggered from OUTSIDE the process (ops-15).

WHY THIS EXISTS
    The 06:00 IST sweep fires from an in-process timer, so it only runs if the
    process is alive at 06:00. On Render's free tier it is asleep unless something
    wakes it, and the only thing that did was a GitHub Actions cron — best-effort by
    GitHub's own account — which, read from its run history for 21 to 30 September,
    started 3.5 to 5.5 hours late. Catch-up at boot (`run_catchup_if_stale`) makes
    every day COMPLETE; it cannot make it PUNCTUAL, and a restart at 06:00 during a
    deploy loses the timer for the day.

    This is the second trigger: a POST an external scheduler (a Render cron job,
    pg_cron with pg_net, any HTTP caller) makes at 06:00 IST. It wakes a sleeping
    instance by the act of calling it and runs whatever today's sweep still owes,
    through exactly the claims `run_daily_jobs` takes (jobs/claims.py), so a second
    trigger, the in-process timer and a second instance cannot double-run anything.

WHY A SHARED TOKEN AND NOT A USER'S JWT
    `POST /api/scheduler/run` is `rbac("team", "write")` and needs a person's JWT,
    which expires hourly: the wake workflow's own header records why that was
    abandoned (secret plumbing and a refresh flow in CI). This caller is a machine
    with no account. So it presents one shared secret, `SCHEDULER_TRIGGER_TOKEN`, in
    `X-Scheduler-Token` — a custom header and not `Authorization`, because the
    request-scoped Supabase client adopts any bearer token as a user's JWT.

THE FOUR WAYS IT REFUSES, none of which writes anything
    * token not configured          -> 503. NEVER an open door: an unset variable must
      not mean "no check", and 503 (not 401) says the deployment is the problem;
    * token configured but shorter than MIN_TOKEN_LENGTH -> 503 as well. A one-word
      secret is an open door with extra steps, so it is refused as misconfiguration;
    * no token or the wrong one     -> 401, compared with `hmac.compare_digest` on
      bytes (not `==`, which stops at the first differing character, and not on
      `str`, which raises for a non-ASCII value);
    * too many wrong ones from one address -> 429 with Retry-After. Only FAILURES are
      counted, so the real caller is never throttled by anything a stranger does.
    The token is never logged. `core/client_ip` resolves the address (the Nth entry
    from the right, not the first one the caller typed).

WHAT IT DOES NOT DO
    It schedules nothing: somebody has to create the external job (docs in the
    answer to the finding). It does not run before 06:00 IST (see
    `jobs/scheduler.run_pending_now`). It returns at once and the run continues on a
    thread — a sweep can take minutes and an external HTTP client should not hold a
    connection for them; `GET /api/scheduler/status` shows the outcome.
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from core.client_ip import client_ip
from core.rate_window import SlidingWindowLimiter
from models.common import api_response

router = APIRouter(prefix="/api/internal/scheduler", tags=["scheduler"])

_logger = logging.getLogger("caflow.scheduler_trigger")

TOKEN_ENV = "SCHEDULER_TRIGGER_TOKEN"
TOKEN_HEADER = "X-Scheduler-Token"
#: `openssl rand -hex 32` is 64 characters; anything under half of that is refused.
MIN_TOKEN_LENGTH = 32

#: Wrong or missing tokens per address per minute. Successes are not counted.
FAILED_PER_IP_MAX = 20
FAILED_WINDOW_SECONDS = 60
_failures = SlidingWindowLimiter(FAILED_PER_IP_MAX, FAILED_WINDOW_SECONDS)


def _configured_token() -> str:
    # The name is a literal HERE and not TOKEN_ENV: tests/test_render_manifest_matches_code
    # finds a variable by the literal in an os.environ.get call, and a read it cannot see is a
    # declaration it reports as dead.
    return os.environ.get("SCHEDULER_TRIGGER_TOKEN", "").strip()


def token_configured() -> bool:
    """Whether this deployment can accept the external trigger at all. A boolean and
    nothing about the value: `GET /api/scheduler/status` serves it, so a Partner can
    see that the human step was done without ever being shown the secret."""
    return len(_configured_token()) >= MIN_TOKEN_LENGTH


def _reset_failures() -> None:  # test seam
    _failures.reset()


def require_trigger_token(
    request: Request,
    x_scheduler_token: Optional[str] = Header(default=None),
) -> None:
    expected = _configured_token()
    if not expected:
        raise HTTPException(status_code=503, detail=(
            "The external scheduler trigger is not configured on this deployment."))
    if len(expected) < MIN_TOKEN_LENGTH:
        _logger.error("%s is set but shorter than %d characters; refusing the external trigger",
                      TOKEN_ENV, MIN_TOKEN_LENGTH)
        raise HTTPException(status_code=503, detail=(
            "The external scheduler trigger is misconfigured on this deployment."))
    provided = (x_scheduler_token or "").strip()
    if provided and hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        return
    ip = client_ip(request) or "unknown"
    if not _failures.hit(ip):
        raise HTTPException(status_code=429, detail="Too many requests.",
                            headers={"Retry-After": str(FAILED_WINDOW_SECONDS)})
    _logger.warning("scheduler trigger: %s token from %s refused",
                    "no" if not provided else "a wrong", ip)
    raise HTTPException(status_code=401, detail="Invalid scheduler token.")


@router.post("/run-pending")
def run_pending(_: None = Depends(require_trigger_token)):
    """Run today's still-pending daily jobs now. Idempotent: a finished job is skipped,
    one another instance is running is skipped, a failed one is retried. Answers at once
    with whether a run was started and how many (job, firm) pairs were pending."""
    from jobs.scheduler import run_pending_now
    from services import email_outbox_service
    result = run_pending_now(background=True)
    # Whether or not any job was pending, the practice's queued mail is drained on this call
    # (off this thread, beside the run): the trigger is also the backstop for the outbox where
    # the in-process minute tick is not running. The drain asks PRACTICE_MAIL_ENABLED again for
    # every message it takes, and claims rows so it cannot double-send beside another drainer.
    email_outbox_service.kick()
    return api_response(True, result)

