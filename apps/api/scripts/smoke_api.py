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
    SMOKE_BASE_URL=https://practicesync-ai.onrender.com \
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


@dataclass(frozen=True)
class Check:
    name: str
    path: str
    # Seconds. Deliberately generous — this is a tripwire for "something is
    # badly wrong", not a performance benchmark. A budget tight enough to flap
    # is a budget that gets ignored, and an ignored check is worse than none.
    budget_s: float


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
        Check("identity/permissions",  "/api/identity/permissions",                  8),
        Check("clients/obligations",   f"/api/compliance/obligations{q}",           15),
        Check("accounting/profit-loss", f"/api/accounting/profit-loss{period}",      20),
        Check("accounting/cash-flow",  f"/api/accounting/cash-flow{period}",        20),
        Check("accounting/trial-balance", f"/api/accounting/trial-balance{q}&as_of_date={end}", 20),
        Check("currencies/policy",     f"/api/currencies/policy{q}",                 8),
    ]


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
        return False, f"{c.name:28s} {elapsed:7.2f}s  HTTP {status}  (expected 2xx)"
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

    token = sign_in(supabase_url, anon, email, password)

    # Longer than the largest budget, so a slow endpoint is reported as slow
    # rather than as a transport error — the distinction the frontend's own
    # 45s abort blurred, turning every over-budget call into a retry.
    failures = []
    with httpx.Client(timeout=120) as client:
        print(f"smoke: {base}")
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
