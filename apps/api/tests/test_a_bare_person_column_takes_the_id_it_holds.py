"""A person column with no foreign key is written with the one id it holds, and what the scan cannot read is listed (POST-A-361, part 2).

WHAT WAS LEFT
    Migration 566 makes the database refuse a row that names a member of another firm, but only on a column that has a foreign key to
    `users`. Seventy-nine uuid columns named for a person have none, and they cannot become keys by a blanket rule: `current_user`
    carries two ids, `users.id` (the internal one) and `auth_user_id` (Supabase's), and the columns disagree about which they take. Read
    against the production data on 1-11-2026 (every row of the 24 that had rows): ELEVEN hold the auth id, NINE hold `users.id`, and
    `audit_log.actor_id` and `client_timeline_events.actor_id` are mixed on purpose. A key to `users(id)` is right for the nine and
    WRONG for the eleven. Nothing on a screen is wrong today (a reader that resolves a creator tries both ids), so what a wrong writer
    does is leave a column that two readers now disagree about. The model for this guard is
    `test_users_fk_columns_take_the_internal_id_pg.py`, which covers the keyed columns from the schema.

WHAT THIS HOLDS (mock mode, no database)
    * THE MAP. The twenty columns whose data was read are named below with the id each holds. It is data, not a rule written from
      memory: it is the production reading of 1-11-2026, and a column is added to it by reading its rows.
    * THE RULE ON A DIRECT WRITE. Every `.table(T).insert(...)`, `.upsert(...)` or `.update(...)` in the API whose payload is a dict
      literal (or a name assigned a dict literal, a list or comprehension of them, or given the column by a subscript assignment in
      the same function) is read for the mapped column. A value that is the auth id where the column holds `users.id`, or the
      internal id where it holds the auth id, FAILS: that is the review-workflow defect again (23503 behind a key, or a silent
      mixed column behind none).
    * THE CHAIN IS FOLLOWED TO ITS ORIGIN (POST-A-361, 3-11-2026). A value that is a parameter is followed through every caller, and through
      the callers of those, up to twelve hops, through a nested helper's outer function, through a call made on a declared factory's result,
      and through a call made on something the scan cannot name when the function's name is defined once. Each origin is `users`, `auth`, a
      deliberate empty or `unread`. All of the writers the scan can see are PROVEN this way, the posting kernel's `posted_by` through its whole
      caller graph, and `UNREAD` is empty. The three columns no direct writer is seen for (`BUILT_ELSEWHERE`) are proven through the
      functions that build their rows.
    * WHAT THE SCAN CANNOT READ IS LISTED, NOT PASSED. A value that is a bare name (a parameter that arrived from a caller), a
      conditional or a call is `unread`, and each is on the list below with the function it sits in. The list is an equality in both
      directions: a new writer of a mapped column whose value the scan cannot read fails until someone reads it and adds it, and a
      listed one that has since become readable (or gone) fails until it is deleted. THE LIST IS NOT A CLAIM THAT THESE ARE RIGHT. It is
      the set of writes nobody has traced to the principal the value came from, which is what the ledger line is for.
    * A payload built elsewhere (`repo.create(payload)`, a helper's dict) is not seen at all; the second limit, also named in the ledger.
    * THE SCAN IS NOT BLIND: synthetic writers show a wrong id of each kind flagged, a right one passed, a name unread, and a
      subscript assignment found.

THE COLUMNS WITH NO ROWS ARE DECIDED FROM THE CODE (POST-A-377, 14-11-2026)
    The twenty above were read from data. The other person columns with no key held no rows, so `DECIDED_FROM_CODE` names the id each takes
    and what in the code decides it, and the guard follows their writers like the twenty's. Doing so found the bank pass path writing the
    internal id into `audit_log.actor_id` through three functions, `bank_transactions.matched_by` and `transfer_paired_by` written with
    both ids, and the client timeline's actor written with the internal id by nine of its 77 writers; each was changed so the column holds
    one kind. To prove the new writers the trace now also follows `self.f(...)` inside the class that defines `f`, a member id a person
    typed that a lookup in `users` checks (`CHECKED_AS_A_MEMBER`), another mapped column read off its row (`READ_OFF_A_ROW`), an attribute
    of an object built with that keyword here or by a helper in the same file, and a column written back with its own earlier value; a
    builder may carry the value under a database function's parameter name. A column nothing writes a person into yet is not decided
    (`NO_PERSON_WRITTEN_YET`): the day a person is written into one, a test fails and its writer maps it. A column that names a portal
    contact, an employee or a platform administrator is in `OTHER_PRINCIPALS`. `test_every_person_column_with_no_key_is_mapped_or_named_pg`
    holds the four lists equal to every such column a migration-built database has.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from tests._call_graph import chain_of

API = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("routers", "services", "repositories", "domain", "jobs", "core")

#: (table, column) -> the id it holds. Read against production on 1-11-2026 (POST-A-361): every row of each held that id.
READ_FROM_ROWS: dict[tuple[str, str], str] = {
    # the auth id (`auth_user_id`)
    ("client_sales_invoices", "created_by"): "auth", ("engagement_events", "user_id"): "auth", ("year_end_notes", "created_by"): "auth",
    ("engagement_templates", "created_by"): "auth", ("ai_conversations", "user_id"): "auth", ("engagements", "created_by"): "auth",
    ("onboarding_tasks", "completed_by"): "auth", ("customer_payment_links", "created_by"): "auth",
    ("year_end_engagements", "created_by"): "auth", ("bank_reconciliations", "created_by"): "auth", ("dsc_records", "deleted_by"): "auth",
    # the internal id (`users.id`)
    ("inventory_stock_ledger", "created_by"): "users", ("journal_entries", "posted_by"): "users", ("login_events", "user_id"): "users",
    ("bank_transactions", "posted_by"): "users", ("client_instructions", "created_by"): "users", ("gstr2b_uploads", "created_by"): "users",
    ("time_entries", "user_id"): "users", ("form_26as_uploads", "created_by"): "users", ("self_assessment_challans", "created_by"): "users",
}

#: (table, column) -> (the id it holds, what in the code decides it). DECIDED FROM THE CODE on 14-11-2026 (POST-A-377), for the columns that
#: had no rows to read. A column compared with `auth.uid()`, or written beside one that is, takes the sign-in id; one checked against
#: `users.id` before it is written, or written beside a column that is a key to `users`, takes the internal id. Where the writers
#: disagreed (`bank_transactions.matched_by` and `transfer_paired_by`, `client_timeline_events.actor_id`) the minority writer was changed
#: in the same commit, so the guard below finds each column written one way. The decision is about the KIND of id, not the person: a
#: column that names a portal contact, an employee or a platform administrator is in `OTHER_PRINCIPALS` instead.
DECIDED_FROM_CODE: dict[tuple[str, str], tuple[str, str]] = {
    # the sign-in id
    ("ai_feedback", "user_id"): ("auth", "the copilot's feedback route writes the caller's sign-in id"),
    ("ai_memory_triggers", "acknowledged_by"): ("auth", "the memory route writes the caller's sign-in id (a table only production has, migration 507)"),
    ("audit_log", "actor_id"): ("auth", "the audit trigger writes auth.uid() (migration 111); test_the_audit_log_names_one_kind_of_actor"),
    ("bank_reconciliations", "completed_by"): ("auth", "beside created_by, which holds the sign-in id on every row read"),
    ("bank_reconciliations", "reopened_by"): ("auth", "beside created_by, which holds the sign-in id on every row read"),
    ("bank_transaction_splits", "created_by"): ("auth", "the split route passes the sign-in id to the split function (migration 256)"),
    ("billing_schedules", "created_by"): ("auth", "the billing route writes the caller's sign-in id"),
    ("client_portal_users", "invited_by"): ("auth", "the portal invitation writes the inviting member's sign-in id"),
    ("closed_account_markers", "auth_user_id"): ("auth", "the purge writes each member's own sign-in id (`users.auth_user_id`) and core/auth "
                                                         "compares it with the caller's verified sign-in id (migration 772)"),
    ("clients", "archived_by"): ("auth", "the archive route writes the caller's sign-in id"),
    ("clients", "deleted_by"): ("auth", "the delete route writes the caller's sign-in id"),
    ("client_timeline_events", "actor_id"): ("auth", "every timeline writer but one passed the sign-in id; that one is changed here"),
    ("customer_statement_deliveries", "sent_by_id"): ("auth", "the statement mail route writes the caller's sign-in id"),
    ("financial_statement_versions", "created_by"): ("auth", "the year-end statements route writes the caller's sign-in id"),
    ("health_alerts", "resolved_by"): ("auth", "the health route writes the caller's sign-in id"),
    ("health_overrides", "override_by"): ("auth", "the health route writes the caller's sign-in id"),
    ("invoice_deliveries", "sent_by_id"): ("auth", "every invoice mail route writes the caller's sign-in id"),
    ("payroll_employees", "portal_invited_by"): ("auth", "the employee portal invitation writes the inviting member's sign-in id"),
    ("recurring_invoice_templates", "created_by"): ("auth", "the recurring invoice route writes the caller's sign-in id"),
    ("workflow_approvals", "responder_id"): ("auth", "the workflow builder's respond route writes the caller's sign-in id"),
    ("workflow_failures", "resolved_by"): ("auth", "the workflow builder's resolve route writes the caller's sign-in id"),
    ("workflow_schedules", "created_by"): ("auth", "the workflow builder writes the caller's sign-in id"),
    ("workflow_templates", "created_by"): ("auth", "the workflow builder writes the caller's sign-in id"),
    ("workflow_templates", "updated_by"): ("auth", "the workflow builder writes the caller's sign-in id"),
    ("year_end_adjustments", "created_by"): ("auth", "beside year_end_engagements.created_by, which holds the sign-in id on every row read"),
    ("year_end_adjustments", "submitted_by"): ("auth", "the adjustment's submit route writes the caller's sign-in id"),
    ("year_end_adjustments", "approved_by"): ("auth", "the adjustment's approve route writes the caller's sign-in id"),
    ("year_end_adjustments", "posted_by"): ("auth", "the adjustment's post route writes the caller's sign-in id"),
    ("year_end_adjustments", "rejected_by"): ("auth", "the adjustment's reject route writes the caller's sign-in id"),
    ("year_end_checklist_items", "completed_by"): ("auth", "the checklist route writes the caller's sign-in id"),
    ("year_end_exports", "created_by"): ("auth", "the export routes write the caller's sign-in id"),
    ("year_end_notes", "locked_by"): ("auth", "beside year_end_notes.created_by, which holds the sign-in id on every row read"),
    # the internal id (`users.id`)
    ("approval_requests", "requested_by"): ("users", "the MFA reset reads it back with user_repo.find_by_id"),
    ("approval_requests", "decided_by"): ("users", "the approval engine writes the deciding member's users.id"),
    ("bank_transactions", "matched_by"): ("users", "beside posted_by, which holds users.id on every row read; the match route is changed here"),
    ("bank_transactions", "transfer_paired_by"): ("users", "beside posted_by, which holds users.id on every row read; the pair route is changed here"),
    ("client_sales_invoices", "rate_selected_by"): ("users", "copied onto journal_entries.rate_selected_by, beside posted_by (users.id)"),
    ("compliance_records", "preparer_id"): ("users", "checked to be a member of the firm by users.id before it is written"),
    ("compliance_records", "reviewer_id"): ("users", "checked to be a member of the firm by users.id before it is written"),
    ("compliance_records", "approver_id"): ("users", "checked to be a member of the firm by users.id before it is written"),
    ("delivery_challan_returns", "created_by"): ("users", "the goods-back route passes users.id to the lot function (migration 585)"),
    ("delivery_challan_returns", "retracted_by"): ("users", "the retraction route passes users.id to the retraction function (migration 651)"),
    ("documents", "deleted_by"): ("users", "beside uploaded_by and reviewed_by, keys to users; the delete route is changed here (no rows held)"),
    ("fee_engagements", "assigned_to"): ("users", "checked to be a member of the firm by users.id before it is written"),
    ("fee_engagements", "reviewer_id"): ("users", "checked to be a member of the firm by users.id before it is written"),
    ("fee_engagements", "partner_id"): ("users", "checked to be a member of the firm by users.id before it is written"),
    ("fx_adjustments", "created_by"): ("users", "written beside the journal it books, whose posted_by holds users.id"),
    ("fx_rates", "created_by"): ("users", "the currencies route writes the caller's users.id"),
    ("fx_revaluations", "run_by"): ("users", "written beside the journal it books, whose posted_by holds users.id"),
    ("government_notices", "ca_approved_by"): ("users", "the notice approval writes the caller's users.id"),
    ("journal_entries", "rate_selected_by"): ("users", "beside posted_by, which holds users.id on every row read"),
    ("knowledge_article_versions", "changed_by"): ("users", "the knowledge base writes the caller's users.id"),
    ("knowledge_articles", "created_by"): ("users", "the knowledge base writes the caller's users.id"),
    ("party_credit_ledger", "created_by"): ("users", "written beside the journal it books, whose posted_by holds users.id"),
    ("purchase_bills", "rate_selected_by"): ("users", "copied onto journal_entries.rate_selected_by, beside posted_by (users.id)"),
    ("purchase_payments", "rate_selected_by"): ("users", "copied onto journal_entries.rate_selected_by, beside posted_by (users.id)"),
    ("receipts", "rate_selected_by"): ("users", "copied onto journal_entries.rate_selected_by, beside posted_by (users.id)"),
    ("reconciliation_findings", "resolved_by"): ("users", "the reconciliation route writes the caller's users.id"),
    ("reconciliation_runs", "triggered_by"): ("users", "the reconciliation route writes the caller's users.id"),
    ("related_party_loans", "created_by"): ("users", "the relationships route writes the caller's users.id"),
    ("task_recurring_configs", "assignee_id"): ("users", "checked to be a member by users.id, and copied into tasks.assigned_to, a key to users"),
    ("user_capacity", "user_id"): ("users", "checked against users.id before it is written, and read back as users.id by the workload screen"),
    ("user_capacity", "updated_by"): ("users", "the workload route writes the caller's users.id"),
}

#: (table, column) -> whose id it is. Columns that hold the sign-in id of a principal who is NOT a member of the firm: a portal contact,
#: an employee or a platform administrator. The kind is the sign-in id, but a guard that proved "a sign-in id" would pass a member's
#: there, so these are named and not traced.
OTHER_PRINCIPALS: dict[tuple[str, str], str] = {
    ("client_portal_users", "auth_user_id"): "the portal contact's sign-in id, compared with auth.uid() by the portal's own policy",
    ("clients", "portal_user_id"): "a portal contact's sign-in id, compared with auth.uid() by my_portal_client_ids",
    ("payroll_employees", "auth_user_id"): "the employee's sign-in id, compared with auth.uid() by my_employee_ids",
    ("platform_audit", "actor_auth_user_id"): "a platform administrator's sign-in id",
}

HOLDS: dict[tuple[str, str], str] = {**READ_FROM_ROWS, **{k: kind for k, (kind, _why) in DECIDED_FROM_CODE.items()}}

WRITES = {"insert", "update", "upsert"}
#: Names this code base gives the dict of the member acting. `approver` and `decider` (POST-A-377) are the approval engine's: every caller passes the
#: route's `current_user` as them.
PRINCIPALS = r"(?:current_user|actor|user|principal|caller|acting_user|me|approver|decider)"
AUTH_VALUE = re.compile(r"auth_user_id|auth_id\b")
USERS_VALUE = re.compile(rf"\b{PRINCIPALS}\b[^\n]*?(?:\.get\(\s*['\"]id['\"]\s*\)|\[\s*['\"]id['\"]\s*\])")

#: Writes whose value the scan cannot read AND cannot prove from the calls that supply it, as (file, function, table, column). A write
#: whose value is a PARAMETER is followed one hop to the calls of its function made through its module (see `traced`): when every such call
#: passes the kind the column holds, it is proven and not listed. What is left is a value that is a conditional or a call, a parameter
#: that is passed on again, or a function called through an object the scan cannot name (`self.repo.f(...)`). Not a claim that they are
#: right: the set of writes nobody has traced to the principal the value came from. Equality in both directions.
UNREAD: set[tuple[str, str, str, str]] = set()      # every write the scan can see is now proven by its chain (POST-A-361, 3-11-2026)


#: Mapped columns with NO direct dict-literal writer anywhere in the API as the scan reads it: their rows are written through a payload built
#: elsewhere (a repository or a helper) or by a path the scan does not follow. Listed so that the day a direct writer appears it is read,
#: and so that "twenty columns are mapped" is not read as "twenty are guarded". Equality in both directions.

#: For each NOT_SEEN column: the functions that BUILD the row's dict (a repository's `create(payload)` writes it, so no `.table(T).insert(...)` is
#: seen next to the key). Each is read for a dict literal carrying the column's key and the value is traced like any other: the proof of the
#: column is that every builder's value is the kind it holds. A builder that no longer has the key fails (the entry is stale).
#: A builder may carry the value under another key (a database function's parameter, `p_actor_id`): then it is named as the third element.
#: A builder is read for dict literals AND for `<name>["<key>"] = value` assignments.
BUILT_ELSEWHERE: dict[tuple[str, str], list[tuple[str, ...]]] = {
    ("time_entries", "user_id"): [("routers/time_tracking.py", "start_timer"), ("routers/time_tracking.py", "create_manual_entry")],
    ("year_end_notes", "created_by"): [("routers/year_end_notes.py", "generate_notes")],
    # POST-A-377: the columns decided from the code whose rows are built away from the write
    ("approval_requests", "requested_by"): [("services/approval_service.py", "create_request")],
    ("approval_requests", "decided_by"): [("services/approval_service.py", "approve"), ("services/approval_service.py", "reject"),
                                          ("services/approval_service.py", "cancel"), ("services/mfa_reset_service.py", "_close_the_others")],
    ("bank_transaction_splits", "created_by"): [("services/bank_split_service.py", "replace", "p_actor_id")],          # migration 256
    ("bank_transactions", "transfer_paired_by"): [("services/bank_transfer_service.py", "pair", "p_actor_id")],      # migration 258
    ("client_sales_invoices", "rate_selected_by"): [("routers/sales_invoices.py", "_create_invoice_core")],
    ("client_timeline_events", "actor_id"): [("services/timeline_service.py", "_row")],
    ("clients", "archived_by"): [("repositories/client_repository.py", "archive")],
    ("compliance_records", "preparer_id"): [("services/compliance_obligation_service.py", "generate_for_engagement"),
                                            ("services/compliance_obligation_service.py", "assign")],
    ("compliance_records", "reviewer_id"): [("services/compliance_obligation_service.py", "generate_for_engagement"),
                                            ("services/compliance_obligation_service.py", "assign")],
    ("compliance_records", "approver_id"): [("services/compliance_obligation_service.py", "generate_for_engagement"),
                                            ("services/compliance_obligation_service.py", "assign")],
    ("delivery_challan_returns", "created_by"): [("services/itc_04_service.py", "record_return")],                   # migration 585
    ("delivery_challan_returns", "retracted_by"): [("services/delivery_challan_writes.py", "retract_lot", "p_by")],   # migration 651
    ("health_overrides", "override_by"): [("routers/health.py", "create_override")],
    ("payroll_employees", "portal_invited_by"): [("services/employee_portal_service.py", "invite_employee")],
    ("purchase_bills", "rate_selected_by"): [("routers/purchase_bills.py", "_create_purchase_bill_core")],
    ("receipts", "rate_selected_by"): [("services/receipt_service.py", "create_foreign_receipt")],                  # migration 781: the row is the function's
    ("purchase_payments", "rate_selected_by"): [("services/purchase_payment_service.py", "_record_foreign_payment")],   # migration 784: the row is the function's
    ("related_party_loans", "created_by"): [("routers/relationships.py", "create_loan")],
    ("user_capacity", "updated_by"): [("routers/workload.py", "set_capacity")],
    ("year_end_exports", "created_by"): [("routers/year_end_exports.py", "_create_export_record")],
}

#: Columns whose row is a request body written whole (`repo.create({**body.model_dump(), ...})`), so no builder names the key: each writer is
#: proven by the member check it makes on the value before the row is written (`named_row_ownership.member_is_the_firms`, a lookup in `users`
#: by id and firm). (table, column) -> [(file, function, the check that must stay in it)].
TYPED_AND_CHECKED: dict[tuple[str, str], list[tuple[str, str, str]]] = {
    ("fee_engagements", "assigned_to"): [("routers/engagements.py", "create_engagement", "member_is_the_firms(_db, firm_id, body.assigned_to)"),
                                         ("routers/engagements.py", "update_engagement", "member_is_the_firms(_db, firm_id, updates.get('assigned_to'))")],
    ("fee_engagements", "reviewer_id"): [("routers/engagements.py", "create_engagement", "member_is_the_firms(_db, firm_id, body.reviewer_id)"),
                                         ("routers/engagements.py", "update_engagement", "member_is_the_firms(_db, firm_id, updates.get('reviewer_id'))")],
    ("fee_engagements", "partner_id"): [("routers/engagements.py", "create_engagement", "member_is_the_firms(_db, firm_id, body.partner_id)"),
                                        ("routers/engagements.py", "update_engagement", "member_is_the_firms(_db, firm_id, updates.get('partner_id'))")],
}

#: Mapped columns with no direct writer the scan can see: proven through their builders, or through the check on the typed body.
NOT_SEEN: set[tuple[str, str]] = set(BUILT_ELSEWHERE) | set(TYPED_AND_CHECKED)

#: A value that is another mapped column READ OFF ITS ROW carries that column's kind: an obligation generated for an engagement is staffed by
#: the engagement's own people. (file, function, the value as written) -> (table, column) it is read from.
READ_OFF_A_ROW: dict[tuple[str, str, str], tuple[str, str]] = {
    ("services/compliance_obligation_service.py", "generate_for_engagement", "engagement.get('assigned_to')"): ("fee_engagements", "assigned_to"),
    ("services/compliance_obligation_service.py", "generate_for_engagement", "engagement.get('reviewer_id')"): ("fee_engagements", "reviewer_id"),
    ("services/compliance_obligation_service.py", "generate_for_engagement", "engagement.get('partner_id')"): ("fee_engagements", "partner_id"),
}

#: (table, column) -> why. Person columns with no key that NOTHING writes a person into yet (POST-A-377: no writer, a writer nothing calls,
#: or one that only ever writes a constant None). Which id each will hold cannot be read from the code, so it is not decided here: the
#: guard below fails the day something supplies a person to one of them, and that writer's author maps the column. The pg test holds
#: the three lists together equal to every such column the migrations build.
NO_PERSON_WRITTEN_YET: set[tuple[str, str]] = {
    ("ai_actions", "executed_by"), ("ai_recommendations", "acted_by"), ("client_firm_customer_links", "created_by"),
    ("client_health_overrides", "created_by"), ("client_lifecycle_events", "created_by"), ("client_timeline_events", "deleted_by"),
    ("cross_client_matches", "reviewed_by"), ("debit_notes", "created_by"), ("demo_filings", "simulated_by"),
    ("engagement_letters", "created_by"), ("entities", "created_by"), ("entity_relationships", "created_by"),
    ("fee_invoices", "deleted_by"), ("firm_hsn_library", "created_by"), ("firm_hsn_library", "updated_by"),
    ("firm_hsn_rate_history", "created_by"), ("lead_activities", "created_by"), ("leads", "created_by"),
    ("notes_to_accounts", "created_by"), ("notes_to_accounts", "locked_by"), ("onboarding_workflows", "assigned_to"),
    ("onboarding_workflows", "created_by"), ("pending_invites", "invited_by"), ("platform_admins", "created_by"),
    ("proposals", "created_by"), ("purchase_credit_notes", "created_by"), ("renewals", "created_by"),
    ("workflow_approvals", "approver_id"), ("workflow_executions", "actor_id"), ("year_end_adjustments", "reviewed_by"),
    ("year_end_checklists", "completed_by"), ("year_end_reviews", "actor_id"), ("year_end_reviews", "reviewed_by"),
}

#: A value a person TYPED (a route's path parameter, a body field) that is checked, before anything is written, to be a member of the caller's
#: firm by a lookup in `users` by id (`_get_member` -> `user_repo.find_by_id(id, firm_id=...)`, `named_row_ownership.member_is_the_firms`, or the
#: writer's own lookup): such a value is a `users.id` and nothing else, whoever typed it. (file, function, the value as written) -> the text of the
#: check that must stay in the function, as `ast.unparse` spells it. Not a claim made from memory: `test_a_checked_path_parameter_...` reads both.
CHECKED_AS_A_MEMBER: dict[tuple[str, str, str], str] = {
    ("routers/identity.py", "suspend_user", "user_id"): "_get_member(user_id",
    ("routers/identity.py", "force_logout", "user_id"): "_get_member(user_id",
    ("routers/task_recurring.py", "create_recurring", "body.assignee_id"): "member_is_the_firms(db, firm_id, body.assignee_id)",
    ("routers/compliance_ops.py", "assign_obligation", "body.preparer_id"): "member_is_the_firms(_db, current_user['firm_id'], body.preparer_id)",
    ("routers/compliance_ops.py", "assign_obligation", "body.reviewer_id"): "member_is_the_firms(_db, current_user['firm_id'], body.reviewer_id)",
    ("routers/compliance_ops.py", "assign_obligation", "body.approver_id"): "member_is_the_firms(_db, current_user['firm_id'], body.approver_id)",
    ("repositories/capacity_repository.py", "upsert", "user_id"): ".table('users').select('id').eq('id', user_id).eq('firm_id', firm_id)",
}


#: Columns that are a key to `users(id)` and are READ off a row to become the actor of a later write: `<row>.get("trusted_by")` is an internal id
#: because the database refuses anything else there. The key is the schema's (migration 322), not a guess.
KEYED_TO_USERS_WHEN_READ = {"trusted_by"}
KEYED_READ = re.compile(r"\.get\(\s*['\"](" + "|".join(sorted(KEYED_TO_USERS_WHEN_READ)) + r")['\"]")


def _none_branch_dropped(value: ast.expr) -> ast.expr:
    """`x if cond else None` (either way round) is `x`: the None branch is a deliberate empty, not a second kind of value."""
    if isinstance(value, ast.IfExp):
        if isinstance(value.orelse, ast.Constant) and value.orelse.value is None:
            return value.body
        if isinstance(value.body, ast.Constant) and value.body.value is None:
            return value.orelse
    return value


def kind_of(value: ast.expr) -> str:
    """'auth', 'users', 'none' (a constant None) or 'unread'."""
    value = _none_branch_dropped(value)
    if isinstance(value, ast.Constant) and value.value is None:
        return "none"
    text = ast.unparse(value)
    if KEYED_READ.search(text) and not AUTH_VALUE.search(text):
        return "users"
    if AUTH_VALUE.search(text):
        return "auth"
    if USERS_VALUE.search(text):
        return "users"
    return "unread"


def _function_of(node, parents) -> ast.AST | None:
    while node is not None and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        node = parents.get(node)
    return node


def _function_chain(node, parents) -> tuple[ast.AST, ...]:
    """The functions a node sits in, innermost first: a helper nested in a function reads the outer function's names."""
    out = []
    node = _function_of(node, parents)
    while node is not None:
        out.append(node)
        node = _function_of(parents.get(node), parents)
    return tuple(out)


def _payload_dicts(payload: ast.expr, fn: ast.AST | None):
    """(dict literals, [(column, value) set by subscript assignment]) for a write's payload."""
    if isinstance(payload, ast.Dict):
        return [payload], []
    if isinstance(payload, ast.List):
        return [e for e in payload.elts if isinstance(e, ast.Dict)], []
    if isinstance(payload, ast.ListComp) and isinstance(payload.elt, ast.Dict):
        return [payload.elt], []
    if isinstance(payload, ast.Name) and fn is not None:
        dicts, subs = [], []
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("append", "extend", "insert")
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == payload.id):
                for arg in n.args:                    # rows.append({...}) / rows.extend([{...}, ...]) / rows.extend({...} for ...)
                    d, _ = _payload_dicts(arg, None)
                    dicts.extend(d)
                    if isinstance(arg, ast.GeneratorExp) and isinstance(arg.elt, ast.Dict):
                        dicts.append(arg.elt)
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id == payload.id:
                        d, _ = _payload_dicts(n.value, None)
                        dicts.extend(d)
                    if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == payload.id
                            and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str)):
                        subs.append((t.slice.value, n.value))
        return dicts, subs
    return [], []


#: Values that are a column's OWN earlier value, written back: (file, function, the value as written) -> why. DECLARED, not recognised by
#: shape: `x["matched_by"]` is a restore only when `x` is the row's earlier copy, and the same shape on a request body or on a dict built in the
#: same function is a value somebody chose (an independent read found both passing as restores when this was a syntactic rule).
RESTORES: dict[tuple[str, str, str], str] = {
    ("services/bank_entry_service.py", "_unapply", "before['matched_by']"):
        "a pass that fails puts the coding back as it was before the draft was applied (`before` is read off the same row)",
    ("services/compliance_obligation_service.py", "assign", "rec.get('preparer_id')"): "the audit row's old_data: what the obligation held",
    ("services/compliance_obligation_service.py", "assign", "rec.get('reviewer_id')"): "the audit row's old_data: what the obligation held",
    ("services/compliance_obligation_service.py", "assign", "rec.get('approver_id')"): "the audit row's old_data: what the obligation held",
}


def restores_its_own_column(value: ast.expr, column: str, rel: str, function: str) -> bool:
    """True for a value declared in RESTORES: the column's own earlier value, put back or copied into an audit row's `old_data`. It is what a
    proven writer put there, so it is not a second kind of value. The declared text must still read the column's own name."""
    text = ast.unparse(_none_branch_dropped(value))
    return (rel, function, text) in RESTORES and f"'{column}'" in text


def writes_in(source: str, relpath: str, columns=None) -> list[tuple[str, str, str, str, str, int]]:
    """(file, function, table, column, kind, line) for every mapped column written by a direct insert, update or upsert. `columns` is the
    set of (table, column) to look for (the map by default); kind 'restore' is a column written back with its own earlier value."""
    columns = HOLDS if columns is None else columns
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    out, seen = [], set()
    for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
        chain = chain_of(call)
        methods = [m for m, _ in chain]
        if "table" not in methods or not (WRITES & set(methods)):
            continue
        table_call = next(c for m, c in chain if m == "table")
        write_call = next(c for m, c in chain if m in WRITES)
        if not (table_call.args and isinstance(table_call.args[0], ast.Constant) and isinstance(table_call.args[0].value, str)):
            continue
        table = table_call.args[0].value
        if id(write_call) in seen or not write_call.args:
            continue
        seen.add(id(write_call))
        fn = _function_of(write_call, parents)
        dicts, subs = _payload_dicts(write_call.args[0], fn)
        pairs = [(k.value, v) for d in dicts for k, v in zip(d.keys, d.values, strict=True) if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        for column, value in pairs + subs:
            if (table, column) in columns:
                key = (relpath, fn.name if fn is not None else "<module>", table, column)
                kind = "restore" if restores_its_own_column(value, column, relpath, key[1]) else kind_of(value)
                out.append((*key, kind, value.lineno))
                PARAM_OF[key] = _parameter(value, fn)
                VALUE_OF.setdefault(key, []).append((value, _function_chain(write_call, parents)))
    return out


#: (file, function, table, column) -> the parameter name the value is, when it is a bare name that is a parameter of its function.
PARAM_OF: dict[tuple[str, str, str, str], tuple[str, int] | None] = {}
#: (file, function, table, column) -> [(the value written, the functions it sits in)]: what the trace starts from.
VALUE_OF: dict[tuple[str, str, str, str], list] = {}


def _parameter(value: ast.expr, fn: ast.AST | None):
    """(name, position) when `value` is a bare name that is one of `fn`'s parameters, else None."""
    value = _none_branch_dropped(value)
    if not (isinstance(value, ast.Name) and isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))):
        return None
    names = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
    kwonly = [a.arg for a in fn.args.kwonlyargs]
    if value.id in names:
        return value.id, names.index(value.id) - (1 if names and names[0] in ("self", "cls") else 0)
    if value.id in kwonly:
        return value.id, -1
    return None


def every_write() -> list[tuple[str, str, str, str, str, int]]:
    found = []
    for d in SCAN_DIRS:
        for path in sorted((API / d).rglob("*.py")):
            try:
                found.extend(writes_in(path.read_text(encoding="utf-8"), path.relative_to(API).as_posix()))
            except (SyntaxError, UnicodeDecodeError):
                continue
    return found


WRITES_FOUND = every_write()


def _aliases(tree: ast.Module) -> dict[str, str]:
    """name bound in this file -> the module basename it stands for (`import services.x as svc`, `from services import x as svc`)."""
    out: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                out[a.asname or a.name.split(".")[0]] = a.name.split(".")[-1]
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                out[a.asname or a.name] = a.name                     # `from services import module` binds the module; `from module import f` binds f
    return out


def _sources_on_disk() -> dict[str, str]:
    out = {}
    for d in SCAN_DIRS:
        for path in sorted((API / d).rglob("*.py")):
            try:
                out[path.relative_to(API).as_posix()] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
    return out


def _call_sites(sources: dict[str, str] | None = None) -> dict[str, list[tuple[str, str, ast.Call, tuple]]]:
    """function name -> [(file, module the call is made through or '', call)]. A bare-name call is made through the file's own module
    unless the name was imported from another (`from module import f`), in which case it is made through that module; `x.f(...)` is made
    through whatever module the alias `x` stands for, and through nothing the scan can name (a parameter, `self`) otherwise."""
    sites: dict[str, list[tuple[str, str, ast.Call, tuple]]] = {}
    sources = sources if sources is not None else _sources_on_disk()
    stems = {Path(r).stem for r in sources}
    for rel, text in sources.items():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        own, aliases = Path(rel).stem, _aliases(tree)
        defined_here = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        imported_from = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module:
                for a in n.names:
                    imported_from[a.asname or a.name] = (n.module.split(".")[-1], a.name)
        for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
            enclosing = _function_chain(call, parents)
            if isinstance(call.func, ast.Name):
                module, real = imported_from.get(call.func.id, (own, call.func.id))
                sites.setdefault(real, []).append((rel, module, call, enclosing))
            elif isinstance(call.func, ast.Attribute):
                base = call.func.value
                module = ""
                if isinstance(base, ast.Name) and base.id in ("self", "cls") and call.func.attr in defined_here:
                    module = own                      # `self._log(...)` inside the class that defines `_log` is made through this file (POST-A-377)
                elif isinstance(base, ast.Name):
                    module = aliases.get(base.id, "")
                    if module not in stems and base.id in imported_from:
                        # `from repositories.dsc_repository import dsc_repo`: `dsc_repo.f(...)` is made through the module that holds the instance.
                        module = imported_from[base.id][0]
                sites.setdefault(call.func.attr, []).append((rel, module, call, enclosing))
    return sites


def supplied_kinds(function: str, module: str, parameter: tuple[str, int], sites=None) -> list[tuple[str, int, str]]:
    """(file, line, kind) of what each call of `module.function` passes for `parameter` (one hop; a name passed on again is `unread`).
    Only calls made THROUGH `module` count: `create` is the name of a dozen unrelated functions."""
    name, position = parameter
    sites = sites if sites is not None else _call_sites()
    out = []
    for rel, through, call, _enclosing in sites.get(function, []):
        if through != module:
            continue
        passed = next((kw.value for kw in call.keywords if kw.arg == name), None)
        if passed is None and 0 <= position < len(call.args):
            passed = call.args[position]
        if passed is None:
            continue                                  # the call leaves it to the default
        out.append((rel, call.lineno, kind_of(passed)))
    return out


def _definition_counts(sources: dict[str, str] | None = None) -> dict[str, int]:
    """function or method name -> how many times it is defined in the scanned tree."""
    counts: dict[str, int] = {}
    for text in (sources if sources is not None else _sources_on_disk()).values():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                counts[n.name] = counts.get(n.name, 0) + 1
    return counts


MAX_HOPS = 12


def origins(function: str, file: str, parameter: tuple[str, int], sites, defined, *, _seen=frozenset(), _depth=0) -> list[tuple[str, int, str]]:
    """(file, line, kind) of every ORIGIN of the value a function receives for `parameter`: its callers' arguments, and where such an
    argument is itself a parameter of the calling function (or a name assigned from one) the callers of THAT, up to `MAX_HOPS` hops.

    A call counts when it is made through the function's module, or through something the scan cannot name (`_loc().f(...)`,
    `self.repo.f(...)`) and the name is defined ONCE in the whole tree (so the call can only be this function). An origin is `auth`,
    `users`, `none` (a constant None, or a conditional's empty branch), or `unread`: a value that is a call, a conditional, a name no
    assignment explains, or a parameter nothing calls. THE CHAIN IS THE PROOF: a column is proven only when every origin is its kind."""
    name, position = parameter
    out: list[tuple[str, int, str]] = []
    seen = _seen | {(file, function)}
    for rel, through, call, enclosing in sites.get(function, []):
        if not (through == Path(file).stem or (through == "" and defined.get(function) == 1)
                or _on_the_declared_factory(file, function, rel, call)):
            continue
        passed = next((kw.value for kw in call.keywords if kw.arg == name), None)
        if passed is None and 0 <= position < len(call.args):
            passed = call.args[position]
        if passed is None:
            star = [kw.value for kw in call.keywords if kw.arg is None]
            if star:                                  # `f(**fields)`: the value is whatever `fields` carries under this name
                out.extend(_through_double_star(star, name, rel, call.lineno, enclosing, sites, defined, seen, _depth + 1))
            continue                                  # otherwise the call leaves it to the default
        out.extend(_origin_of(passed, rel, call.lineno, enclosing, sites, defined, seen, _depth + 1))
    return out


def _through_double_star(star, name, rel, line, enclosing, sites, defined, seen, depth) -> list[tuple[str, int, str]]:
    """`f(**fields)`. Where `fields` is the calling function's own `**fields`, the value is what ITS callers pass under `name` (an independent
    read found `record_event(**fields)` -> `_row(**fields)` was never followed). Anything else is unread."""
    out: list[tuple[str, int, str]] = []
    fn = enclosing[0] if enclosing else None
    for value in star:
        if (isinstance(value, ast.Name) and fn is not None and fn.args.kwarg is not None and fn.args.kwarg.arg == value.id
                and depth <= MAX_HOPS and (rel, fn.name) not in seen):
            out.extend(origins(fn.name, rel, (name, -1), sites, defined, _seen=seen, _depth=depth))
        elif isinstance(value, ast.Name) and fn is not None and depth <= MAX_HOPS:
            # `_ccy = self._currency_kwargs(...)` then `f(**_ccy)`: what the dict carries under this name, read like an attribute
            for v, where in [b for f_ in enclosing for b in _built_with(value.id, f_, name, rel)] or [(None, fn)]:
                out.extend([(rel, line, "unread")] if v is None else
                           _origin_of(v, rel, line, (where, *enclosing) if where not in enclosing else enclosing, sites, defined, seen,
                                      depth + 1))
        else:
            out.append((rel, line, "unread"))
    return out


#: Calls made on the RESULT of a factory function (`_repo().create_conversation(...)`) cannot be named by the resolver, and the method's name is
#: shared (`create_conversation` is also a route), so the name alone does not identify it. (the function's file, its name) -> (the file that
#: calls it, the factory it calls it on). The call must really be `<factory>().<name>(...)` in that file or it does not count.
CALLED_ON_A_FACTORY: dict[tuple[str, str], tuple[str, str]] = {
    ("repositories/ai_copilot_repository.py", "create_conversation"): ("routers/ai_copilot_v2.py", "_repo"),
    ("repositories/workflow_repository.py", "create_template"): ("routers/workflow_builder.py", "_repo"),
    ("repositories/workflow_repository.py", "update_template"): ("routers/workflow_builder.py", "_repo"),
    ("repositories/workflow_repository.py", "create_schedule"): ("routers/workflow_builder.py", "_repo"),
    ("repositories/workflow_repository.py", "resolve_failure"): ("routers/workflow_builder.py", "_repo"),
    ("repositories/memory_repository.py", "acknowledge_trigger"): ("routers/memory_intelligence.py", "_get_repo"),
}


def _on_the_declared_factory(file: str, function: str, rel: str, call: ast.Call) -> bool:
    declared = CALLED_ON_A_FACTORY.get((file, function))
    if declared is None or rel != declared[0] or not isinstance(call.func, ast.Attribute):
        return False
    base = call.func.value
    return isinstance(base, ast.Call) and getattr(base.func, "id", None) == declared[1]


def _module_functions(rel: str) -> dict[str, ast.AST]:
    """The functions and methods defined ONCE in a scanned file, by name (parsed once): a name defined twice in the file is left out, so a
    helper is never read from the wrong definition."""
    if rel not in _MODULE_FUNCTIONS:
        tree = ast.parse((globals().get("_SOURCES") or _sources_on_disk()).get(rel, ""))
        fns = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        names = [n.name for n in fns]
        _MODULE_FUNCTIONS[rel] = {n.name: n for n in fns if names.count(n.name) == 1}
    return _MODULE_FUNCTIONS[rel]


_MODULE_FUNCTIONS: dict[str, dict[str, ast.AST]] = {}


#: Functions from another module whose result carries a known kind in the named field: (function name) -> (its file, the text that says so,
#: the kind). A test reads the file, so the claim cannot go stale. `identity_currency` is the inert INR currency every INR document takes and
#: names nobody; `document_currency_from_row` rebuilds a document's currency from its stored row, so it carries that row's own
#: `rate_selected_by`, which holds the internal id on every document table that has one (the test checks the map says so).
CARRIED_BY_A_FUNCTION: dict[str, tuple[str, str, str]] = {
    "identity_currency": ("domain/currency/document_currency.py", "rate_selected_by=None", "none"),
    "document_currency_from_row": ("domain/currency/document_currency.py", "rate_selected_by=row.get('rate_selected_by')", "users"),
}

_NOBODY = ast.Constant(None)
#: A value whose kind is known without a principal in sight (what CARRIED_BY_A_FUNCTION says): read by `kind_of` like any other.
_KIND_MARKER = {"users": ast.parse("current_user.get('id')", mode="eval").body,
                "auth": ast.parse("current_user.get('auth_user_id')", mode="eval").body}


def _from_a_call(call: ast.Call, attr: str, fn, rel: str) -> list:
    """What a call's result carries in `attr`: the keyword it is passed, nobody for a BUILDS_NOBODY function, or every return of a helper in
    the same file followed the same way. (None, fn) is a value the scan cannot read."""
    passed = [(kw.value, fn) for kw in call.keywords if kw.arg == attr]
    if passed:
        return passed
    func = call.func
    callee = (func.id if isinstance(func, ast.Name) else
              func.attr if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in ("self", "cls") else "")
    if callee in CARRIED_BY_A_FUNCTION:
        kind = CARRIED_BY_A_FUNCTION[callee][2]
        return [(_NOBODY if kind == "none" else _KIND_MARKER[kind], fn)]
    helper = _module_functions(rel).get(callee) if rel and callee else None
    if helper is None:
        return [(None, fn)]
    out = []
    for r in [r for r in ast.walk(helper) if isinstance(r, ast.Return)]:     # EVERY return is read: one unread return is an unread value
        if isinstance(r.value, ast.Call):
            out.extend(_from_a_call(r.value, attr, helper, rel))
        elif isinstance(r.value, ast.Dict):            # `return {...}`: the key's value, or nobody where the key is absent
            got = [(v, helper) for k, v in zip(r.value.keys, r.value.values, strict=True) if isinstance(k, ast.Constant) and k.value == attr]
            out.extend(got or [(_NOBODY, helper)])
        else:
            out.append((None, helper))
    return out or [(None, helper)]


def _built_with(name: str, fn, attr: str, rel: str = ""):
    """(value, the function it sits in) for each value `name.<attr>` (or `name["<attr>"]`) can have in `fn`: `name` assigned a dict literal
    carrying the key, a call that passes the keyword (`dc = resolve(..., rate_selected_by=x)`; `dc.rate_selected_by` is then `x`), or a call to
    a helper in the same file whose every return is such a call (`dc = _bill_currency(...)`, which returns `resolve(..., rate_selected_by=x)`);
    and every later `name["<attr>"] = v` too. ANY assignment the scan cannot read makes the answer unread, (None, fn): a value proven from
    one assignment while another is unread would be a false proof (an independent read made exactly that pass)."""
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            if isinstance(n.value, ast.Dict):
                out.extend((v, fn) for k, v in zip(n.value.keys, n.value.values, strict=True)
                           if isinstance(k, ast.Constant) and k.value == attr)
            elif isinstance(n.value, ast.Call):
                out.extend(_from_a_call(n.value, attr, fn, rel))
            else:
                out.append((None, fn))
        if isinstance(n, ast.Assign):
            out.extend((n.value, fn) for t in n.targets
                       if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == name
                       and isinstance(t.slice, ast.Constant) and t.slice.value == attr)
    return out


def _origin_of(value, rel, line, chain, sites, defined, seen, depth) -> list[tuple[str, int, str]]:
    value = _none_branch_dropped(value)
    if isinstance(value, ast.IfExp):                  # two real branches: both are origins
        return (_origin_of(value.body, rel, line, chain, sites, defined, seen, depth)
                + _origin_of(value.orelse, rel, line, chain, sites, defined, seen, depth))
    if chain:
        text = ast.unparse(value)
        if (rel, chain[0].name, text) in CHECKED_AS_A_MEMBER:
            return [(rel, line, "users")]             # typed by a person and proven a member of this firm by a lookup in `users`
        if (rel, chain[0].name, text) in READ_OFF_A_ROW:
            return [(rel, line, HOLDS[READ_OFF_A_ROW[(rel, chain[0].name, text)]])]
        if (isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name)) or (
                isinstance(value, ast.Subscript) and isinstance(value.value, ast.Name)
                and isinstance(value.slice, ast.Constant) and isinstance(value.slice.value, str)):
            attr = value.attr if isinstance(value, ast.Attribute) else value.slice.value
            built = [b for fn in chain for b in _built_with(value.value.id, fn, attr, rel)]
            if built and depth <= MAX_HOPS:
                return [o for v, where in built
                        for o in ([(rel, line, "unread")] if v is None else
                                  _origin_of(v, rel, line, (where, *chain) if where not in chain else chain, sites, defined, seen, depth + 1))]
    kind = kind_of(value)
    if kind != "unread" or not isinstance(value, ast.Name) or depth > MAX_HOPS:
        return [(rel, line, kind)]
    for fn in chain:                                  # innermost function first: a nested helper reads its outer function's names
        param = _parameter(value, fn)
        if param is not None and (rel, fn.name, param[0]) in CHECKED_AS_A_MEMBER:
            return [(rel, line, "users")]             # a parameter proven to be a member of this firm, by a lookup in `users`
        if param is not None:                         # passed on again: the callers of the function that takes it
            if (rel, fn.name) in seen:
                return [(rel, line, "unread")]
            found = origins(fn.name, rel, param, sites, defined, _seen=seen, _depth=depth)
            return found or [(rel, line, "unread")]   # nothing calls it: not proven
        assigned = []                                 # a local name: what every assignment to it in this function makes it
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == value.id for t in n.targets):
                assigned.extend(_origin_of(n.value, rel, n.lineno, chain, sites, defined, seen, depth + 1))
        if assigned:
            return assigned
    return [(rel, line, "unread")]


def traced() -> tuple[dict[tuple[str, str, str, str], list], dict[tuple[str, str, str, str], str]]:
    """For every unread write whose value is a parameter: what its callers pass. -> (callers by write, verdict by write).

    verdict 'ok' when there is at least one caller and every caller passes the kind the column holds (or None); 'wrong' when one passes
    the other kind; 'open' when a caller passes something this scan cannot read, or nothing calls it."""
    sites, defined = _GRAPH
    callers, verdict = {}, {}
    for f, fn, t, c, k, line in WRITES_FOUND:
        key = (f, fn, t, c)
        if k != "unread" or key in callers:
            continue
        # every value this function writes into the column, followed from where it is written: a parameter to its callers, a local name to
        # its assignments, a body field to the member check made on it, an attribute to the call that built the object
        passed = [o for value, chain in VALUE_OF.get(key, [])
                  if kind_of(value) == "unread" and not restores_its_own_column(value, c, f, fn)
                  for o in _origin_of(value, f, line, chain, sites, defined, frozenset(), 0)]
        callers[key] = passed
        kinds = {kind for _f, _line, kind in passed}
        want = HOLDS[(t, c)]
        verdict[key] = ("wrong" if kinds & ({"auth", "users"} - {want}) else
                        "ok" if passed and kinds <= {want, "none"} else "open")
    return callers, verdict


_SOURCES = _sources_on_disk()
#: The call graph is built ONCE: it is the slow part (about fourteen seconds), and every proof below reads the same tree.
_GRAPH = (_call_sites(_SOURCES), _definition_counts(_SOURCES))
CALLERS, VERDICT = traced()


def built_elsewhere_origins(table: str, column: str, sources: dict[str, str] | None = None) -> list[tuple[str, int, str]]:
    """(file, line, kind) of the value of every dict literal carrying `column` as a key, in each function named for that column."""
    sites, defined = _GRAPH if sources is None else (_call_sites(sources), _definition_counts(sources))
    sources = sources if sources is not None else _SOURCES
    out: list[tuple[str, int, str]] = []
    for rel, fn_name, *named in BUILT_ELSEWHERE[(table, column)]:
        key = named[0] if named else column
        tree = ast.parse(sources[rel])
        parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        built = False
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name]:
            chain = _function_chain(fn, parents)
            values = [v for d in [n for n in ast.walk(fn) if isinstance(n, ast.Dict)]
                      for k, v in zip(d.keys, d.values, strict=True) if isinstance(k, ast.Constant) and k.value == key]
            values += [n.value for n in ast.walk(fn) if isinstance(n, ast.Assign) for t in n.targets
                       if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value == key]
            for v in values:
                built = True
                if not restores_its_own_column(v, column, rel, fn_name):
                    out.extend(_origin_of(v, rel, v.lineno, chain, sites, defined, frozenset(), 0))
        assert built, f"{rel}::{fn_name} no longer builds a row with the key {key!r}: update BUILT_ELSEWHERE"
    return out


def test_the_scan_finds_the_writers_it_was_written_for():
    tables = {t for _f, _fn, t, _c, _k, _l in WRITES_FOUND}
    assert len(WRITES_FOUND) >= 20, WRITES_FOUND
    assert len(tables) >= 12, sorted(tables)


def test_no_direct_write_puts_the_other_kind_of_id_in_a_mapped_column():
    wrong = [(f, fn, t, c, HOLDS[(t, c)], k, line) for f, fn, t, c, k, line in WRITES_FOUND
             if k in ("auth", "users") and k != HOLDS[(t, c)]]
    assert not wrong, ("a person column is written with the other kind of id (file, function, table, column, it holds, written, line):\n  "
                       + "\n  ".join(map(str, wrong)))


def test_no_call_supplies_the_other_kind_of_id_to_a_writer_that_takes_it_as_a_parameter():
    """The opening-documents screen passed `current_user.get("id")` to the writer of `client_sales_invoices.created_by`, which holds the
    AUTH id on every invoice (5,664 of 5,664 on production): found by this trace, fixed in the same change."""
    wrong = {key: [c for c in CALLERS[key] if c[2] in ("auth", "users") and c[2] != HOLDS[(key[2], key[3])]]
             for key, v in VERDICT.items() if v == "wrong"}
    assert not wrong, f"a call passes the other kind of id for a person column: {wrong}"


def test_what_the_scan_cannot_read_or_prove_is_exactly_the_listed_set():
    open_ = {key for key, v in VERDICT.items() if v == "open"}
    assert open_ == UNREAD, (
        f"writes of a mapped column whose value cannot be read or proven and are not listed: {sorted(open_ - UNREAD)}; "
        f"listed but now proven or gone (delete them): {sorted(UNREAD - open_)}")


def test_the_trace_proves_the_writers_it_can():
    """A floor so a tracer that quietly stops matching cannot turn every proof into 'open' and pass with a longer list."""
    proven = {key for key, v in VERDICT.items() if v == "ok"}
    assert len(proven) >= 12, sorted(proven)
    assert ("services/journal_posting_service.py", "post_draft", "journal_entries", "posted_by") in proven
    # the posting kernel is proven through its WHOLE caller graph, and the chain is long: dozens of origins, every one the internal id
    kernel = ("services/phase2_journal_service.py", "_create_journal", "journal_entries", "posted_by")
    assert kernel in proven and sum(kind == "users" for _f, _l, kind in CALLERS[kernel]) >= 40, CALLERS.get(kernel)
    assert not [o for o in CALLERS[kernel] if o[2] == "auth"], "a posting is credited to the sign-in id"


def test_every_column_with_no_direct_writer_is_proven_through_the_functions_that_build_its_row():
    assert not set(BUILT_ELSEWHERE) & set(TYPED_AND_CHECKED)
    for (table, column) in sorted(BUILT_ELSEWHERE):
        got = built_elsewhere_origins(table, column)
        assert got, (table, column)
        want = HOLDS[(table, column)]
        bad = [g for g in got if g[2] not in (want, "none")]
        assert not bad, f"{table}.{column} holds {want} but its row is built with: {bad}"


def _function_text(rel: str, fn_name: str) -> str:
    tree = ast.parse((API / rel).read_text(encoding="utf-8"))
    return ast.unparse(next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name))


def test_a_checked_path_parameter_is_still_checked_by_a_lookup_in_users():
    """A member id a person typed is a `users.id` because the member is looked up first, in this firm: by `_get_member`, by
    `named_row_ownership.member_is_the_firms`, or by the writer's own lookup. Each check must still be in its function, and each lookup must
    still be a lookup in `users` by id and firm."""
    for (rel, fn_name, _value), check in CHECKED_AS_A_MEMBER.items():
        assert check in _function_text(rel, fn_name), f"{rel}::{fn_name} no longer calls {check!r}: the typed value is not proven"
    for (_t, _c), checks in TYPED_AND_CHECKED.items():
        for rel, fn_name, check in checks:
            assert check in _function_text(rel, fn_name), f"{rel}::{fn_name} no longer calls {check!r}: the typed column is not proven"
    getter = _function_text("routers/identity.py", "_get_member")
    assert "user_repo.find_by_id(" in getter and "firm_id" in getter, "_get_member no longer looks the member up in users, in the firm"
    member = _function_text("services/named_row_ownership.py", "member_is_the_firms")
    assert ".table('users')" in member and ".eq('id', named)" in member and ".eq('firm_id', firm_id)" in member, (
        "member_is_the_firms no longer looks the member up in users by id and firm")


def test_a_column_read_off_a_row_names_a_mapped_column_and_is_still_read_there():
    for (rel, fn_name, value), (table, column) in READ_OFF_A_ROW.items():
        assert (table, column) in HOLDS, (table, column)
        assert value in _function_text(rel, fn_name), f"{rel}::{fn_name} no longer reads {value}"


def test_the_columns_with_no_direct_writer_the_scan_can_see_are_exactly_the_listed_ones():
    seen = {(t, c) for _f, _fn, t, c, _k, _l in WRITES_FOUND}
    assert set(HOLDS) - seen == NOT_SEEN, (
        f"mapped columns a direct writer was found for (delete from NOT_SEEN): {sorted(NOT_SEEN & seen)}; "
        f"mapped columns nothing is seen to write (add): {sorted(set(HOLDS) - seen - NOT_SEEN)}")


def test_the_map_names_the_twenty_columns_that_were_read():
    assert len(READ_FROM_ROWS) == 20
    assert sum(v == "auth" for v in READ_FROM_ROWS.values()) == 11 and sum(v == "users" for v in READ_FROM_ROWS.values()) == 9


def test_every_column_decided_from_the_code_says_what_decided_it_and_no_column_is_in_two_lists():
    assert len(DECIDED_FROM_CODE) == 63, len(DECIDED_FROM_CODE)
    for key, (kind, why) in DECIDED_FROM_CODE.items():
        assert kind in ("auth", "users") and len(why) > 20, key
    lists = [set(READ_FROM_ROWS), set(DECIDED_FROM_CODE), set(OTHER_PRINCIPALS), NO_PERSON_WRITTEN_YET]
    for i, a in enumerate(lists):
        for b in lists[i + 1:]:
            assert not a & b, sorted(a & b)
    assert len(NO_PERSON_WRITTEN_YET) == 33 and len(OTHER_PRINCIPALS) == 4


def _supplies(call: ast.Call, name: str, position: int) -> bool:
    """Whether a call passes anything for a parameter: by name, by position, or through `**` (which may carry it)."""
    return (any(kw.arg == name or kw.arg is None for kw in call.keywords)
            or (0 <= position < len(call.args)) or any(isinstance(a, ast.Starred) for a in call.args))


def persons_written_into(columns, sources=None) -> list:
    """(file, function, table, column, origin) for every person written into one of `columns`, CONSERVATIVELY: a value the writer computes is
    traced like any other; a value that is a parameter of the writer is looked for in EVERY call of a function of that name anywhere in the
    tree, resolved or not. No call supplying it means nobody is written; a supplying call the scan cannot pin to this writer is 'unread',
    never 'nobody' (an independent read showed `origins() == []` also meant 'the calls could not be resolved')."""
    sources = sources if sources is not None else _SOURCES
    sites, defined = _GRAPH if sources is _SOURCES else (_call_sites(sources), _definition_counts(sources))
    if sources is not _SOURCES:
        for key in [k for k in VALUE_OF if k[0] in sources]:
            del VALUE_OF[key]                          # a synthetic tree is traced on its own
    found = []
    for rel, text in sources.items():
        try:
            found.extend(writes_in(text, rel, columns=columns))
        except SyntaxError:
            continue
    out = []
    for f, fn, t, c, kind, line in found:
        if kind in ("none", "restore"):
            continue
        for value, chain in VALUE_OF[(f, fn, t, c)]:
            param = _parameter(value, chain[0]) if chain else None
            if param is None:
                got = _origin_of(value, f, line, chain, sites, defined, frozenset(), 0) if kind == "unread" else [(f, line, kind)]
            else:
                got = []
                for rel, through, call, enclosing in sites.get(fn, []):
                    if not _supplies(call, *param):
                        continue                      # this call passes nothing for it: the writer's default (None)
                    counts = (through == Path(f).stem or (through == "" and defined.get(fn) == 1)
                              or _on_the_declared_factory(f, fn, rel, call))
                    if not counts:
                        got.append((rel, call.lineno, "unread"))   # a call of this name the scan cannot pin to this writer
                        continue
                    passed = next((kw.value for kw in call.keywords if kw.arg == param[0]), None)
                    if passed is None and 0 <= param[1] < len(call.args):
                        passed = call.args[param[1]]
                    got.extend(_origin_of(passed, rel, call.lineno, enclosing, sites, defined, frozenset(), 0)
                               if passed is not None else [(rel, call.lineno, "unread")])
            out.extend((f, fn, t, c, o) for o in got if o[2] != "none")
    return out, found


def test_nothing_writes_a_person_into_a_column_whose_id_is_not_decided_yet():
    """POST-A-377: a column nothing writes a person into is not decided, because no code says which id it takes. The day something does, this
    fails, and whoever wrote it maps the column."""
    people, found = persons_written_into(NO_PERSON_WRITTEN_YET)
    assert found, "the scan found no write at all to the undecided columns (it should see the writers that write None or nothing calls)"
    assert not people, f"a person is now (or may be) written into a column whose id was never decided; map it (DECIDED_FROM_CODE): {people}"


def test_the_undecided_rule_counts_a_call_it_cannot_pin_as_unread_and_one_that_passes_nothing_as_nobody():
    sources = {
        "repositories/r.py": ("class R:\n    def log_execution(self, db, actor_id=None):\n"
                              "        db.table('workflow_executions').insert({'actor_id': actor_id}).execute()\n"),
        "repositories/s.py": "def log_execution(x):\n    return x\n",                  # a second function of the same name
        "routers/a.py": "def a(repo):\n    repo.log_execution(None)\n",
    }
    people, _ = persons_written_into(NO_PERSON_WRITTEN_YET, sources)
    assert people == [], people                                                   # no call passes actor_id: nobody
    sources["routers/a.py"] = "def a(repo, current_user):\n    repo.log_execution(None, actor_id=current_user.get('id'))\n"
    people, _ = persons_written_into(NO_PERSON_WRITTEN_YET, sources)
    assert [o[2] for *_x, o in people] == ["unread"], people                       # passed, through a call the scan cannot pin


# ── The scan is not blind ─────────────────────────────────────────────────────────────────────────

def _scan(body: str):
    return writes_in(body, "synthetic.py")


def test_a_wrong_id_of_each_kind_is_flagged_and_the_right_one_passed():
    src = '''
def a(db, current_user):
    db.table("client_sales_invoices").insert({"created_by": current_user.get("id")}).execute()
def b(db, current_user):
    db.table("journal_entries").insert({"posted_by": current_user.get("auth_user_id")}).execute()
def c(db, current_user):
    db.table("client_sales_invoices").insert({"created_by": current_user.get("auth_user_id")}).execute()
def d(db, current_user):
    db.table("journal_entries").insert({"posted_by": current_user["id"]}).execute()
'''
    kinds = {(fn, k) for _f, fn, _t, _c, k, _l in _scan(src)}
    assert kinds == {("a", "users"), ("b", "auth"), ("c", "auth"), ("d", "users")}
    wrong = [fn for _f, fn, t, c, k, _l in _scan(src) if k != HOLDS[(t, c)]]
    assert sorted(wrong) == ["a", "b"]


def test_a_bare_name_is_unread_and_a_constant_none_is_not():
    src = '''
def a(db, actor_id):
    db.table("bank_transactions").update({"posted_by": actor_id}).eq("id", 1).execute()
def b(db):
    db.table("bank_transactions").update({"posted_by": None}).eq("id", 1).execute()
'''
    assert {(fn, k) for _f, fn, _t, _c, k, _l in _scan(src)} == {("a", "unread"), ("b", "none")}


def test_a_payload_named_and_filled_by_subscript_is_read_too():
    src = '''
def a(db, current_user):
    row = {"name": "x"}
    row["created_by"] = current_user.get("id")
    db.table("client_sales_invoices").insert(row).execute()
def b(db, current_user):
    rows = [{"created_by": current_user.get("id")} for _ in range(2)]
    db.table("client_sales_invoices").insert(rows).execute()
'''
    assert {(fn, k) for _f, fn, _t, _c, k, _l in _scan(src)} == {("a", "users"), ("b", "users")}


def test_a_table_that_is_not_mapped_is_not_judged():
    src = '''
def a(db, current_user):
    db.table("tasks").insert({"created_by": current_user.get("id")}).execute()
'''
    assert _scan(src) == []


def test_a_call_counts_only_when_it_is_made_through_the_writers_module():
    """`create` is the name of a dozen functions: a name-only match blamed `manual_journal_service.create` for the opening documents."""
    sources = {
        "services/w.py": "def write(db, who):\n    db.table('journal_entries').insert({'posted_by': who})\n",
        "routers/r.py": ("from services import w as svc\nfrom services import other\n"
                         "def a(current_user, db):\n    svc.write(db, current_user.get('id'))\n"
                         "def b(current_user, db):\n    other.write(db, current_user.get('auth_user_id'))\n"
                         "def c(current_user, db):\n    svc.write(db, who=current_user.get('auth_user_id'))\n"),
    }
    sites = _call_sites(sources)
    [(f, fn, t, c, k, _l)] = writes_in(sources["services/w.py"], "services/w.py")
    param = PARAM_OF[(f, fn, t, c)]
    assert param == ("who", 1)
    got = supplied_kinds("write", "w", param, sites)
    assert sorted((rel, kind) for rel, _line, kind in got) == [("routers/r.py", "auth"), ("routers/r.py", "users")], got
    # the call through the OTHER module is not counted for this writer: it is attributed to another module
    [other_call] = [(through, call) for rel, through, call, _e in sites["write"] if ast.unparse(call.func) == "other.write"]
    assert other_call[0] != "w", other_call


def test_a_bare_name_call_inside_the_writers_own_module_counts():
    sources = {"services/w.py": ("def write(db, who):\n    db.table('journal_entries').insert({'posted_by': who})\n"
                                 "def post(db, current_user):\n    write(db, current_user['id'])\n")}
    sites = _call_sites(sources)
    [(f, fn, t, c, k, _l)] = writes_in(sources["services/w.py"], "services/w.py")
    assert [kind for _f, _line, kind in supplied_kinds("write", "w", PARAM_OF[(f, fn, t, c)], sites)] == ["users"]


# ── the chain is followed, whatever shape it takes ─────────────────────────────────────────────────────────────

def _chain(sources: dict[str, str], writer_file: str, fn: str, table="journal_entries", column="posted_by"):
    [(f, name, t, c, k, _l)] = [w for w in writes_in(sources[writer_file], writer_file) if w[1] == fn]
    param = PARAM_OF[(f, name, t, c)]
    return origins(fn, writer_file, param, _call_sites(sources), _definition_counts(sources)), param


def test_a_value_passed_on_through_several_calls_is_followed_to_where_it_is_made():
    sources = {
        "services/w.py": "def write(db, who):\n    db.table('journal_entries').insert({'posted_by': who})\n",
        "services/mid.py": "from services import w\ndef relay(db, actor):\n    w.write(db, actor)\n",
        "routers/r.py": ("from services import mid\n"
                         "def good(current_user, db):\n    mid.relay(db, current_user.get('id'))\n"
                         "def bad(current_user, db):\n    mid.relay(db, current_user.get('auth_user_id'))\n"),
    }
    got, _ = _chain(sources, "services/w.py", "write")
    assert sorted((rel, kind) for rel, _line, kind in got) == [("routers/r.py", "auth"), ("routers/r.py", "users")], got


def test_a_nested_helper_reads_the_variable_of_its_outer_function():
    """`_insert_and_cache(created_by=created_by)` is called from a nested `_attempt` that takes no parameter: the name is the outer function's."""
    sources = {
        "domain/inv.py": ("def _insert(db, created_by=None):\n    db.table('journal_entries').insert({'posted_by': created_by})\n"
                          "def seed(db, created_by=None):\n    def _attempt():\n        _insert(db, created_by=created_by)\n    return _attempt()\n"),
        "routers/r.py": "from domain import inv\ndef a(current_user, db):\n    inv.seed(db, created_by=current_user.get('id'))\n",
    }
    got, _ = _chain(sources, "domain/inv.py", "_insert")
    assert [kind for _f, _l, kind in got] == ["users"], got


def test_a_conditional_with_an_empty_branch_is_the_other_branch_and_a_cycle_does_not_hang():
    sources = {
        "services/k.py": ("def kernel(db, created_by, is_posted):\n    db.table('journal_entries').insert({'posted_by': created_by if is_posted else None})\n"
                          "def ping(db, who):\n    pong(db, who)\ndef pong(db, who):\n    ping(db, who)\n    kernel(db, who, True)\n"),
        "routers/r.py": "from services import k\ndef a(current_user, db):\n    k.ping(db, current_user.get('id'))\n",
    }
    got, param = _chain(sources, "services/k.py", "kernel")
    assert param == ("created_by", 1)
    kinds = {kind for _f, _l, kind in got}
    assert "users" in kinds and kinds <= {"users", "unread"}, got         # the loop is cut, not followed for ever


def test_a_call_on_the_result_of_a_function_counts_only_when_the_name_is_unique_or_declared():
    sources = {
        "services/w.py": "def only_one(db, who):\n    db.table('journal_entries').insert({'posted_by': who})\n",
        "services/x.py": "def shared(db, who):\n    db.table('journal_entries').insert({'posted_by': who})\n",
        "services/y.py": "def shared(db, who):\n    pass\n",
        "routers/r.py": ("def a(current_user, db, svc):\n    svc().only_one(db, current_user.get('id'))\n"
                         "    svc().shared(db, current_user.get('auth_user_id'))\n"),
    }
    one, _ = _chain(sources, "services/w.py", "only_one")
    assert [kind for _f, _l, kind in one] == ["users"], one
    two, _ = _chain(sources, "services/x.py", "shared")
    assert two == [], "a name defined twice is not resolved through an object the scan cannot name"


def test_rows_collected_with_append_are_a_payload_too():
    src = """
def a(db, created_by):
    rows = []
    for n in range(3):
        rows.append({"created_by": created_by, "n": n})
    db.table("inventory_stock_ledger").insert(rows).execute()
def b(db, current_user):
    rows = []
    rows.extend([{"created_by": current_user.get("auth_user_id")}])
    db.table("inventory_stock_ledger").insert(rows).execute()
"""
    assert {(fn, k) for _f, fn, _t, _c, k, _l in writes_in(src, "x.py")} == {("a", "unread"), ("b", "auth")}


def test_a_read_of_a_column_that_keys_users_is_the_internal_id():
    assert kind_of(ast.parse('rule.get("trusted_by")', mode="eval").body) == "users"
    assert kind_of(ast.parse('rule.get("something_else")', mode="eval").body) == "unread"
    assert kind_of(ast.parse('rule.get("trusted_by") or current_user.get("auth_user_id")', mode="eval").body) == "auth"


def test_a_call_made_on_a_declared_factory_counts_and_a_look_alike_does_not():
    good = ast.parse("_repo().create_conversation(f, u, {})", mode="eval").body
    other_factory = ast.parse("_other().create_conversation(f, u, {})", mode="eval").body
    key_file = "repositories/ai_copilot_repository.py"
    assert _on_the_declared_factory(key_file, "create_conversation", "routers/ai_copilot_v2.py", good)
    assert not _on_the_declared_factory(key_file, "create_conversation", "routers/ai_copilot_v2.py", other_factory)
    assert not _on_the_declared_factory(key_file, "create_conversation", "routers/elsewhere.py", good)


# ── The new patterns of POST-A-377 are not blind either ───────────────────────────────────────────

def _trace_synthetic(src: str, columns=None):
    """{(function, table, column): [origin kinds]} for a synthetic module traced against itself."""
    sources = {"synthetic.py": src}
    sites, defined = _call_sites(sources), _definition_counts(sources)
    tree = ast.parse(src)
    for key in [k for k in VALUE_OF if k[0] == "synthetic.py"]:
        del VALUE_OF[key]                           # each synthetic module is traced on its own
    _MODULE_FUNCTIONS["synthetic.py"] = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    out = {}
    for f, fn, t, c, kind, line in writes_in(src, "synthetic.py", columns=columns):
        if kind != "unread":
            out[(fn, t, c)] = [kind]
            continue
        for value, chain in VALUE_OF[(f, fn, t, c)]:
            out.setdefault((fn, t, c), []).extend(
                o[2] for o in _origin_of(value, "synthetic.py", line, chain, sites, defined, frozenset(), 0))
    del _MODULE_FUNCTIONS["synthetic.py"]
    return out


def test_a_column_written_back_with_its_own_earlier_value_is_a_restore_and_another_columns_value_is_not():
    src = '''
def undo(db, before):
    db.table("bank_transactions").update({"matched_by": before["matched_by"]}).execute()
def wrong(db, before):
    db.table("bank_transactions").update({"matched_by": before["posted_by"]}).execute()
'''
    assert _trace_synthetic(src)[("undo", "bank_transactions", "matched_by")] == ["unread"]       # not declared: not a restore
    RESTORES[("synthetic.py", "undo", "before['matched_by']")] = "declared for this test"
    try:
        got = _trace_synthetic(src)
        assert got[("undo", "bank_transactions", "matched_by")] == ["restore"]
        assert got[("wrong", "bank_transactions", "matched_by")] == ["unread"]
    finally:
        del RESTORES[("synthetic.py", "undo", "before['matched_by']")]


def test_a_self_call_is_made_through_the_class_that_defines_it():
    src = '''
class S:
    def go(self, db, current_user):
        self._write(db, current_user.get("auth_user_id"))
    def _write(self, db, who):
        db.table("bank_transactions").update({"matched_by": who}).execute()
'''
    assert _trace_synthetic(src)[("_write", "bank_transactions", "matched_by")] == ["auth"]   # found, and it is the wrong kind


def test_an_attribute_of_an_object_built_here_or_by_a_helper_is_the_keyword_it_was_built_with():
    src = '''
def _build(current_user):
    return make(rate_selected_by=current_user.get("auth_user_id"))
def direct(db, current_user):
    dc = make(rate_selected_by=current_user.get("id"))
    db.table("journal_entries").insert({"rate_selected_by": dc.rate_selected_by}).execute()
def through_a_helper(db, current_user):
    dc = _build(current_user)
    db.table("journal_entries").insert({"rate_selected_by": dc.rate_selected_by}).execute()
'''
    got = _trace_synthetic(src)
    assert got[("direct", "journal_entries", "rate_selected_by")] == ["users"]
    assert got[("through_a_helper", "journal_entries", "rate_selected_by")] == ["auth"]


def test_a_typed_member_id_is_proven_only_where_the_check_is_declared():
    src = '''
def create_recurring(db, body):
    db.table("task_recurring_configs").insert({"assignee_id": body.assignee_id}).execute()
'''
    assert _trace_synthetic(src)[("create_recurring", "task_recurring_configs", "assignee_id")] == ["unread"]
    CHECKED_AS_A_MEMBER[("synthetic.py", "create_recurring", "body.assignee_id")] = "member_is_the_firms("
    try:
        assert _trace_synthetic(src)[("create_recurring", "task_recurring_configs", "assignee_id")] == ["users"]
    finally:
        del CHECKED_AS_A_MEMBER[("synthetic.py", "create_recurring", "body.assignee_id")]


def test_the_undecided_columns_rule_sees_a_person_written_and_spares_a_none():
    src = '''
def a(db, current_user):
    db.table("leads").insert({"created_by": current_user.get("id")}).execute()
def b(db):
    db.table("leads").insert({"created_by": None}).execute()
'''
    got = _trace_synthetic(src, columns=NO_PERSON_WRITTEN_YET)
    assert got == {("a", "leads", "created_by"): ["users"], ("b", "leads", "created_by"): ["none"]}



def test_an_object_is_proven_only_when_every_way_it_is_built_is_read():
    """An independent read made three false proofs pass: a helper with one unread return, a second unreadable assignment, and a later
    `row["who"] = <other kind>` overwrite. Each is now unread or the overwrite's own kind."""
    src = '''
def _two_returns(current_user, other):
    if other:
        return other_module.make(current_user)
    return make(rate_selected_by=current_user.get("id"))
def helper_with_an_unread_return(db, current_user):
    dc = _two_returns(current_user, None)
    db.table("journal_entries").insert({"rate_selected_by": dc.rate_selected_by}).execute()
def a_second_unreadable_assignment(db, current_user, x):
    dc = make(rate_selected_by=current_user.get("id"))
    dc = x
    db.table("journal_entries").insert({"rate_selected_by": dc.rate_selected_by}).execute()
def an_overwrite(db, current_user):
    row = {"rate_selected_by": current_user.get("id")}
    row["rate_selected_by"] = current_user.get("auth_user_id")
    db.table("journal_entries").insert({"rate_selected_by": row["rate_selected_by"]}).execute()
'''
    got = _trace_synthetic(src)
    assert "unread" in got[("helper_with_an_unread_return", "journal_entries", "rate_selected_by")]
    assert "unread" in got[("a_second_unreadable_assignment", "journal_entries", "rate_selected_by")]
    assert "auth" in got[("an_overwrite", "journal_entries", "rate_selected_by")]


def test_a_value_forwarded_through_double_star_is_followed_to_its_callers():
    """`record_event(**fields)` -> `_row(**fields)` was invisible: the timeline route's actor never reached the trace."""
    sources = {
        "services/t.py": ("class T:\n    def record(self, **fields):\n        return self._row(**fields)\n"
                          "    def _row(self, *, actor_id=None):\n        db.table('client_timeline_events').insert({'actor_id': actor_id})\n"),
        "routers/r.py": ("from services import t\ndef a(current_user):\n    t.svc.record(actor_id=current_user.get('id'))\n"),
    }
    sites, defined = _call_sites(sources), _definition_counts(sources)
    assert [k for _f, _l, k in origins("_row", "services/t.py", ("actor_id", -1), sites, defined)] == ["users"]


def test_what_a_function_from_another_module_carries_is_read_in_that_module():
    for name, (rel, text, kind) in CARRIED_BY_A_FUNCTION.items():
        assert text in _function_text(rel, name), f"{rel}::{name} no longer carries {text!r}: CARRIED_BY_A_FUNCTION is stale"
        if kind != "none":
            # `document_currency_from_row` carries the document's own column: every document table with one must hold that kind
            tables = [t for (t, c) in HOLDS if c == "rate_selected_by"]
            assert tables and all(HOLDS[(t, "rate_selected_by")] == kind for t in tables), tables


def test_every_declared_restore_is_still_written_where_it_is_declared():
    for (rel, fn_name, value), _why in RESTORES.items():
        assert value in _function_text(rel, fn_name), f"{rel}::{fn_name} no longer writes {value}: RESTORES is stale"
