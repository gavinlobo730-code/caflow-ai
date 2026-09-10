"""PAY-11 — a finished payroll endpoint has a way in, or says why not.

WHAT WAS WRONG
    Seven payroll capabilities were built, mounted, tested and unreachable. The
    leaver's settlement — which computes gratuity, leave encashment and notice
    pay, withholds under §192, posts to the general ledger and closes the
    employee — had no screen at all. Nor did 24Q Annexure II, the year-end
    deliverable TRACES turns into Form 16.

    docs/audits/2026-09-01-payroll-can-it-run-a-year.md answers its own question
    "yes for the monthly cycle, the leaver and the statutory returns", and the
    leaver and the year-end could not be reached from anywhere in the product.

WHY THIS GUARD STATES THE RULE RATHER THAN A LIST
    The defect is not "these seven". It is that nothing noticed. An endpoint can
    be written, reviewed, tested and merged without one line of the product
    calling it, and every test in this suite passes — because every test in this
    suite calls it directly.

    So the rule is: EVERY endpoint on /api/payroll is called from apps/web, or
    is registered below with a reason. Adding an endpoint and no screen now
    fails here, and the failure names the endpoint.

HOW THE MATCH WORKS
    The path's static chunks, in order, with anything permitted between them —
    so `/api/payroll/employees/{id}/settlement` matches the api client's
    `/api/payroll/employees/${employeeId}/settlement`. Matching only the last
    segment would be far too loose: "settlement" and "loans" both occur in
    banking and accounting screens that have nothing to do with payroll, and a
    guard that passes on those would be worse than no guard.
"""
from __future__ import annotations

import pathlib
import re

import pytest

import routers.payroll as pay


WEB = pathlib.Path(__file__).resolve().parents[3] / "apps" / "web"

# Endpoints with deliberately no way in, each with the reason. An entry here is
# a claim somebody made on purpose — not a way to quiet the test.
UNREACHED: dict[tuple[str, str], str] = {
    ("POST", "/api/payroll/ecr-filings/{filing_id}/retract"):
        "Retracting a recorded ECR filing un-does a statement about the EPFO "
        "portal, not about this database — the return is still filed there. "
        "The screen offers recording and not retraction deliberately: a CA who "
        "recorded the wrong month fixes it by recording the right one, and an "
        "un-record button invites the queue to be cleared rather than filed. "
        "If it is ever surfaced it belongs beside the filing it retracts, with "
        "the same 'this transmits nothing' wording.",
}


def _sources() -> str:
    """Every .ts/.tsx in the product, minus its own tests.

    Tests are excluded so a test that merely NAMES an endpoint cannot make it
    look reachable — which is the exact shape of the mistake this file guards
    against, one level up.
    """
    out = []
    for folder in ("app", "lib", "components"):
        for path in (WEB / folder).rglob("*"):
            if path.suffix in (".ts", ".tsx") and ".test." not in path.name:
                out.append(path.read_text(errors="ignore"))
    return "\n".join(out)


def _pattern(path: str) -> re.Pattern:
    """The path's static chunks in order, with anything between them."""
    chunks = re.split(r"\{[^}]+\}", path)
    return re.compile(r"[^\s\"'`]*?".join(re.escape(c) for c in chunks))


def _routes() -> list[tuple[str, str]]:
    out = set()
    for route in pay.router.routes:
        for method in getattr(route, "methods", ()) or ():
            if method in ("HEAD", "OPTIONS"):
                continue
            out.add((method, route.path))
    return sorted(out)


ROUTES = _routes()
BLOB = _sources()


def test_the_web_tree_was_actually_read():
    """Without this the sweep is vacuous: a wrong path would read nothing and
    every endpoint would look unreachable — or, with the assertion inverted,
    reachable."""
    assert WEB.is_dir(), WEB
    assert len(BLOB) > 500_000, f"only {len(BLOB)} chars of frontend source found"
    assert "/api/payroll/runs" in BLOB


def test_there_are_enough_routes_to_be_worth_sweeping():
    """A prefix typo or a failed import would enumerate nothing and pass."""
    assert len(ROUTES) >= 60, len(ROUTES)


@pytest.mark.parametrize("method,path", ROUTES, ids=lambda v: str(v))
def test_every_payroll_endpoint_is_reachable_from_the_product(method, path):
    if (method, path) in UNREACHED:
        pytest.skip(UNREACHED[(method, path)])
    assert _pattern(path).search(BLOB), (
        f"{method} {path} is finished and mounted and NOTHING in apps/web calls "
        f"it. Give it a screen, or register it in UNREACHED with the reason — "
        f"an endpoint nobody can reach is work that was done and cannot be used."
    )


def test_every_registered_exception_is_still_a_real_endpoint():
    """A registration that outlives its endpoint is a reason for something that
    no longer exists, and it would silently excuse a future endpoint that
    happened to be given the same path."""
    for key in UNREACHED:
        assert key in ROUTES, f"{key} is registered as unreached but is not a route"


def test_a_registered_exception_carries_a_real_reason():
    for key, reason in UNREACHED.items():
        assert len(reason) > 80, f"{key} needs a reason, not a note"


# ─────────── the seven this finding was actually about ───────────

@pytest.mark.parametrize("method,path", [
    ("POST", "/api/payroll/employees/{employee_id}/settlement"),
    ("POST", "/api/payroll/employees/{employee_id}/settlement/record"),
    ("POST", "/api/payroll/employees/{employee_id}/arrears-relief"),
    ("POST", "/api/payroll/employees/{employee_id}/perquisites/value"),
    ("PUT", "/api/payroll/employees/{employee_id}/perquisites"),
    ("POST", "/api/payroll/employees/{employee_id}/salary-revisions"),
    ("GET", "/api/payroll/employees/{employee_id}/salary-revisions"),
    ("POST", "/api/payroll/employees/{employee_id}/loans"),
    ("GET", "/api/payroll/employees/{employee_id}/loans"),
    ("GET", "/api/payroll/24q-annexure-ii"),
    ("POST", "/api/payroll/salary-structures/{structure_id}/apply"),
])
def test_the_named_orphans_now_have_a_screen(method, path):
    """Named individually as well as swept, because the sweep would keep passing
    if one of these were deleted — and a deleted settlement endpoint is not a
    fixed finding."""
    assert (method, path) in ROUTES, f"{method} {path} no longer exists"
    assert _pattern(path).search(BLOB), f"{method} {path} is orphaned again"


def test_recording_a_settlement_is_gated_above_writing():
    """It posts an immutable journal, withholds against the year and closes the
    employee. `payroll:finalize`, the same tier as finalising a run — not
    `write`, which edits pay."""
    import inspect
    src = inspect.getsource(pay.record_settlement)
    assert 'rbac("payroll", "finalize")' in src
    assert 'rbac("payroll", "read")' in inspect.getsource(pay.preview_settlement)
