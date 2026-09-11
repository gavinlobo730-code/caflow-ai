"""An endpoint the product never calls is an endpoint nobody can use.

WHY THIS IS TREE-WIDE AND NOT ANOTHER PER-MODULE CHECK

`test_a_finished_payroll_endpoint_is_reachable.py` has enforced this for
`/api/payroll` since PAY-11, and it works: of the 904 routes this app mounts,
payroll accounts for exactly ONE that no screen reaches — the ECR retract,
registered there on purpose with its reason. The other 46 prefixes, which have
never had such a check, account for the rest.

That is the finding, and it is the argument for the file: the defect is not any
particular unreachable endpoint. It is that an endpoint can be written,
reviewed, tested and merged without one line of the product calling it, and
every test in the suite still passes — because every test in the suite calls it
directly.

WHY A BUDGET RATHER THAN A LIST OF EXEMPTIONS

The honest alternative was 137 entries each saying "deliberate". That is not a
policy, it is paperwork — the same conclusion Track F6's rule 3 reached after
its first shape failed on 23 files. Several of the 137 are also FALSE
POSITIVES of the matcher and cannot be cleared by writing prose about them: a
screen that builds a path suffix from a variable

    fetch(`${API}/api/public/engagement-letters/${token}${path}`)   // /sign

is genuinely calling the endpoint, and no static scan of this shape can see it.

So this is a RATCHET, like `MAX_UNREADABLE` in
test_backend_columns_exist_pg.py. The number may fall and may never rise. A new
endpoint with no caller pushes a module over its budget and fails here, naming
it; wiring one up lets the budget be lowered in the same commit. Nothing has to
be explained up front, and the situation cannot quietly get worse.

WHAT THIS CHECKS IS WEAKER THAN IT LOOKS, AND THE DIFFERENCE MATTERS

It matches PATHS, not (method, path) pairs — inherited from the payroll guard,
and a real limit rather than an oversight. One `fetch` to
`/api/dsc/${id}/renew` satisfies the pattern for `PATCH /api/dsc/{dsc_id}` and
`DELETE /api/dsc/{dsc_id}` as well, because all three are `/api/dsc/` followed
by something. This was found by writing the file: budgeting `/api/dsc` at 2 on
the assumption that only renew had been wired produced an actual count of 0
before the edit path existed.

So a green run means "some screen names a URL of this shape", NOT "every verb on
it is used". Tightening it would mean reading the `method:` out of each call
site's options object and pairing it with the URL — fragile against a verb held
in a variable, which is the same blind spot one level down. The looser check is
kept and its looseness written here, because a guard a reader trusts for more
than it proves is worse than one whose limits are on the label.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from main import app

WEB = pathlib.Path(__file__).resolve().parents[3] / "apps" / "web"

#: Per-prefix ceilings, measured against the tree of 2026-09-11. Lower one in
#: the same commit that wires a screen up; raising one is a claim that a new
#: endpoint is deliberately unreachable, and belongs in a review.
#:
#: `/api/payroll`'s 1 is the ECR retract, which
#: test_a_finished_payroll_endpoint_is_reachable.py registers with its reason —
#: that file stays the stricter check for its own module, and this one is the
#: floor under every other.
BUDGET: dict[str, int] = {
    "/api/year-end": 10, "/api/task-recurring": 9, "/api/itr": 9,
    "/api/tasks": 8, "/api/engagements": 7, "/api/relationships": 7,
    "/api/income-tax": 6, "/api/gst-portal": 5, "/api/lifecycle": 5,
    "/api/health": 4, "/api/mca-workspace": 4, "/api/sales-invoices": 4,
    "/api/xbrl": 4, "/api/gst": 4, "/api/recurring-invoices": 4,
    "/api/tds": 3, "/api/invoices": 3,
    "/api/ai-copilot": 2, "/api/analytics": 2, "/api/billing": 2,
    "/api/customers": 2, "/api/form-26as": 2, "/api/onboarding": 2,
    "/api/scheduler": 2, "/api/vendors": 2, "/api/public": 2,
    "/api/ai-insights": 1, "/api/approvals": 1, "/api/banking": 1,
    "/api/copilot": 1, "/api/customer-statements": 1,
    "/api/identity": 1, "/api/tds-workspace": 1, "/api/memory": 1,
    "/api/document-intelligence-v2": 1, "/api/purchase-payments": 1,
    "/api/team": 1, "/api/accounting": 1, "/api/automation": 1,
    "/api/compliance": 1, "/api/eway-bill": 1, "/api/payments": 1,
    "/api/payroll": 1, "/api/purchase-bills": 1, "/api/tally-migration": 1,
}

TOTAL_BUDGET = 133


def _sources() -> str:
    """Every .ts/.tsx in the product, minus its own tests.

    Tests are excluded so a test that merely NAMES an endpoint cannot make it
    look reachable — the exact mistake this guards against, one level up.
    """
    out = []
    for folder in ("app", "lib", "components"):
        for path in (WEB / folder).rglob("*"):
            if path.suffix in (".ts", ".tsx") and ".test." not in path.name:
                out.append(path.read_text(errors="ignore"))
    return "\n".join(out)


def _pattern(path: str) -> re.Pattern:
    """The path's static chunks in order, with anything between them.

    Matching only the last segment would be far too loose — "settlement" and
    "loans" occur in screens that have nothing to do with the endpoint.
    """
    chunks = re.split(r"\{[^}]+\}", path)
    return re.compile(r"[^\s\"'`]*?".join(re.escape(c) for c in chunks))


def _routes() -> set[tuple[str, str]]:
    out = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/"):
            continue
        for method in (getattr(route, "methods", set()) or set()):
            if method not in ("HEAD", "OPTIONS"):
                out.add((method, path))
    return out


@pytest.fixture(scope="module")
def unreached() -> dict[str, list[str]]:
    blob = _sources()
    by_prefix: dict[str, list[str]] = {}
    for method, path in sorted(_routes()):
        if not _pattern(path).search(blob):
            by_prefix.setdefault("/".join(path.split("/")[:3]), []).append(
                f"{method} {path}")
    return by_prefix


def test_the_route_scan_still_sees_the_app(unreached):
    """A scan that stops matching keeps passing while checking nothing."""
    assert len(_routes()) > 500, (
        "the app mounts far fewer routes than expected — the scan is probably "
        "reading a half-imported app, not a shrunken product")


def test_no_module_exceeds_its_unreachable_budget(unreached):
    over = {
        prefix: (len(items), BUDGET.get(prefix, 0), items)
        for prefix, items in unreached.items()
        if len(items) > BUDGET.get(prefix, 0)
    }
    assert not over, "\n".join(
        f"{prefix}: {found} unreachable, budget {allowed} — {items}"
        for prefix, (found, allowed, items) in sorted(over.items())
    ) + (
        "\n\nAn endpoint no screen calls cannot be used by a CA, however well "
        "it is tested. Wire it up, or raise the budget in the same commit and "
        "say why."
    )


def test_the_total_only_goes_down(unreached):
    """The per-module budgets can hide a shuffle; the total cannot."""
    found = sum(len(v) for v in unreached.values())
    assert found <= TOTAL_BUDGET, (
        f"{found} endpoints reach no screen, budget {TOTAL_BUDGET}. Lower the "
        f"budget when you wire one up; raising it needs a reason.")


def test_no_budget_entry_is_stale(unreached):
    """A budget that outlives its debt is how a ratchet stops ratcheting."""
    slack = {
        prefix: (allowed, len(unreached.get(prefix, [])))
        for prefix, allowed in BUDGET.items()
        if allowed > len(unreached.get(prefix, []))
    }
    assert not slack, (
        f"these budgets are above what the tree actually owes — lower them: "
        f"{ {p: f'budget {a}, actual {n}' for p, (a, n) in sorted(slack.items())} }"
    )
