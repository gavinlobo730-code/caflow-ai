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
    # year_end_notes.py — Notes to Accounts, addressed by engagement_id
    # (list, generate, get/PATCH/lock by note_id). "/notes" doesn't
    # string-prefix-collide with any sibling. list_notes, get_note and
    # lock_note never resolved the engagement at all before this fix.
    "/api/year-end/{engagement_id}/notes": (
        "can_access_client", "_assert_engagement_scope",
    ),
    # year_end_exports.py — the last of the year-end siblings entangled by
    # collision with year_end.py's own "/engagements" branch (all others
    # are "/{engagement_id}/..." like this one, colliding with nothing but
    # each other — "/exports" is disjoint from "/adjustments", "/reviews",
    # "/checklist", "/notes", "/financial-statements", "/schedules").
    # get_download_url was the sharpest gap: it hands back a live signed
    # Storage URL to the export PDF, so an unassigned caller reaching it
    # was a real exfiltration path, not just metadata.
    "/api/year-end/{engagement_id}/exports": (
        "can_access_client", "_assert_engagement_scope",
    ),
    # year_end_mappings.py — Chart of Accounts -> Schedule III line mapping.
    # account_group_mappings has firm_id and no client_id at all: a firm's
    # mapping of its own chart of accounts to statutory line items is a
    # firm-wide configuration, applied uniformly across every client, same
    # reasoning as task_templates/engagement_templates/workflow_templates
    # (all already EXEMPT below). Genuinely disjoint from the rest of the
    # year-end cluster: "/mappings" is a distinct top-level segment, not
    # nested under "/{engagement_id}/...". Empty tuple + EXEMPT entries
    # below complete the entire year-end cluster this sweep started with
    # year_end_adjustments.py.
    "/api/year-end/mappings": (),
    # portal.py — CA-facing document requests, messages and dues for a
    # client's portal. NOT the same surface as portal_self.py/
    # portal_data.py's "/api/portal/self/*" and "/api/portal/me"/
    # "/dashboard"/"/memberships"/"/accept-invite" routes — those serve the
    # CLIENT's own portal login (get_current_portal_client/get_jwt_user), a
    # structurally different authorization model (a portal contact sees
    # only their own bound client_id, not a firm-staff assignment), and are
    # out of scope for this sweep. Confirmed no literal-segment collision:
    # "document-requests"/"messages"/"dues" (this file) vs "clients"/
    # "contacts" (portal_access.py) vs "self"/"me"/"dashboard"/
    # "memberships"/"accept-invite" (portal_self.py/portal_data.py).
    "/api/portal/document-requests": (
        "assert_client_access", "_assert_doc_request_scope",
    ),
    "/api/portal/messages": ("assert_client_access",),
    "/api/portal/dues": ("assert_client_access",),
    # portal_access.py — CA-side portal-contact management (enable a
    # client's portal, invite/resend/deactivate a contact). list/invite are
    # addressed directly by client_id (assert_client_access); resend/
    # deactivate are row-addressed by contact_id and previously had no
    # client check at all — the service layer's get_contact() checked only
    # firm_id.
    "/api/portal/clients": ("assert_client_access",),
    "/api/portal/contacts": (
        "can_access_client", "_assert_contact_scope",
    ),
    # clients.py — the root Client resource. get_client_workspace/update_client/
    # archive_client/restore_client/delete_client all previously checked only
    # _assert_firm(client, firm_id) (firm boundary, not assignment) — any
    # Executive/Reviewer (read) or Manager (write) in the firm could reach ANY
    # client in it, not just their assigned book. _assert_firm now takes
    # current_user and also raises on !can_access_client, reusing the identical
    # "Client not found" text so the firm-check and assignment-check branches
    # cannot be distinguished (message-oracle). delete_client is Partner-only
    # by RBAC (_PARTNER_ONLY, the sole firm-wide role) so the added check can
    # never actually deny a real caller there — it still goes through the same
    # path for consistency. list_clients was already correct (effective_client_ids).
    "/api/clients": (
        "effective_client_ids", "_assert_firm", "can_access_client",
    ),
    # credit_notes.py, debit_notes.py, purchase_credit_notes.py,
    # sales_debit_notes.py — the four GST note-type routers. None imported
    # core.authz at all before this fix, the same shape as sales_invoices.py/
    # purchase_bills.py before THEIR fix earlier in this sweep. list_*/
    # create_* took client_id from the query/body and never checked it;
    # get_*/update_*/issue_*/delete_* (and debit_notes.py's/
    # purchase_credit_notes.py's upload/document-url pair, which mints a live
    # signed Storage URL) are row-addressed and checked only firm_id. Each
    # resolver uses can_access_client with ONE fixed message covering every
    # failure branch (missing / wrong firm / right firm but unassigned) in
    # BOTH mock and live mode — the year_end.py `_assert_engagement_scope`
    # shape, not the older permissive-in-mock/id-embedded-message shape
    # sales_invoices.py used. Confirmed disjoint prefixes — each string is
    # owned by exactly one router file.
    "/api/credit-notes": ("assert_client_access", "can_access_client", "_assert_cn_scope"),
    "/api/debit-notes": ("assert_client_access", "can_access_client", "_assert_dn_scope"),
    "/api/purchase-credit-notes": ("assert_client_access", "can_access_client", "_assert_pcn_scope"),
    "/api/sales-debit-notes": ("assert_client_access", "can_access_client", "_assert_sdn_scope"),
    # service_catalogue.py — the Product/Service catalogue, CLIENT-owned by
    # design (migration 182: "Client B must never inherit Client A's
    # products"). The router never imported core.authz at all before this
    # fix. list_services/create_service take client_id directly (query/
    # body) and use assert_client_access, the sales_invoices.py list/create
    # shape; bulk_create_services checks every DISTINCT client_id in the
    # batch up front via _assert_batch_scope, before any row is processed —
    # same convention as sales_invoices.py's own _assert_batch_scope.
    # update_service/delete_service/record_service_used are row-addressed
    # and used _assert_service_scope (can_access_client, ONE fixed message
    # — "Service not found." — already the pre-existing text every one of
    # these handlers used for its own missing-row branch, so the fix
    # introduces no second wording for the same condition).
    "/api/service-catalogue": (
        "assert_client_access", "can_access_client", "_assert_service_scope",
        "_assert_batch_scope",
    ),
    # time_tracking.py. stop_timer/update_entry/delete_entry are
    # row-addressed and checked only firm_id (list_entries right above them
    # already used filter_by_client — M2/M5); create_manual_entry/
    # start_timer take an optional client_id and never checked it either —
    # assert_client_access is a no-op for client_id=None (client-less/
    # internal-work entries), so this doesn't break that case.
    # _assert_entry_scope is the row-addressed resolver (can_access_client,
    # ONE fixed "Time entry not found" message, already the pre-existing
    # text). Also fixed beyond the audit doc's original 2-route count for
    # this path: export_entries had NO assignment filtering at all — now
    # threads effective_client_ids into time_export_service.export_time_entries,
    # which drops any entry outside it (client-less entries always kept).
    "/api/time-entries": (
        "assert_client_access", "can_access_client", "filter_by_client",
        "effective_client_ids", "_assert_entry_scope",
    ),
    # dsc.py — Digital Signature Certificate tracker. dsc_records has a
    # firm_id and NO client_id column at all (migration 014, grepped the
    # whole table + router) — a DSC belongs to the FIRM (a partner, staff
    # member, or the firm's own token), not to any one client's book. There
    # is no assignment to check against; every route is EXEMPT below.
    "/api/dsc": (),
    # firm_hsn_library.py — the firm's own CA-curated HSN/SAC code list.
    # firm_hsn_library has a firm_id and NO client_id column (migration
    # 179) — firm-wide BY DESIGN per the module's own docstring: "the
    # library itself stays firm-wide, shared across all of the firm's
    # clients, even though the Product/Service referencing a code is
    # client-owned" (service_catalogue.py, which IS client-owned, is fixed
    # above). Every route is EXEMPT below.
    "/api/firm-hsn-library": (),
    # branding.py — firm Branding, Invoice Settings, Invoice Templates and
    # Email Templates, all under "/api/settings". Grepped the whole file:
    # no client_id anywhere. Firm-level configuration applied uniformly
    # across every client the firm serves — the same reasoning as
    # task-templates/engagement-templates/workflow-templates/year-end
    # mappings, all already EXEMPT above. Every route is EXEMPT below.
    "/api/settings": (),
    # identity.py — staff (users) administration: create/invite, activate,
    # suspend, role change, force-logout, login history. `users` and
    # `login_events` both have a firm_id and NO client_id column at all
    # (migrations 003/085, grepped) — a "user" here is a STAFF MEMBER of the
    # firm, not a client; there is no assignment to check. Every route is
    # EXEMPT below.
    "/api/identity": (),
    # tally_migration.py — tally_migration_jobs.client_id is OPTIONAL
    # (ledgers/journals can be a firm-level migration; customers/vendors
    # need a target client — domain/tally/migration_service.py's
    # _import_single_item). create_job checks the request-body client_id
    # directly via assert_client_access (replacing a bespoke inline
    # firm-only query that never checked assignment); list_jobs returned
    # EVERY job in the firm unfiltered — now narrowed with filter_by_client
    # (an Executive/Reviewer/Manager could otherwise see which other
    # clients had a migration in progress outside their own book);
    # get_job/parse_xml/preview_import/execute_import/rollback_import are
    # row-addressed by job_id and use the new _assert_job_scope resolver
    # (can_access_client, ONE fixed "Migration job not found" message — was
    # two different strings, "Migration job not found" vs "Job not found",
    # before this fix, a pre-existing message-oracle inconsistency closed
    # as a side effect). can_access_client(user, None) is always True, so a
    # client-less (firm-level) job is unaffected throughout.
    "/api/tally-migration": (
        "assert_client_access", "can_access_client", "filter_by_client",
        "_assert_job_scope",
    ),
    # accounting.py — Chart of Accounts, Journal Entries, Ledger, Trial
    # Balance, P&L, Balance Sheet. chart_of_accounts.client_id is NULLABLE
    # (migration 003: NULL = firm-level template); journal_entries.client_id
    # is NOT NULL (every journal belongs to exactly one client).
    # list_journal_entries/create_journal_entry/post_opening_balances_endpoint/
    # list_journals_queue took client_id from the query/body and never
    # checked it. update_account/post_journal_entry (the row-addressed,
    # legacy in-memory engine — see the module note above
    # create_journal_entry) are row-addressed and had NO check at all, not
    # even firm_id; _assert_account_scope/_assert_journal_scope replace the
    # id-embedded NotFoundError text with ONE fixed message covering missing
    # and hidden alike (year_end.py's shape). post_draft_journal
    # (/journals/{journal_id}/post) and reverse_journal_entry
    # (/journal/{entry_id}/reverse) require `accounting.approve`, Partner-only
    # by RBAC (the sole firm-wide role) — M2 cannot be bypassed by
    # construction there, so _assert_draft_scope and the inline
    # can_access_client check close only the firm-BOUNDARY half, the same
    # convention billing.py's Partner-only record_fee_receipt used. The seven
    # reporting endpoints (ledger/trial-balance/profit-loss/balance-sheet/
    # schedule-iii/cash-flow/statement-analysis) now check a NAMED client_id;
    # the client_id=None "firm-wide consolidation" case is recorded, not
    # fixed — see get_ledger's docstring and the audit doc, the same line
    # drawn for /api/copilot/intelligence/*.
    "/api/accounting": (
        "assert_client_access", "can_access_client", "filter_by_client",
        "_assert_account_scope", "_assert_draft_scope", "_assert_journal_scope",
    ),
    # approvals.py — Module 9.0/M4 maker-checker governance inbox.
    # approval_requests has a firm_id and NO client_id column at all
    # (migration 083) — a request (user create/activate, role change,
    # client-assignment change, COA change) is a FIRM governance object, not
    # a client's. assignment_create/assignment_remove/assignment_transfer
    # name a client_id inside their JSONB payload, but the ROW ITSELF has no
    # client column to check assignment against — there is no narrower scope
    # to apply than the RBAC already in place (read: Manager+, approve:
    # Partner-only, core/permissions.py). Every route is EXEMPT below.
    "/api/approvals": (),
    # xbrl_engine.py — MCA XBRL package generation. xbrl_packages.client_id
    # is NOT NULL (migration 156). create_package/list_packages took
    # client_id from the body/query and never checked it; update_package_data/
    # validate_package/generate_xml/review_package are row-addressed by
    # package_id and checked only firm_id — an unassigned Executive (write)
    # or Manager (approve) could read/edit/validate/generate-XML/review
    # another staff member's assigned client's Balance Sheet and P&L data.
    # _assert_package_scope is the year_end.py-shaped resolver (can_access_
    # client, ONE fixed "XBRL package not found." message) in both mock and
    # live mode. get_tag_mappings is the one EXEMPT route — the statutory
    # Schedule III -> XBRL tag table, identical for every firm and client.
    "/api/xbrl": ("assert_client_access", "can_access_client", "_assert_package_scope"),
    # income_tax.py — ITR/HRA/capital-gains/advance-tax computation. /compute,
    # /hra/compute, /capital-gains/cii-table, /capital-gains/compute and
    # /advance-tax/compute are stateless calculators with no client_id in
    # their request models — EXEMPT below. create_capital_gains and
    # save_advance_tax already called assert_client_access pre-phase (tasks
    # #238/#230). list_capital_gains/list_advance_tax took client_id from the
    # query string and only ever filtered it into the firm-scoped WHERE
    # clause, never checking the caller's assignment; delete_capital_gains is
    # row-addressed by record_id and checked only firm_id.
    # _assert_capital_gains_scope is the new resolver (can_access_client, one
    # fixed "Capital gains record not found" message, the year_end.py shape) —
    # a no-op in mock mode, which has no persistent store to protect.
    "/api/income-tax": ("assert_client_access", "can_access_client", "_assert_capital_gains_scope"),
    # "/api/compliance" is a SHARED prefix — TWO DISTINCT FILES both declare
    # APIRouter(prefix="/api/compliance"): compliance.py (4 routes: /tasks,
    # /calendar, /seed, /due-dates/calculate — the older compliance_calendar
    # entity) and compliance_ops.py (8 routes: /obligations/*, /dashboard,
    # /run-escalations — the canonical compliance_records entity, Phase
    # 4.4). Same shape as "/api/tasks" (tasks.py + task_extras.py) and "/api
    # /gst" (three files) — registering the shared prefix is a claim about
    # BOTH files.
    #
    # compliance.py: list_compliance_tasks and compliance_calendar already
    # used filter_by_client pre-phase (client_id, when supplied, is narrowed
    # into the firm-scoped query AND then filtered — a caller-named foreign
    # client_id returns rows filter_by_client immediately drops, so this was
    # already correct, not merely permissive). seed_compliance_calendar
    # checked only client.firm_id == firm_id (a bespoke inline check, the
    # tally_migration.py-shaped gap) and never the caller's assignment — an
    # Executive/Manager could seed ~30 compliance task rows into any other
    # staff member's assigned client. calculate_due_dates is a stateless
    # due-date calculator (year/month only) — EXEMPT below.
    #
    # compliance_ops.py: list_obligations and obligations_calendar already
    # used filter_by_client pre-phase. assign_obligation/transition_
    # obligation/mark_filed_obligation called the domain service directly
    # (get_record/update_record/mark_filed), which checks only firm_id — the
    # SAME compliance_records table routers/compliance_records.py
    # additionally guards with assert_client_access at its own call site
    # (_assert_obligation_scope mirrors that call site rather than pushing
    # the check into the shared domain service). generate_obligations/
    # compliance_dashboard/run_escalations ran across the WHOLE FIRM with no
    # assignment check at all — compliance.write/read are Executive+, not
    # firm-wide-only (core/permissions.py) — confined via allowed_client_ids
    # =effective_client_ids(...), the same F2 convention compliance_record_
    # service.get_firm_summary already used.
    "/api/compliance": (
        "assert_client_access", "filter_by_client", "effective_client_ids",
        "_assert_obligation_scope",
    ),
    # ai_insights.py — the AI-generated insight feed (Chapter 17). ai_insights
    # has a client_id column (repositories/ai_insights_repository.py).
    # list_insights took client_id from the query string and never checked
    # it when supplied; when NOT supplied it returned every insight in the
    # FIRM, now narrowed with filter_by_client (the tally_migration.py-shaped
    # gap). generate_insights is row-addressed by client_id in the path and
    # had no check at all — an unassigned Executive/Manager could trigger a
    # real AI generation run against another staff member's client.
    # ack_insight/dismiss_insight are row-addressed by insight_id and checked
    # only firm_id; new _assert_insight_scope resolver (can_access_client,
    # one fixed "Insight not found" message, the year_end.py shape).
    # insight_feed returns NAMED insight rows (each carrying client_id/
    # client_name) firm-wide with no narrowing at all — confined via
    # allowed_client_ids=effective_client_ids(...) threaded into
    # get_insight_feed, the same F2 convention compliance_ops.py's
    # generate_obligations/compliance_dashboard/run_escalations used.
    # cross_client_patterns is the one EXEMPT route below — see its reason.
    "/api/ai-insights": (
        "assert_client_access", "filter_by_client", "effective_client_ids",
        "_assert_insight_scope",
    ),
    # eway_bill.py — CGST Act §68/Rule 138. create_eway_bill already called
    # assert_client_access pre-phase. list_eway_bills took client_id from
    # the query string and never checked it. record_ewb_generated/
    # extend_ewb/cancel_ewb are row-addressed by record_id with NO client_id
    # in the request body at all and checked only firm_id — an unassigned
    # staff member with gst.approve could record/extend/cancel another
    # client's E-Way Bill just by guessing or observing a record_id. New
    # get_eway_bill lookup (domain/income_tax/eway_service.py) + router-level
    # _assert_ewb_scope resolver (can_access_client, one fixed "E-Way Bill
    # record not found" message) closes the row-addressed gap.
    "/api/eway-bill": ("assert_client_access", "_assert_ewb_scope"),
    # inventory.py — stock register, per-item ledger, manual adjustment and
    # NRV write-down for kind='good' catalogue items (migration 188).
    # service_catalogue.client_id is NOT NULL (migration 182, service_
    # catalogue.py's own AUDITED entry). None of the four endpoints here
    # imported core.authz at all before this fix — list_stock_items/
    # get_item_stock_ledger take client_id from the query string,
    # adjust_stock/writedown_stock_to_nrv from the request body
    # (StockAdjustmentIn.client_id / NrvWritedownIn.client_id, both
    # required), and none of the four checked it — an unassigned Executive
    # (read) or Manager (write) could read another staff member's client's
    # stock register or post a real inventory adjustment (with its own GL
    # journal, CGST Act §17(5)(h) ITC reversal) against it.
    "/api/inventory": ("assert_client_access",),
    # engagement_sign_public.py — client-facing engagement-letter signing,
    # registered WITHOUT the staff auth guard at all (see the module
    # docstring): there is no firm-staff JWT, no core.authz applicable, and
    # no user to check an assignment for. The unguessable sign_token IS the
    # credential, and every query is already constrained to the single row
    # it resolves to via `.eq("sign_token", token)` — structurally the same
    # "different authorization model" carve-out already recorded for
    # portal_self.py/portal_data.py's "/api/portal/self/*" client-portal-
    # login surface (see the AUDITED note on portal.py above). Registered
    # with an empty tuple (the /api/platform shape) purely so the sweep
    # counts its 3 routes as looked-at rather than silently skipped; every
    # one is EXEMPT below with this same reasoning.
    "/api/public/engagement-letters": (),
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
    "/api/year-end/mappings":
        "account_group_mappings has firm_id and no client_id at all "
        "(grepped the whole file) — a firm's mapping of its own chart of "
        "accounts to Schedule III line items is firm-wide configuration, "
        "identical across every client, the same reasoning as "
        "task-templates/engagement-templates/workflow-templates. Covers "
        "GET and POST, which share this path.",
    "/api/year-end/mappings/bulk":
        "same table, the bulk-upsert variant.",
    "/api/year-end/mappings/defaults":
        "same table — default mapping suggestions plus firm-level "
        "auto-initialization from the firm's own chart of accounts.",
    "/api/clients":
        "shared by GET list_clients and POST create_client. create_client "
        "makes a brand-new client — there is no existing client_id to check "
        "assignment against. list_clients already narrows via "
        "effective_client_ids (pre-existing, marked 'M2: assignment scope' "
        "in the code) — real coverage, just not visible to this path-level "
        "check since POST shares the path and this test picks one winner per "
        "path. The row-addressed siblings ({client_id}, {client_id}/archive, "
        "{client_id}/restore) are guarded via _assert_firm and are NOT "
        "exempt — this entry covers only the bare '/api/clients' path.",
    # dsc.py — dsc_records has firm_id and no client_id column at all
    # (migration 014). Covers GET (list) and POST (create), which share
    # this path.
    "/api/dsc":
        "dsc_records has a firm_id and NO client_id column (migration 014) "
        "— a Digital Signature Certificate belongs to the firm (a partner, "
        "staff member, or the firm's own token), not to any client's book. "
        "Covers GET (list_dsc) and POST (create_dsc), which share this path.",
    "/api/dsc/{dsc_id}":
        "same table, addressed by id. Covers PATCH (update_dsc) and DELETE "
        "(delete_dsc).",
    "/api/dsc/{dsc_id}/renew":
        "same table, the renew (extend expiry) operation.",
    # firm_hsn_library.py — firm_hsn_library has firm_id and no client_id
    # column at all (migration 179), firm-wide by design per the module's
    # own docstring.
    "/api/firm-hsn-library/":
        "firm_hsn_library has a firm_id and NO client_id column (migration "
        "179) — the firm's own HSN/SAC code library is firm-wide by "
        "design, shared across every client the firm serves (see the "
        "module docstring). Covers GET (list_library) and POST (add_code), "
        "which share this path.",
    "/api/firm-hsn-library/bulk":
        "same table, the bulk-import variant.",
    "/api/firm-hsn-library/bulk-delete":
        "same table, the bulk permanent-delete variant.",
    "/api/firm-hsn-library/{library_id}":
        "same table, addressed by id. Covers PATCH (update_code) and "
        "DELETE (retire_code).",
    "/api/firm-hsn-library/{library_id}/purge":
        "same table, the permanent-delete-once-unused operation.",
    # branding.py — firm Branding/Invoice Settings/Invoice Templates/Email
    # Templates, all under /api/settings. Grepped the whole file: no
    # client_id anywhere. Firm-level configuration, applied uniformly
    # across every client — same reasoning as task/engagement/workflow
    # templates and year-end mappings, all already exempt above.
    "/api/settings/branding":
        "firm_branding has a firm_id and no client_id (repositories/"
        "branding_repository.py, grepped) — the firm's own logo/colours/"
        "font, applied to every document it issues. Covers GET "
        "(get_branding) and PUT (upsert_branding).",
    "/api/settings/branding/logo":
        "same resource, the logo-upload endpoint.",
    "/api/settings/invoice-settings":
        "firm invoice numbering/bank-details configuration — firm-level, "
        "no client_id. Covers GET and PUT.",
    "/api/settings/invoice-templates":
        "firm-level invoice template DEFINITIONS (layout/font choices), "
        "reused across every client's invoices — no client_id. Covers GET "
        "(list) and POST (create).",
    "/api/settings/invoice-templates/{template_id}":
        "same table, addressed by id. Covers PATCH (update) and DELETE.",
    "/api/settings/invoice-templates/{template_id}/set-default":
        "same table, the set-default operation.",
    "/api/settings/email-templates":
        "firm-level email template DEFINITIONS (subject/body per "
        "template_type), reused across every client's correspondence — no "
        "client_id. Covers GET (list) and POST (upsert).",
    "/api/settings/email-templates/{template_id}":
        "same table, addressed by id. Covers PATCH (update) and DELETE.",
    # time_tracking.py — the two "my own" endpoints. Addressed by the
    # caller's own user_id, not a client; there is no OTHER staff member's
    # data being read, so there is nothing for an assignment check to gate.
    "/api/time-entries/summary/me":
        "addressed by the caller's own user_id, not a client — my_summary "
        "aggregates only entries the caller logged "
        "(time_tracking_repo.get_summary(user_id=current_user['id'])). The "
        "by_client breakdown in the response reflects the caller's OWN "
        "work, never another staff member's assigned book.",
    "/api/time-entries/running/me":
        "same reasoning — addressed by the caller's own user_id "
        "(find_running(user_id=current_user['id'])), returns only the "
        "caller's own currently-running timer, never another staff "
        "member's.",
    # identity.py — staff administration. `users`/`login_events` have a
    # firm_id and NO client_id column (migrations 003/085) — every route
    # manages STAFF accounts, not clients.
    "/api/identity/users":
        "users has a firm_id and NO client_id (migration 003) — a staff "
        "roster, not client data. Covers GET (list_users) and POST "
        "(create_user).",
    "/api/identity/users/{user_id}/role":
        "same table, addressed by a STAFF user_id — not a client.",
    "/api/identity/users/{user_id}/suspend":
        "same table, addressed by a staff user_id.",
    "/api/identity/users/{user_id}/reactivate":
        "same table, addressed by a staff user_id.",
    "/api/identity/users/{user_id}/force-logout":
        "same table, addressed by a staff user_id.",
    "/api/identity/users/{user_id}/login-history":
        "login_events has a firm_id and NO client_id (migration 085) — a "
        "staff member's own sign-in history, addressed by their user_id.",
    "/api/identity/force-logout-all":
        "firm-wide batch: revokes every staff member's sessions. No "
        "client_id in the request or touched table.",
    "/api/identity/login-history":
        "same table as above, the firm-wide feed (GET, no id).",
    "/api/identity/accept-invite":
        "completes a staff invite from a server-issued token — identity is "
        "established from the verified JWT and the pre-created invite row, "
        "never a client_id.",
    "/api/identity/login-event":
        "records the CALLER's own sign-in/sign-out event. No client_id.",
    # accounting.py — the two firm-level path groups.
    "/api/accounting/accounts":
        "AccountIn (models/accounting.py) has no client_id field at all — the "
        "public API can only ever create a firm-level account; "
        "chart_of_accounts.client_id IS nullable (migration 003, NULL = "
        "firm-level template) but nothing here ever sets it. Covers GET "
        "(list_accounts) and POST (create_account), which share this path. "
        "A client-specific Chart of Accounts is a real schema capability "
        "the API never exposes — recorded as a product gap in the audit "
        "doc, not a client-scope one.",
    "/api/accounting/year-lock":
        "firms.locked_financial_years (migration 136) is a firm-level "
        "financial-year lock, no client_id — the whole firm's books lock "
        "together for a given FY. Covers GET (get_year_lock) and POST "
        "(set_year_lock, Partner-only), which share this path.",
    # approvals.py — every route, approval_requests has no client_id column
    # at all (migration 083). See the AUDITED entry above for the full
    # reasoning; each entry below just names the path it covers.
    "/api/approvals":
        "approval_requests has a firm_id and NO client_id column (migration "
        "083) — a governance request is a firm object. Covers GET "
        "(list_approvals) and POST (create_approval), which share this path.",
    "/api/approvals/types":
        "the static REQUEST_TYPES tuple. No stored data read at all.",
    "/api/approvals/{request_id}":
        "same table, addressed by id (get_approval).",
    "/api/approvals/{request_id}/approve":
        "same table, the approve transition (Partner-only, MFA-guarded).",
    "/api/approvals/{request_id}/reject":
        "same table, the reject transition (Partner-only, MFA-guarded).",
    "/api/approvals/{request_id}/cancel":
        "same table, the cancel transition (requester or Partner only, "
        "enforced by services/approval_service.cancel).",
    # xbrl_engine.py — the one route with no client at all.
    "/api/xbrl/tag-mappings":
        "the statutory Schedule III -> MCA XBRL taxonomy tag table "
        "(domain/income_tax/xbrl_service.DEFAULT_MAPPINGS) — identical for "
        "every firm and every client, no stored data read.",
    # income_tax.py — five stateless calculators. None of their request
    # models carry a client_id; nothing is persisted or read from a table.
    "/api/income-tax/compute":
        "ComputeITRRequest has no client_id — a pure tax computation over "
        "caller-supplied income/deduction figures, nothing stored or read.",
    "/api/income-tax/hra/compute":
        "plain scalar query params (basic/hra/rent/is_metro) — Section "
        "10(13A) exemption math, nothing stored or read.",
    "/api/income-tax/capital-gains/cii-table":
        "the statutory Cost Inflation Index table (Section 48 2nd proviso) "
        "— identical for every firm and client, no stored data read.",
    "/api/income-tax/capital-gains/compute":
        "ComputeCapitalGainsRequest has no client_id — a stateless "
        "estimator, does not persist anything (unlike POST /capital-gains, "
        "which does and is guarded).",
    "/api/income-tax/advance-tax/compute":
        "ComputeAdvanceTaxRequest has no client_id — a stateless Section "
        "234C interest estimator, does not persist anything (unlike POST "
        "/advance-tax, which does and is guarded).",
    # compliance.py (sharing the /api/compliance prefix with compliance_ops.py
    # — see the AUDITED comment) — the one stateless route.
    "/api/compliance/due-dates/calculate":
        "plain year/month query params — GST/ITR due-date math (CGST Act "
        "§§37/39), no client_id, nothing stored or read.",
    # ai_insights.py — the one route with no real client-scoped data.
    "/api/ai-insights/cross-client":
        "get_cross_client_patterns (domain/ai_insight_service.py) is a "
        "hardcoded stub that returns the same fixed sample patterns for "
        "every firm regardless of real data — its own docstring says so "
        "('In production this would query the DB... For now return "
        "realistic mock patterns.'). There is no real client-scoped row "
        "here for an assignment check to gate.",
    # engagement_sign_public.py — see the AUDITED entry above for the full
    # reasoning (public token-bearer flow, no firm-staff caller at all).
    "/api/public/engagement-letters/{token}":
        "public, token-scoped (view_letter) — no firm-staff user, no "
        "core.authz applicable. Every query is constrained to the single "
        "engagement the unguessable sign_token resolves to.",
    "/api/public/engagement-letters/{token}/sign":
        "same token-scoped flow, the recipient's electronic acceptance "
        "(IT Act 2000 §10A).",
    "/api/public/engagement-letters/{token}/reject":
        "same token-scoped flow, the recipient's decline.",
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
              "/api/year-end/{engagement_id}/schedules": 1,
              "/api/year-end/{engagement_id}/notes": 5,
              "/api/year-end/{engagement_id}/exports": 5,
              "/api/year-end/mappings": 4,
              "/api/portal/document-requests": 3, "/api/portal/messages": 2,
              "/api/portal/dues": 1, "/api/portal/clients": 2,
              "/api/portal/contacts": 2,
              "/api/clients": 7,
              "/api/credit-notes": 6, "/api/debit-notes": 8,
              "/api/purchase-credit-notes": 8, "/api/sales-debit-notes": 6,
              "/api/service-catalogue": 6, "/api/time-entries": 9,
              "/api/dsc": 5, "/api/firm-hsn-library": 7, "/api/settings": 14,
              "/api/identity": 11, "/api/tally-migration": 7,
              "/api/accounting": 19, "/api/approvals": 7, "/api/xbrl": 7,
              "/api/income-tax": 10, "/api/compliance": 12,
              "/api/ai-insights": 6, "/api/eway-bill": 5, "/api/inventory": 4,
              "/api/public/engagement-letters": 3}


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
                   "routers.year_end", "routers.portal", "routers.portal_access",
                   "routers.clients", "routers.credit_notes", "routers.debit_notes",
                   "routers.purchase_credit_notes", "routers.sales_debit_notes",
                   "routers.service_catalogue", "routers.time_tracking",
                   "routers.tally_migration", "routers.accounting",
                   "routers.xbrl_engine", "routers.income_tax",
                   "routers.compliance", "routers.compliance_ops",
                   "routers.ai_insights", "routers.eway_bill",
                   "routers.inventory"):
        src = inspect.getsource(importlib.import_module(module))
        assert re.search(r"^from core\.authz import", src, re.M), \
            f"{module} does not import core.authz"
