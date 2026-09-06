#!/usr/bin/env python3
"""
Hit the real API as a real user and fail on anything a page would fail on.

WHY THIS EXISTS
    Every other check in this repo is static. The column checker parses source
    and compares it to a schema replayed from migrations; the frontend ratchets
    parse the TypeScript AST. All of them passed, green, on a build where the
    client Overview page did not load at all.

    What actually found that bug was opening the app. The console showed a 400
    from PostgREST, five 403s from /api/identity/permissions, a 503 from
    /health, and a cash-flow request that took 57 seconds. Not one of those is
    expressible as a property of the source code — they are properties of a
    running system, and nothing in CI had ever run one.

    This is the missing check. It signs in, calls the endpoints the pages call,
    and fails on two things no static analysis can see:

        * a non-2xx response
        * a response that took longer than its budget

    The second matters as much as the first. The waterfall ratchet added earlier
    counts ROUND TRIPS, so a single request taking 57 seconds scores perfect on
    it. Wall-clock is the only measure that would have complained.

WHAT IT IS NOT
    Not a browser test. It makes no attempt to render pages, and it will not
    catch a PostgREST select naming a column that does not exist — the column
    checker already covers that exactly, against a real schema, without needing
    credentials. This covers the gap that one cannot: the FastAPI backend's
    availability and latency under real data volumes.

    Real data volumes are the point. The endpoint that took 57s was serving a
    client with 12,836 journal entries and 32,936 lines. No fixture reproduces
    that, which is why the budgets below are meant to be run against a real
    deployment rather than a seeded test database.

RUNNING IT
    SMOKE_BASE_URL=https://practicesync-api.onrender.com \
    SUPABASE_URL=https://<project>.supabase.co \
    SUPABASE_ANON_KEY=<anon key> \
    SMOKE_EMAIL=<user> SMOKE_PASSWORD=<password> \
    SMOKE_CLIENT_ID=<a client uuid with a real ledger> \
        python3 scripts/smoke_api.py

    Exits non-zero if any check fails, and prints one line per endpoint so a
    regression says WHICH endpoint and by how much. With no credentials it
    exits 0 and says it was skipped — it is meant to be wired to a scheduled
    job with secrets, not to block every PR on a live deployment.

CREDENTIALS
    Read from the environment only. Nothing is written to disk, nothing is
    logged, and the password is never echoed — including in the failure output.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

import httpx


# core/auth.py::mfa_guard raises this verbatim. Duplicated as a literal because
# this script runs standalone in CI with only httpx installed and cannot import
# the app; tests/test_smoke_api_script.py asserts the two stay identical, so
# rewording the message breaks a test rather than silently making this check red
# forever.
MFA_REQUIRED_DETAIL = "Multi-factor authentication required for this action."


@dataclass(frozen=True)
class Check:
    name: str
    path: str
    # Seconds. Deliberately generous — this is a tripwire for "something is
    # badly wrong", not a performance benchmark. A budget tight enough to flap
    # is a budget that gets ignored, and an ignored check is worse than none.
    budget_s: float
    # True when main.py mounts this router behind _MFA_GUARD (assignments,
    # identity, practice, billing). See run_check for why it matters.
    mfa_guarded: bool = False


def checks(client_id: str, start: str, end: str) -> list[Check]:
    """The endpoints a CA's first two screens depend on.

    Ordered roughly by how early a page needs them, so the output reads like a
    page load. Budgets reflect what these SHOULD cost, not what they currently
    do: /api/accounting/cash-flow was measured at 53-57s in production, so at 20
    it fails loudly rather than being quietly accepted."""
    q = f"?client_id={client_id}"
    period = f"{q}&start_date={start}&end_date={end}"
    return [
        Check("health",                "/health",                                    5),
        Check("identity/permissions",  "/api/identity/permissions",                  8,
              mfa_guarded=True),
        Check("clients/obligations",   f"/api/compliance/obligations{q}",           15),
        Check("accounting/profit-loss", f"/api/accounting/profit-loss{period}",      20),
        Check("accounting/cash-flow",  f"/api/accounting/cash-flow{period}",        20),
        Check("accounting/trial-balance", f"/api/accounting/trial-balance{q}&as_of_date={end}", 20),
        Check("currencies/policy",     f"/api/currencies/policy{q}",                 8),
    ]


def wake(client: httpx.Client, base: str, attempts: int = 3) -> tuple[bool, float, str]:
    """Get the instance out of bed BEFORE anything is timed.

    WHY THIS EXISTS
        Render's free tier spins the instance down after ~15 minutes without
        traffic, and waking it takes the better part of a minute. This workflow
        runs every 6 hours, so it almost always arrives at a sleeping instance
        and the FIRST request pays the whole cold start. That was landing on the
        `health` check's 5s budget and failing it — 56.55s on 2026-09-06 — which
        made the workflow permanently red for a reason that has nothing to do
        with whether the API works.

        A check that is always red is a check nobody reads. The next time the
        API is genuinely broken it will look exactly like this, and get scrolled
        past.

    SO THE WAKE IS UNTIMED, AND REPORTED ANYWAY
        The cold start is a real fact about the deployment and the point is not
        to hide it — it is printed on its own line, with its own duration, and
        excluded from the budgets. What the budgets then measure is what they
        were always meant to measure: how long a WARM instance takes to answer.

    A FAILURE HERE IS A REAL FAILURE
        If the instance never answers, that is the API being down, and the
        caller stops rather than running seven checks that will each time out
        and print the same thing seven times.
    """
    started = time.monotonic()
    last = ""
    for attempt in range(1, attempts + 1):
        try:
            r = client.get(f"{base}/health")
            if r.status_code < 400:
                return True, time.monotonic() - started, f"HTTP {r.status_code}"
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001 — a cold instance refuses connections
            last = type(e).__name__
        if attempt < attempts:
            time.sleep(2 * attempt)
    return False, time.monotonic() - started, last


def sign_in(supabase_url: str, anon_key: str, email: str, password: str) -> str:
    """A real user's access token, via the same password grant the login page
    uses. Fails loudly: a smoke check that silently ran unauthenticated would
    report 401s as if they were the system being broken."""
    r = httpx.post(
        f"{supabase_url}/auth/v1/token",
        params={"grant_type": "password"},
        headers={"apikey": anon_key, "Content-Type": "application/json"},
        json={"email": email, "password": password},
        timeout=30,
    )
    if r.status_code != 200:
        # Deliberately does not echo the body — it can contain the submitted
        # address, and on some failures the payload as well.
        raise SystemExit(f"smoke: sign-in failed with HTTP {r.status_code}")
    token = r.json().get("access_token")
    if not token:
        raise SystemExit("smoke: sign-in returned no access_token")
    return token


def failure_reason(r: httpx.Response) -> str:
    """The API's own explanation for a non-2xx, or "" when there isn't one.

    "HTTP 403 (expected 2xx)" names a symptom and leaves the cause to guesswork —
    /api/identity/permissions can 403 for at least four unrelated reasons (no user
    row, disabled account, suspended firm, MFA not satisfied) and the status code
    cannot tell them apart. The server already writes which one it is; not
    printing it was the difference between a diagnosis and an afternoon.

    Reads ONLY the two known string fields — this repo's {success, data, error}
    contract and FastAPI's HTTPException {"detail": ...} — never the whole body,
    which on a 200 would be a client's ledger. Truncated, and 2xx bodies are
    never touched at all.
    """
    try:
        body = r.json()
    except Exception:  # noqa: BLE001 — a non-JSON error page is not a reason to crash
        return ""
    if not isinstance(body, dict):
        return ""
    for field in ("error", "detail"):
        value = body.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return ""


def run_check(client: httpx.Client, base: str, c: Check, token: str) -> tuple[bool, str]:
    started = time.monotonic()
    try:
        r = client.get(f"{base}{c.path}", headers={"Authorization": f"Bearer {token}"})
        elapsed = time.monotonic() - started
        status: Optional[int] = r.status_code
    except httpx.HTTPError as e:
        elapsed = time.monotonic() - started
        return False, f"{c.name:28s} {elapsed:7.2f}s  TRANSPORT ERROR  {type(e).__name__}"

    over = elapsed > c.budget_s
    bad = status is None or not (200 <= status < 300)

    if bad:
        why = failure_reason(r)
        # An MFA-guarded route refusing an aal1 token is the POLICY WORKING, not
        # an outage. This script signs in with a password grant, which yields
        # aal1 by construction and can never satisfy an aal2 requirement — so
        # once REQUIRE_MFA is on for the smoke account's role, that 403 is
        # permanent and correct. Failing on it would leave a red check nobody
        # can ever make green, which is precisely the state /health was in for
        # weeks and the reason nobody could see real drift behind it.
        #
        # What it still proves: the route is mounted, the token was accepted,
        # and the guard ran. What it CANNOT prove is the authorised response —
        # so it is reported distinctly rather than as a plain pass, and only for
        # this exact status and reason. A 403 for any other reason (no user row,
        # disabled account, suspended firm) still fails, as does a 500.
        #
        # To cover the authorised path instead, point SMOKE_EMAIL at an account
        # whose role is not in MFA_REQUIRED_ROLES (default "Partner"); the
        # endpoint then answers 200 and is checked normally, with no code change.
        if c.mfa_guarded and status == 403 and why == MFA_REQUIRED_DETAIL:
            if over:
                return False, f"{c.name:28s} {elapsed:7.2f}s  OVER BUDGET of {c.budget_s:.0f}s"
            return True, (f"{c.name:28s} {elapsed:7.2f}s  ok (MFA-guarded: policy "
                          f"enforced; authorised response not covered)")
        return False, (f"{c.name:28s} {elapsed:7.2f}s  HTTP {status}  (expected 2xx)"
                       + (f"  — {why}" if why else ""))
    if over:
        return False, f"{c.name:28s} {elapsed:7.2f}s  OVER BUDGET of {c.budget_s:.0f}s"
    return True, f"{c.name:28s} {elapsed:7.2f}s  ok"


def main() -> int:
    base = os.environ.get("SMOKE_BASE_URL", "").rstrip("/")
    # Server spellings only. The NEXT_PUBLIC_* names are the frontend's, and
    # accepting them here would add a second name for one value in a script
    # whose whole job is to be unambiguous about what it talked to.
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    anon = os.environ.get("SUPABASE_ANON_KEY")
    email = os.environ.get("SMOKE_EMAIL")
    password = os.environ.get("SMOKE_PASSWORD")
    client_id = os.environ.get("SMOKE_CLIENT_ID")

    missing = [n for n, v in [
        ("SMOKE_BASE_URL", base), ("SUPABASE_URL", supabase_url),
        ("SUPABASE_ANON_KEY", anon), ("SMOKE_EMAIL", email),
        ("SMOKE_PASSWORD", password), ("SMOKE_CLIENT_ID", client_id),
    ] if not v]
    if missing:
        print(f"smoke: skipped — not configured ({', '.join(missing)})")
        return 0

    # A financial year's worth of data, which is what the dashboard asks for.
    start = os.environ.get("SMOKE_START_DATE", "2026-04-01")
    end = os.environ.get("SMOKE_END_DATE", "2027-03-31")

    # Longer than the largest budget, so a slow endpoint is reported as slow
    # rather than as a transport error — the distinction the frontend's own
    # 45s abort blurred, turning every over-budget call into a retry.
    failures = []
    with httpx.Client(timeout=120) as client:
        print(f"smoke: {base}")

        # Untimed, and always printed. See wake().
        awake, wake_s, detail = wake(client, base)
        print(f"  WAKE  {'instance ready':28s} {wake_s:7.2f}s  {detail}"
              f"{'  (cold start — not counted against any budget)' if wake_s > 5 else ''}")
        if not awake:
            print(f"\nsmoke: the API never answered /health ({detail}) — "
                  f"not running the remaining checks")
            return 1

        token = sign_in(supabase_url, anon, email, password)
        for c in checks(client_id, start, end):
            ok, line = run_check(client, base, c, token)
            print(("  PASS  " if ok else "  FAIL  ") + line)
            if not ok:
                failures.append(line)

    if failures:
        print(f"\nsmoke: {len(failures)} check(s) failed")
        return 1
    print("\nsmoke: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
