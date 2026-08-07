"""
Client-assignment scope across every router that has been audited for it.

`core.authz` makes only the **Partner** firm-wide (`_FIRMWIDE_ROLES`); a Manager,
Executive or Reviewer sees only the clients in `user_client_assignments`. Several
routers enforced none of it — `sales_invoices` and `purchase_bills` did not even
import `core.authz` — so an authenticated member of a firm could read and write
any client's records in it.

WHY A REGISTRY RATHER THAN A TEST PER ROUTER
    Per-endpoint tests only cover the endpoints someone remembered to write one
    for, which is the same failure mode as the bug. This walks the REGISTERED
    ROUTES of each audited router and fails for any endpoint that never consults
    the caller's client scope — so the next endpoint added to an audited router
    fails closed, before it ever reaches a database.

    `AUDITED` is the ratchet. Adding a router to it is a claim that every one of
    its endpoints has been looked at; the test then holds that claim true. It is
    deliberately NOT every router yet — see the audit doc for the backlog.

WHAT COUNTS AS CONSULTING THE SCOPE
    Either the endpoint names its client directly and calls `assert_client_access`
    (or narrows a firm-wide list with `filter_by_client` / `_scope_rows`), or it
    is addressed by a row id and calls that router's resolve-then-assert guard.
    Both are listed per router below, so a router cannot pass by accident on a
    helper that means something else.
"""
import inspect
import re

import pytest


# router prefix → the names that count as a client-scope check in it.
# A router is in here only once EVERY endpoint under its prefix has one.
AUDITED: dict[str, tuple[str, ...]] = {
    "/api/banking/": (
        "assert_client_access", "_scope_rows", "filter_by_client",
        "_assert_txn_scope", "_assert_recon_scope", "_assert_txn_batch_scope",
    ),
    "/api/sales-invoices": (
        "assert_client_access", "filter_by_client",
        "_assert_invoice_scope", "_assert_batch_scope",
    ),
    "/api/purchase-bills": (
        "assert_client_access", "filter_by_client",
        "_assert_bill_scope", "_assert_batch_scope",
    ),
    "/api/engagement-letters": (
        "assert_client_access", "filter_by_client", "_assert_engagement_scope",
    ),
    "/api/workflows": (
        "assert_client_access", "filter_by_client",
        "_assert_instance_scope", "_scope_by_instance",
    ),
}

# Endpoints whose RESOURCE has no client to scope to, with the reason. An
# exemption you have to write down and justify is a different thing from an
# endpoint nobody looked at — which is the whole point of listing them here
# rather than loosening the sweep.
EXEMPT: dict[str, str] = {
    "/api/engagement-letters/templates":
        "engagement_templates has firm_id and no client_id (migration 115) — a "
        "template is firm property, reused across every client. A client guard "
        "here would have to invent a client to check.",
    "/api/engagement-letters/templates/{template_id}":
        "same table, addressed by id.",
    "/api/workflows/templates":
        "workflow_templates has firm_id and nothing else (migration 068) — a "
        "template is the DEFINITION of a workflow, firm property. The RUNS "
        "(workflow_instances) carry the client, and those are guarded.",
    "/api/workflows/templates/{template_id}":
        "same table, addressed by id.",
    "/api/workflows/templates/{template_id}/toggle":
        "same table: enabling or disabling a firm-level definition.",
    "/api/workflows/schedules":
        "workflow_schedules has firm_id and nothing else (migration 068) — when "
        "a firm-level definition runs, not who it runs for.",
    "/api/workflows/schedules/{schedule_id}":
        "same table, addressed by id.",
    "/api/workflows/schedules/{schedule_id}/toggle":
        "same table, addressed by id.",
    "/api/workflows/analytics":
        "firm-wide operational aggregates — counts, success rates and template "
        "names. No client identifier is returned, and the per-template "
        "breakdown is over firm-level definitions.",
}

# How many endpoints each audited router is expected to have, at least. Without
# this a prefix typo would silently make the sweep vacuous — it would enumerate
# nothing and pass.
MIN_ROUTES = {"/api/banking/": 50, "/api/sales-invoices": 18,
              "/api/purchase-bills": 10, "/api/engagement-letters": 19,
              "/api/workflows": 20}


def _routes():
    from main import app
    out = []
    for r in app.routes:
        path = getattr(r, "path", "")
        prefix = next((p for p in AUDITED if path.startswith(p)), None)
        if prefix is None:
            continue
        for m in sorted(getattr(r, "methods", set()) - {"HEAD", "OPTIONS"}):
            out.append((prefix, path, m, r.endpoint))
    return out


ROUTES = _routes()


@pytest.mark.parametrize("prefix,minimum", sorted(MIN_ROUTES.items()))
def test_the_sweep_actually_finds_each_audited_router(prefix, minimum):
    """A sweep that matches nothing passes every assertion below vacuously."""
    found = [r for r in ROUTES if r[0] == prefix]
    assert len(found) >= minimum, \
        f"{prefix}: expected at least {minimum} routes, found {len(found)} — bad prefix?"


@pytest.mark.parametrize("prefix,path,method,endpoint",
                         [pytest.param(*r, id=f"{r[2]} {r[1]}") for r in ROUTES])
def test_every_endpoint_in_an_audited_router_consults_client_scope(
        prefix, path, method, endpoint):
    """Source-level on purpose: this has to fail on an endpoint nobody has
    written a runtime test for yet — that is the whole point of it."""
    if path in EXEMPT:
        return
    src = inspect.getsource(endpoint)
    if any(name in src for name in AUDITED[prefix]):
        return
    pytest.fail(
        f"{method} {path} never consults the caller's client scope. "
        f"Firm scoping alone lets any member of the firm reach every client in "
        f"it. Expected one of: {', '.join(AUDITED[prefix])}. If this resource "
        f"genuinely has no client_id, add it to EXEMPT with the reason.")


def test_every_exemption_names_a_route_that_exists():
    """A stale exemption is an unguarded endpoint hiding behind a dead entry —
    a rename would silently move the endpoint out of the sweep."""
    live = {p for _prefix, p, _m, _e in ROUTES}
    for path in EXEMPT:
        assert path in live, f"EXEMPT lists {path}, which is no longer a route"


def test_no_exemption_covers_a_resource_that_does_carry_a_client():
    """The exemptions are all 'this table has no client_id'. If one of these
    handlers ever starts reading a client_id, the reason has stopped being true
    and the exemption has to go."""
    by_path = {p: e for _prefix, p, _m, e in ROUTES}
    for path in EXEMPT:
        src = inspect.getsource(by_path[path])
        assert "client_id" not in src, (
            f"{path} is exempt on the grounds that its resource has no client, "
            f"but its handler now mentions client_id — re-check the exemption.")


def test_a_row_addressed_endpoint_is_not_satisfied_by_a_bare_client_check():
    """`assert_client_access(current_user, client_id)` is meaningless where there
    is no client_id in the request — the id has to be resolved to its owner
    first. Endpoints keyed by a row id must use their router's resolve-then-assert
    guard, not the bare check."""
    resolvers = ("_assert_txn_scope", "_assert_recon_scope",
                 "_assert_invoice_scope", "_assert_bill_scope",
                 "_assert_engagement_scope", "_assert_instance_scope")
    checked = 0
    for prefix, path, method, endpoint in ROUTES:
        # Keyed by a row id, and nothing else in the request names a client.
        if path in EXEMPT:
            continue
        if not re.search(r"\{(txn|recon|invoice|bill|engagement|instance|approval|failure)_id\}", path):
            continue
        src = inspect.getsource(endpoint)
        assert any(r in src for r in resolvers), (
            f"{method} {path} is addressed by a row id but only checks a "
            f"client_id it was handed — there isn't one.")
        checked += 1
    assert checked >= 35, f"expected the row-addressed endpoints, found {checked}"


def test_every_audited_router_actually_imports_the_authz_engine():
    """sales_invoices and purchase_bills passed review for years while importing
    no authz at all. An import is cheap to check and impossible to fake."""
    import importlib
    for module in ("routers.banking", "routers.sales_invoices",
                   "routers.purchase_bills", "routers.engagement_letters",
                   "routers.workflow_builder"):
        src = inspect.getsource(importlib.import_module(module))
        assert re.search(r"^from core\.authz import", src, re.M), \
            f"{module} does not import core.authz"
