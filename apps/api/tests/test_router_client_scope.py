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
    # GST is THREE registrations of one feature: /api/gst, /api/gst-workspace
    # and /api/gst-portal. As with TDS, /api/gst is a string prefix of the
    # other two — _prefix_for takes the longest match.
    "/api/gst-workspace": (
        "assert_client_access", "_visible_or_none", "can_access_client",
        "_load_return_or_none",
    ),
    "/api/gst-portal": ("assert_client_access", "_assert_job_scope"),
    "/api/gst": ("assert_client_access",),
    "/api/mca-workspace": (
        "assert_client_access", "_visible_or_none", "can_access_client",
        "_load_or_none",
    ),
    # `entities` and the two entity↔entity tables carry no client column at all
    # (migrations 059/156) — they are firm-level and EXEMPT below. Everything
    # that names a client is guarded, and `_match_visible` is the sharp one:
    # a cross-client match row names TWO clients, so both are checked.
    "/api/relationships": (
        "assert_client_access", "filter_by_client", "can_access_client",
        "_match_visible", "_assert_role_scope", "is_firmwide",
    ),
    # Audited and found already correct — all four endpoints called
    # assert_client_access before this sweep reached them. Registering it is
    # still worth doing: it holds the claim, and the NEXT endpoint added here
    # fails closed. See the audit doc for what the tests could and could not
    # show, given only the Partner gets past rbac("accounting", "approve").
    "/api/reconciliation": ("assert_client_access",),
    # The small tail of the "guards the body, not the record" list, taken as
    # one batch. compliance_records was already fully guarded (task #238);
    # reminders and engagements each had row-addressed endpoints that checked
    # only the firm; task_templates is the firm-template pattern — its five
    # template routes are EXEMPT and only /instantiate names a client.
    "/api/reminders": (
        "assert_client_access", "filter_by_client", "can_access_client",
    ),
    "/api/engagements": (
        "assert_client_access", "filter_by_client", "_assert_engagement_scope",
    ),
    "/api/compliance-records": (
        "assert_client_access", "filter_by_client", "effective_client_ids",
    ),
    "/api/task-templates": ("assert_client_access",),
    # customers.client_id is required by CustomerIn — never absent on a real
    # row. create/bulk-create were already guarded (task #231); every OTHER
    # endpoint — including a write that can post a real opening-balance
    # journal, a soft delete, and a PERMANENT delete — checked only the firm.
    "/api/customers": (
        "assert_client_access", "can_access_client",
        "_load_customer_or_404", "_assert_customer_scope",
    ),
    # vendors.py mirrors customers.py exactly — same fix, same helper shape.
    "/api/vendors": (
        "assert_client_access", "can_access_client",
        "_load_vendor_or_404", "_assert_vendor_scope",
    ),
    # Every endpoint here requires Partner (PERMISSIONS["billing"] in
    # core/permissions.py is Partner-only for both actions) — the sole
    # firm-wide role, so M2 assignment-scope cannot be bypassed by
    # construction. What was real: the firm-boundary half of
    # assert_client_access, unchecked everywhere but create_schedule.
    # list_schedules uses filter_by_client (a no-op for a firm-wide caller
    # today, kept explicit for if "billing" is ever opened to Manager/
    # Executive); record_fee_receipt is row-addressed by invoice_id and uses
    # the named resolver _assert_invoice_scope, same convention as
    # sales_invoices.py's _assert_invoice_scope.
    "/api/billing": (
        "assert_client_access", "filter_by_client", "_assert_invoice_scope",
    ),
    # A live M2 gap, not a firm-boundary one: PERMISSIONS["invoice"] is
    # _AT_LEAST_EXECUTIVE (unlike billing's Partner-only), so Manager and
    # Executive both reach every endpoint here directly. fee_invoices.
    # client_id and fee_engagements.client_id are both NOT NULL (migration
    # 014) — nothing on this router is a firm-level resource in disguise.
    # run_overdue_check_endpoint is a firm-wide WRITE, confined per-caller
    # via effective_client_ids (the recurring_invoices.py /run pattern)
    # rather than narrowed as a list, since narrowing a write's OUTPUT after
    # the fact would be the wrong shape.
    "/api/invoices": (
        "assert_client_access", "filter_by_client", "effective_client_ids",
        "_assert_invoice_scope", "_assert_engagement_scope",
    ),
    # The last of the original twelve "guards the body, not the record"
    # routers. send_message/quick_chat/client_intelligence already guarded
    # their context_id/client_id before this phase; every other row-addressed
    # or query-param endpoint that reaches client-scoped data did not.
    # Four intelligence/dashboard endpoints are EXEMPT below — not because
    # they carry no client data, but because narrowing them properly needs
    # more than a guard; see the EXEMPT reasons and the audit doc.
    "/api/copilot": (
        "assert_client_access", "can_access_client", "filter_by_client",
        "effective_client_ids", "_assert_conversation_scope", "_assert_message_scope",
    ),
    # First of the "long tail" routers (not one of the original twelve).
    # Already the best-guarded file found so far — get_client_health,
    # get_dimension_detail, list_scores, get_score, get_score_history and
    # list_overrides all called assert_client_access/filter_by_client before
    # this phase. calculate_score and create_override (row-addressed by
    # client_id) had NO guard; deactivate_override and resolve_alert were
    # firm-scoped only (health_overrides.client_id / health_alerts.client_id
    # are both NOT NULL, migration 059); recalculate_all is a firm-wide
    # WRITE, confined per-caller via effective_client_ids rather than
    # narrowed as a list; health_dashboard returned NAMED critical/at-risk
    # client rows and alerts firm-wide, unfiltered.
    "/api/health": (
        "assert_client_access", "can_access_client", "filter_by_client",
        "effective_client_ids", "_assert_override_scope", "_assert_alert_scope",
    ),
    # year_end.py, year_end_checklist.py and year_end_adjustments.py all
    # declare the SAME router prefix ("/year-end") and are included at
    # app.include_router(..., prefix="/api") — three DISTINCT routers
    # sharing one namespace, the same shape as /api/gst's three-way split.
    # Registering "/api/year-end" here would sweep in year_end.py's
    # /engagements routes and year_end_checklist.py's /{id}/checklist
    # routes too — neither audited. The literal path segment
    # "/{engagement_id}/adjustments" is what actually distinguishes this
    # router's routes and does not string-prefix-collide with either
    # sibling's paths (they diverge at "engagements" / "checklist" vs
    # "adjustments").
    "/api/year-end/{engagement_id}/adjustments": (
        "can_access_client", "_load_engagement_or_404", "_fetch_engagement_db",
        "_assert_engagement_client_mock", "_guard_locked_mock",
    ),
    # Not one of the original twelve — found while working the long tail.
    # The router delegates 100% to domain/income_tax/{computation_workspace,
    # itr_workflow}.py rather than touching Supabase directly, so the four
    # row-addressed resolvers below live in the ROUTER but call new lookup
    # functions added to those two domain modules (get_snapshot,
    # get_disallowance, get_bf_loss, get_filing) rather than querying inline
    # — matching the router's existing layering instead of breaking it.
    # transition_filing/save_version/record_acknowledgement share ONE
    # resolver, _assert_filing_scope, since all three act on the same
    # itr_filings row via filing_id. create_snapshot/create_filing/
    # create_disallowance/auto_detect_40a3/create_deduction/create_bf_loss
    # were already guarded pre-phase (client_id is on the request body).
    "/api/itr": (
        "assert_client_access", "can_access_client",
        "_assert_snapshot_scope", "_assert_filing_scope",
        "_assert_disallowance_scope", "_assert_bf_loss_scope",
    ),
    # Platform admin tooling — cross-tenant BY DESIGN, gated by a completely
    # separate authorization system (core.platform_auth's require_platform_admin
    # / require_platform_admin_mfa, checked against the platform_admins
    # allowlist) rather than core.authz. It uses get_service_supabase() to
    # bypass firm RLS on purpose: a platform owner suspending or purging a
    # firm is not a firm member reaching a client, it is the operator of the
    # whole system. Every one of its 9 endpoints touches only firms/users
    # rows — never a client — so the empty tuple here is not an oversight;
    # nothing in this router could satisfy a client-scope check because none
    # of it is client data. All 9 endpoints are EXEMPT below with that
    # reasoning; this entry exists only so the sweep counts its routes as
    # looked-at rather than unaudited.
    "/api/platform": (),
    # year_end.py OWNS the collection (create/list/get/PATCH status) and
    # year_end_reviews.py owns a workflow nested one level deeper under the
    # SAME literal path segment ("/engagements/{engagement_id}/reviews/..."
    # is a string prefix of nothing shorter than "/engagements/
    # {engagement_id}" itself) — the sweep's prefix-longest-match can't
    # separate "the collection resource" from "a sub-resource of it owned by
    # a different file" the way it separated year_end_adjustments.py's
    # "/{engagement_id}/adjustments" from its year-end siblings, because
    # here there IS no distinguishing segment above the shared one: every
    # route year_end_reviews.py owns starts with a route year_end.py also
    # owns. Same shape as "/api/tasks" being shared by tasks.py and
    # task_extras.py — registering the shared prefix is a claim about BOTH
    # files, which is the honest reading here too: guarding the engagement
    # CRUD while leaving its review-approval-and-lock workflow open would be
    # absurd. year_end_reviews.py's 5 endpoints delegate to year_end.py's
    # own _assert_engagement_scope by name rather than duplicating the
    # check against the same table in a second file.
    "/api/year-end/engagements": (
        "assert_client_access", "can_access_client", "filter_by_client",
        "_assert_engagement_scope",
    ),
    # year_end_checklist.py — the standard 12-item checklist, addressed by
    # engagement_id (list, PATCH by item_id). "/checklist" is a literal
    # segment that string-prefix-collides with nothing else under
    # "/api/year-end" (siblings use "/adjustments", "/reviews", "/exports",
    # "/notes", "/financial-statements", "/schedules", "/engagements",
    # "mappings"). Delegates to year_end.py's _assert_engagement_scope by
    # name, same pattern as year_end_reviews.py.
    "/api/year-end/{engagement_id}/checklist": (
        "can_access_client", "_assert_engagement_scope",
    ),
    # year_end_statements.py owns TWO distinct literal segments —
    # "/financial-statements" (4 routes) and "/schedules" (1 route) — that
    # neither collide with each other nor with any sibling ("/adjustments",
    # "/reviews", "/checklist", "/exports", "/notes", "/engagements",
    # "mappings"). Registered as two entries since they're separate path
    # segments, both pointing at the same file's resolver. list_versions and
    # get_version never resolved the engagement at all before this fix —
    # live mode applied only an inline firm_id filter on
    # financial_statement_versions, mock mode had no tenancy check
    # whatsoever.
    "/api/year-end/{engagement_id}/financial-statements": (
        "can_access_client", "_assert_engagement_scope",
    ),
    "/api/year-end/{engagement_id}/schedules": (
        "can_access_client", "_assert_engagement_scope",
    ),
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
    # complete_filing is a one-line delegation to update_filing_status IN THE
    # SAME MODULE — the guard lives there, and forcing a second check into the
    # wrapper just to satisfy the sweep would be a check that means nothing.
    "/api/mca-workspace": "routers.mca_workspace",
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
    "/api/gst/classify":
        "classifies transaction rows the CALLER supplied into GST buckets. "
        "TransactionClassifyRequest has no client_id — nothing to check.",
    "/api/gst/gstr1/build":
        "builds the GSTR-1 JSON payload from classified rows in the request "
        "body. GSTR1Request has no client_id. The FROM-BOOKS variant, which "
        "reads a client's ledger, is guarded.",
    "/api/gst/gstr3b/compute":
        "computes GSTR-3B from figures in the request body. GSTR3BRequest "
        "has no client_id; the from-books variant is guarded.",
    "/api/gst/validate/gstr1":
        "runs the CGST §37 validators over a payload in the request body. "
        "No client_id, no stored data read.",
    "/api/gst/validate/gstr3b":
        "same, for CGST §39.",
    "/api/task-templates":
        "task_templates has a nullable firm_id and no client_id (migration "
        "063; NULL = shared system template). A template is the firm's "
        "reusable task definition — the same pattern as engagement and "
        "workflow templates, both already exempt. The one endpoint that "
        "names a client, /{template_id}/instantiate, IS guarded.",
    "/api/task-templates/{template_id}":
        "same table, addressed by id. Covers GET, PUT and DELETE; the "
        "system-template write protection (403 on firm_id NULL) is the "
        "router's own concern, not a client-scope one.",
    "/api/relationships/entities":
        "`entities` has a firm_id and NO client_id (migration 059). An entity "
        "is a person or company the firm knows about, and it is deliberately "
        "shared across clients — that sharing is what makes cross-client "
        "match detection possible at all. It can also exist with no roles "
        "yet. It IS traceable to clients through entity_roles, and whether "
        "the register itself should be narrowed that way is a product "
        "decision recorded in the audit doc, not a mechanical one. The "
        "ROLES returned by /entities/{entity_id} ARE narrowed.",
    "/api/relationships/entities/{entity_id}":
        "same table, addressed by id. EXEMPT is keyed by path, so this one "
        "entry covers both the PATCH and the GET. The PATCH edits the "
        "firm-level entity itself and has no client to check. The GET also "
        "returns the entity's ROLES, which do name clients — those ARE "
        "narrowed with filter_by_client, and because this exemption would "
        "let the endpoint pass either way, the narrowing is pinned by a "
        "runtime test rather than by the sweep.",
    "/api/relationships/relationships":
        "`entity_relationships` is an edge between two entities (migration "
        "059) and has no client column. The entities at both ends are "
        "firm-level; the edge cannot be more client-scoped than its ends.",
    "/api/relationships/entity-to-entity":
        "`entity_to_entity_relationships` (migration 156) — holding, "
        "subsidiary, associate and JV edges between firm-level entities. "
        "Companies Act §2(87)/§2(6). Same reasoning, no client column.",
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
    # billing.py: every endpoint requires Partner (PERMISSIONS["billing"] is
    # Partner-only), the sole firm-wide role — these nine paths have no
    # client_id in the request at all (verified by
    # test_no_exemption_covers_a_resource_that_does_carry_a_client below).
    "/api/billing/preview-run":
        "dry run across the firm's due schedules — no client_id in the "
        "request. Partner-only router; same reasoning as list_schedules.",
    "/api/billing/run":
        "firm-wide batch: generate drafts for every due schedule. No single "
        "client_id addressed — the firm-wide-capability pattern used "
        "elsewhere in the sweep (e.g. task-recurring's /run), except here "
        "RBAC already restricts the caller to Partner rather than needing a "
        "403 of its own.",
    "/api/billing/ar-aging":
        "firm-wide AR aging aggregate. No client_id in the request.",
    "/api/billing/collections/dashboard":
        "firm-wide collections KPIs. No client_id in the request.",
    "/api/billing/collections/sweep":
        "firm-wide batch: recompute aging on every open invoice. No single "
        "client addressed, same reasoning as /run above.",
    "/api/billing/collections/send-reminders":
        "firm-wide batch reminder sweep. No client_id in the request.",
    "/api/billing/collections/reminder-settings":
        "firm-level policy (GET and PUT) — cadence/cap/attach-PDF for the "
        "whole firm. No client_id in the request.",
    "/api/billing/staff-cost-rates":
        "firm-level staff HR data (list), not client data. No client_id in "
        "the request.",
    "/api/billing/staff-cost-rates/{user_id}":
        "same table, addressed by a STAFF user_id — not a client — for the "
        "write side.",
    "/api/copilot/suggestions":
        "GLOBAL/CLIENT/COMPLIANCE_SUGGESTED_QUESTIONS are hardcoded prompt "
        "lists in models/ai_copilot.py — no client_id in the request, no "
        "stored data read.",
    # These four aggregate across the whole firm with no per-client
    # identifiers in their CURRENT output — confirmed by reading
    # domain/ai_copilot_service.py's actual implementations, not the
    # aspirational Pydantic response models in models/ai_copilot.py (which
    # declare fields like at_risk_clients/cross_client_conflicts that the
    # real functions do not populate). That is a real gap, not a
    # non-issue — recorded as an open question in the audit doc rather than
    # guarded here, because a correct fix is bigger than a guard:
    "/api/copilot/intelligence/compliance":
        "get_compliance_intelligence caches ONE firm-wide summary per firm "
        "(ai_summaries, entity_id=None) shared across every caller "
        "regardless of assignment — narrowing the counts it computes "
        "without also changing the cache key would still serve a "
        "firm-wide-cached response to the next assignment-scoped caller.",
    "/api/copilot/intelligence/workflows":
        "failing_workflows/overdue_approvals come from workflow_failures/ "
        "workflow_approvals, neither of which carries a client_id column "
        "(only instance_id, migration 068) — narrowing by client requires "
        "joining through workflow_instances, which the repository does not "
        "currently expose.",
    "/api/copilot/intelligence/relationships":
        "cross_client_conflicts is computed over the firm's WHOLE client "
        "list by design (PAN/email-domain cross-matching only means "
        "something compared across every client) — the same tension "
        "already recorded for /api/relationships/entities: narrowing the "
        "input set would change what the analysis IS, not just who can "
        "see it.",
    "/api/copilot/executive-dashboard":
        "same caching issue as intelligence/compliance (ai_summaries, "
        "summary_type='executive', entity_id=None) — also aggregates "
        "revenue/capacity/churn signals across every client by design, "
        "the same tension as intelligence/relationships.",
    # platform.py — the platform OWNER's cross-tenant admin surface, not a
    # firm member's. Every endpoint reads/writes only firms/users rows via
    # get_service_supabase() and is gated by require_platform_admin(_mfa)
    # from core.platform_auth, a separate system from core.authz entirely.
    # GET and DELETE /firms/{firm_id} share this path (soft delete); the
    # HARD delete lives at its own /permanent path.
    "/api/platform/me":
        "UI gating only — returns whether the caller is a platform admin. "
        "Touches no table at all.",
    "/api/platform/stats":
        "firm-count/user-count/client-count TALLIES across the whole "
        "platform — the platform owner's dashboard, not scoped to any one "
        "firm's clients let alone one staff member's assignments.",
    "/api/platform/firms":
        "lists every firm on the platform with per-firm user/client counts. "
        "firms has no client_id — it IS the tenant boundary, one level "
        "above a client.",
    "/api/platform/firms/{firm_id}":
        "same table, addressed by id. Covers GET (firm detail) and DELETE "
        "(soft delete) — both act on the firm row itself, never a client.",
    "/api/platform/firms/{firm_id}/users":
        "lists a firm's staff (name/email/role/status) — users has a "
        "firm_id, not a client_id. Staff roster, not client data.",
    "/api/platform/firms/{firm_id}/suspend":
        "flips firms.is_active — a firm-level operational flag.",
    "/api/platform/firms/{firm_id}/unsuspend":
        "same field, the reverse operation.",
    "/api/platform/firms/{firm_id}/permanent":
        "irreversible hard delete of the firm and everything under it via "
        "platform_purge_firm — the firm IS the unit being removed, there is "
        "no narrower client to scope this to.",
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
              "/api/tds": 8,
              "/api/gst-workspace": 13, "/api/gst-portal": 5,
              "/api/gst": 7, "/api/mca-workspace": 13,
              "/api/relationships": 19,
              "/api/reconciliation": 4,
              "/api/reminders": 3, "/api/engagements": 7,
              "/api/compliance-records": 6, "/api/task-templates": 6, "/api/customers": 10,
              "/api/vendors": 10, "/api/billing": 16, "/api/invoices": 8,
              "/api/copilot": 17, "/api/health": 13,
              "/api/year-end/{engagement_id}/adjustments": 7,
              "/api/itr": 17, "/api/platform": 9,
              "/api/year-end/engagements": 9,
              "/api/year-end/{engagement_id}/checklist": 2,
              "/api/year-end/{engagement_id}/financial-statements": 4,
              "/api/year-end/{engagement_id}/schedules": 1}


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
                   "routers.tds_workspace", "routers.tds",
                   "routers.gst_workspace", "routers.gst_portal",
                   "routers.gst", "routers.mca_workspace",
                   "routers.relationships", "routers.reconciliation",
                   "routers.reminders", "routers.engagements",
                   "routers.compliance_records", "routers.task_templates",
                   "routers.customers", "routers.vendors", "routers.billing",
                   "routers.invoices", "routers.ai_copilot_v2", "routers.health",
                   "routers.year_end_adjustments", "routers.itr_workspace",
                   "routers.year_end"):
        src = inspect.getsource(importlib.import_module(module))
        assert re.search(r"^from core\.authz import", src, re.M), \
            f"{module} does not import core.authz"
