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
import io
import re
import tokenize

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
    # knowledge's guards live in the SERVICE, not the router — see FOLLOW below.
    # `_load_article_or_404` is deliberately NOT listed: it is a loader that
    # exists whether or not it checks anything, so naming it let the sweep pass
    # on a service with every check stripped out. Only names that cannot exist
    # without the check belong here.
    "/api/knowledge": (
        "_assert_client_access", "can_view_client_content",
    ),
    "/api/clients/{client_id}/instructions": (
        "_assert_client_access", "can_view_client_content",
    ),
    "/api/clients/{client_id}/knowledge": (
        "_assert_client_access", "can_view_client_content",
    ),
    "/api/lifecycle": (
        "assert_client_access", "filter_by_client",
        "_assert_row_scope", "_assert_via_parent",
    ),
    "/api/payroll": (
        "assert_client_access", "filter_by_client", "_assert_run_scope",
        "_assert_employee_scope", "_assert_slip_scope",
    ),
    "/api/recurring-invoices": (
        "assert_client_access", "filter_by_client", "effective_client_ids",
        "_assert_template_scope",
    ),
    "/api/memory": (
        "assert_client_access", "filter_by_client",
        "_assert_trigger_scope", "_assert_anomaly_scope", "_assert_firmwide",
    ),
    # /api/tasks is shared by TWO routers — tasks.py and task_extras.py. The
    # sweep keys on the path prefix, so registering it is a claim about both,
    # which is the honest reading: guarding the tags on a task while leaving
    # PATCH on the same task open would be absurd.
    "/api/tasks": (
        "assert_client_access", "filter_by_client", "effective_client_ids",
        "_assert_task_scope", "_assert_firmwide_job",
    ),
    # A SEPARATE router on its own prefix — /api/tasks does not cover it, which
    # is exactly the trap: the two read as one feature and are two registrations.
    "/api/task-recurring": (
        "assert_client_access", "filter_by_client", "effective_client_ids",
        "_assert_config_scope",
    ),
    # `_visible_or_none` is the row-addressed half: this router reports a
    # missing row as a 200 with {"success": false}, so a 404 refusal would
    # make the status code an oracle. See the note in the router.
    "/api/tds-workspace": (
        "assert_client_access", "_visible_or_none", "can_access_client",
    ),
    # A SECOND TDS router. "/api/tds" is a string PREFIX of "/api/tds-workspace",
    # which is why _routes() takes the longest match rather than the first.
    "/api/tds": ("assert_client_access",),
}

# Routers whose endpoints are one-line delegations, with the client-scope check
# living in the service they call. Following the call is the only way to tell a
# thin-but-guarded router from an unguarded one — refusing to follow would force
# a pointless second check into the router just to satisfy a test.
#
# Bounded to the named module and two levels, so this stays a check rather than
# a whole-program analysis: endpoint → service function → the helper it calls
# (knowledge's `_load_article_or_404` is exactly that second level).
FOLLOW: dict[str, str] = {
    "/api/knowledge": "services.knowledge_service",
    "/api/clients/{client_id}/instructions": "services.knowledge_service",
    "/api/clients/{client_id}/knowledge": "services.knowledge_service",
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
    "/api/lifecycle/leads":
        "leads has a firm_id and no client_id (migration 059) — a lead is not "
        "yet a client, so there is no assignment to check against. Whether "
        "leads should carry a scope of their own is an open product question, "
        "recorded in the audit doc.",
    "/api/lifecycle/leads/{lead_id}":
        "same table, addressed by id.",
    "/api/memory/firm/profile":
        "firm_profiles has firm_id and nothing else (migration 070) — the "
        "firm's own intelligence profile, not any client's. It IS derived by "
        "aggregating across the firm's clients, which is why the COMPUTE that "
        "writes it is limited to firm-wide roles; the resulting figures are "
        "firm-level and are what every member of the firm already sees on the "
        "dashboards.",
    "/api/tasks/summary/dashboard":
        "aggregate counts only — open tasks by status, overdue counts, a "
        "high-risk-client TALLY. No client is named and no per-client figure is "
        "returned. Same line as the lifecycle dashboard: the counts are derived "
        "from client rows, and that is stated rather than glossed over.",
    "/api/tds/compute-amount":
        "a calculator: section + amount in, rate + TDS in paise out. The "
        "request model has no client_id at all — there is nothing to check "
        "and no client data touched.",
    "/api/tds/sections":
        "the statutory TDS rate table for a financial year (domain/tds/"
        "section_rates.py). Reference data from the IT Act, identical for "
        "every firm and every client.",
    "/api/lifecycle/dashboard":
        "aggregate counts only: lead stage tallies, a proposal count, an "
        "overdue-renewal count. No client is named and no per-client figure is "
        "returned. The renewal count IS a cardinality signal derived from "
        "client rows — that is the line being drawn, stated rather than "
        "pretending the endpoint touches nothing client-shaped.",
}

# How many endpoints each audited router is expected to have, at least. Without
# this a prefix typo would silently make the sweep vacuous — it would enumerate
# nothing and pass.
MIN_ROUTES = {"/api/banking/": 50, "/api/sales-invoices": 18,
              "/api/purchase-bills": 10, "/api/engagement-letters": 19,
              "/api/workflows": 20, "/api/knowledge": 7,
              "/api/clients/{client_id}/instructions": 4,
              "/api/clients/{client_id}/knowledge": 1,
              "/api/lifecycle": 19, "/api/payroll": 16,
              "/api/recurring-invoices": 11,
              "/api/memory": 14,
              "/api/tasks": 15, "/api/task-recurring": 9,
              "/api/tds-workspace": 12,
              "/api/tds": 8}


def _code_only(src: str) -> str:
    """`src` with comments and string literals removed.

    Without this the sweep can be satisfied by PROSE: a docstring that merely
    explains `can_view_client_content` counts as calling it, so a service with
    every check stripped out still passed on the strength of its own commentary.
    Matching has to be on code.
    """
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        # A fragment that will not tokenise on its own (an indented def pulled
        # out of a class): fall back to the raw text rather than skipping it,
        # which would be the permissive direction.
        return src
    return " ".join(out)


def _reachable_source(prefix: str, endpoint, depth: int = 2) -> str:
    """The endpoint's source, plus that of the service functions it delegates to.

    Only for prefixes in FOLLOW, only into the one module named there, and only
    `depth` levels deep — enough for endpoint → service → helper, and no more.
    """
    src = inspect.getsource(endpoint)
    module_name = FOLLOW.get(prefix)
    if not module_name:
        return src
    import importlib
    mod = importlib.import_module(module_name)
    seen, frontier = set(), [src]
    for _ in range(depth):
        nxt = []
        for text in frontier:
            for name in re.findall(r"\b([a-z_][a-z0-9_]*)\s*\(", text):
                fn = getattr(mod, name, None)
                if fn is None or name in seen or not callable(fn):
                    continue
                seen.add(name)
                try:
                    body = inspect.getsource(fn)
                except (OSError, TypeError):      # builtins, C functions
                    continue
                src += "\n" + body
                nxt.append(body)
        frontier = nxt
    return src


def _prefix_for(path: str, registry=None):
    """The AUDITED prefix a route belongs to — the LONGEST match, not the first.

    `/api/tds` is a string prefix of `/api/tds-workspace`. Under first-match,
    which of the two claimed a workspace route depended on their declaration
    order in AUDITED — so the route would be checked against the wrong router's
    guard names, and nobody maintains that ordering deliberately. `registry` is
    a seam for the test that pins this with the shadowing prefix declared first.
    """
    reg = AUDITED if registry is None else registry
    return max((p for p in reg if path.startswith(p)), key=len, default=None)


def _routes():
    from main import app
    out = []
    for r in app.routes:
        path = getattr(r, "path", "")
        prefix = _prefix_for(path)
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
    src = _code_only(_reachable_source(prefix, endpoint))
    if any(name in src for name in AUDITED[prefix]):
        return
    pytest.fail(
        f"{method} {path} never consults the caller's client scope. "
        f"Firm scoping alone lets any member of the firm reach every client in "
        f"it. Expected one of: {', '.join(AUDITED[prefix])}. If this resource "
        f"genuinely has no client_id, add it to EXEMPT with the reason.")


def test_a_shadowing_prefix_does_not_capture_a_longer_ones_routes():
    """Declared worst-first on purpose: this is the order that breaks under
    first-match, and dict order is not something anyone maintains on purpose."""
    shadowed = {"/api/tds": (), "/api/tds-workspace": ()}
    assert _prefix_for("/api/tds-workspace/challans", shadowed) == "/api/tds-workspace"
    assert _prefix_for("/api/tds/sections", shadowed) == "/api/tds"


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
                   "routers.workflow_builder", "routers.lifecycle",
                   "routers.payroll", "routers.recurring_invoices",
                   "routers.memory_intelligence", "routers.tasks",
                   "routers.task_extras", "routers.task_recurring",
                   "routers.tds_workspace", "routers.tds"):
        src = inspect.getsource(importlib.import_module(module))
        assert re.search(r"^from core\.authz import", src, re.M), \
            f"{module} does not import core.authz"
