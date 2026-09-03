# Guard drift — the first run (3 September 2026)

`scripts/db/guard_drift.py` compared the RLS switches, policies and constraints
of a database built from the migrations against production for the first time
at 02:15 IST on 3 September 2026 (`tests/fixtures/production_guards_2026-09-03.json`,
proved equal to a fresh capture by `guards_md5` in its `.meta.json`). This is
what it found, what migration 316 closed, and what is left for a human.

The column diff (`schema_drift.py`, 31 August) had a blind spot it named in its
own docstring: "deliberately not indexes, policies, functions or triggers".
Migration 293 then walked into it — a foreign key production lacked, two
RESTRICTIVE policies drifted from their declared form — and this run found a
CHECK constraint that had been rejecting a real feature. So the diff now has a
twin, and `tests/test_guards_match_production_pg.py` holds four directions at
zero the same way the column test holds three.

## 276 differences, in five headline categories and eight informational ones

| Category | Count | Asserted | After 316 |
|---|---|---|---|
| RLS switched OFF in production | **0** | yes | 0 |
| RESTRICTIVE policies missing from production | **0** (1 on a table production lacks) | yes | 0 |
| Tables with declared policies and none in production | **0** | yes | 0 |
| CHECK constraints whose expression differs | **2** | yes | 0 |
| UNIQUE constraints missing from production | 3 | no — see client_profiles | 1 |
| Tables the migrations declare that production lacks | 7 | no | 7 |
| Tables production has that no migration declares | 11 | no | 11 |
| Policies the migrations declare that production lacks | 19 | no | 19 |
| Policies production has that no migration declares | 77 | no | 77 |
| Policies whose roles or expression differ | 30 | no | 30 |
| Constraints the migrations declare that production lacks | 36 | no | 1 |
| Constraints production has that no migration declares | 62 | no | 62 |
| Constraints whose definition differs | 29 | no | 29 |

The four asserted categories are the ones that BREAK something — a tenancy
check not applied, a table fail-closed to the frontend's direct reads, or a
value rejected in production that every test here accepts. The rest is real
drift and is listed below for the next pass; asserting on 270 lines would make
the test a permanent complaint that somebody turns off, which is how the column
diff was scoped too.

## The two live bugs

**`clients_status_check`.** Migration 042 widened it to `('active',
'inactive', 'archived')`. Production's still read `('active', 'inactive')`.
`routers/clients.py` archives a client by writing `'archived'`, so archiving
failed in production — with a 23514 that reached the CA as "Internal server
error" before PR #384 — while the suite passed here. Every client in production
is `active`; nobody had managed to archive one. Migration 316 drops and
re-creates the constraint on both sides so the two definitions hash the same.

**`form_26as_uploads_parse_status_check`.** Migration 234 declares `('pending',
'parsed', 'failed')`; production has `('pending', 'parsing', 'parsed',
'error')`. The code writes only `pending` and `parsed`, production holds no
rows, so nothing had failed — but a future write of `'failed'` would have.
Converged to the declared set, both sides.

## What migration 316 adds to production

All checked against production data before writing, at 02:15 IST:

- **18 foreign keys** the migrations declare inline and production never got
  (0 orphans in every child column): `automation_executions.firm_id`,
  `client_timeline_events.client_id` (the one 293 noticed), `escalation_rules.firm_id`,
  `filings.firm_id`, `gst_portal_snapshots.sync_job_id`, `invoice_sequences.firm_id`,
  `pending_invites.firm_id`, `permission_grants.firm_id`, `task_escalations.task_id`,
  `tasks.workflow_step_id`, `workflow_steps.workflow_id`, the six
  `year_end_engagements.*_by → users(id)`, and `year_end_exports.version_id`.
  Added `NOT VALID` then `VALIDATE`, so a row that appears before the deploy
  fails the migration loudly rather than being locked in.
- **11 format CHECKs from migration 112 and fee_invoices' length check** (0
  violating rows each): the PAN / GSTIN / pincode / BSR patterns. Added `NOT VALID` and
  deliberately NOT validated, because that is the form 112 declares and the
  template carries — a validated copy in production would itself read as drift.
- **2 plain CHECKs and 2 UNIQUEs** (0 violators, 0 duplicate groups):
  `account_group_mappings_statement_type_check`, `workflow_steps_default_assignee_role_check`,
  `account_group_mappings (firm_id, account_id)`, `workflow_steps (workflow_id, step_order)`.

Every step is guarded on its own existence, so on a replayed database 316 is a
no-op and it was applied twice to the local harness to prove it.

## Deliberately NOT reconciled — each needs a person

### `client_profiles_firm_id_client_id_key` — the migrations are wrong, not the data

The migrations declare `UNIQUE (firm_id, client_id)`. Production holds 94 rows
in 6 groups of ~16, one per client per day since 18 August. That is not a bug
in the data: `repositories/memory_repository.upsert_profile` **versions**
profiles — it retires the current row (`is_current = false`), inserts the next
with `profile_version + 1`, and writes a `client_profile_history` snapshot
pointing at the retired row (88 history rows, every one on a non-current
profile, `ON DELETE CASCADE`). Adding the unique would need those rows
deleted, and the history with them.

What is wrong is the declaration. The right shape is a partial unique index —
`UNIQUE (firm_id, client_id) WHERE is_current` — which says what the code
means. That is a design decision for whoever owns the memory pipeline, and it
should also ask whether a profile that is recomputed every day by the sweep
ought to keep every daily version forever.

### 62 constraints production has and no migration declares — CLOSED by 319

*Migration 319 declares 59 of them, and the other three were taken by 318
(the two Tally vocabularies and the widened `gst_sync_jobs` one). Every
declared object was verified to hash IDENTICALLY to production's — the
constraint set is now at zero. The paragraph below is the original finding.*

### The original finding

Mostly on the tables the intelligence and tax layers got from a Studio
migration the repository never had (the same story migration 252 tells):
`itr_filings`, `tax_computation_snapshots`, `tax_deduction_claims`,
`tax_disallowances`, `xbrl_packages`, `einvoice_records`, `eway_bill_records`,
`brought_forward_losses`, `form_26as_*`, `tally_migration_*`, `gst_sync_jobs`.
Production has status CHECKs, `created_by → users(id)` foreign keys and
UNIQUEs on them that the migrations do not.

These are the dangerous direction in the same sense as the column test's
`live_requires_but_migrations_do_not`: a value the migrations accept can be
rejected there. Two things were checked before leaving them:

- **None of the `*_by → users(id)` foreign keys is being written with the auth
  id.** The #89 scan (`test_users_fk_columns_take_the_internal_id.py`) reads
  the FK list from the migrated template, so it could not see these; a manual
  scan of every insert site for the twenty columns found each written from
  `current_user["id"]` or a caller-supplied `actor_id`. Once these FKs are
  declared in a migration, the scan covers them automatically.
- **No test writes a status value production's CHECKs refuse** — but only
  because nothing asserted it. Declaring these constraints in a migration is
  the 292 pattern (declare what production already has; zero effect there,
  and the local template starts enforcing it) and is the right next step. It
  is a separate PR because the moment the template enforces them, any test
  fixture writing `status='foo'` fails, and each of those is a judgement.

### 36 → 1 constraints the migrations declare and production lacks

34 are added by 316 and one — `year_end_review_events_actor_id_fkey` — by 315,
so the survivor is the client_profiles unique above. The objects on the seven
tables production does not have at all (`notes_to_accounts`,
`year_end_checklists`, `year_end_reviews`, `ri_*` — 067's never-applied
tables, which no router queries since migration 252 repointed them) are not in
this count: the diff folds them into "table missing", so they are 7 findings,
not 40.

### 29 constraints whose definition differs — every one is `ON DELETE`

The migrations declare `ON DELETE CASCADE` on the `client_id` / `firm_id` /
`job_id` foreign keys of the Studio-created tables; production's are plain
`NO ACTION`. No insert is affected. A DELETE of a client behaves differently:
here it cascades, there it is refused. Since the product soft-deletes clients
(`deleted_at`) and hard-deletes are not a user action, this is low-risk and
not urgent, and which side is right depends on whether a hard delete should
ever be possible. Converging is one migration of drop-and-re-add per key once
that is decided.

### 19 + 77 policies present on one side only — mostly renames, all worth a pass

The 19 declared-but-absent are permissive firm-isolation policies whose
production counterpart exists under another name (`firm_client_isolation`
here, `firm_purchase_bills` there). No table is left without a policy — that is
asserted — so isolation holds; but a migration that later `DROP POLICY IF
EXISTS` by the declared name would silently miss. The 77 the other way include
the RESTRICTIVE `*_assignment_scope` policies of migrations 260/261 on the
Studio tables, which production has and the migrations do not: **on a fresh
deployment those tables would have no assignment scoping.** Declaring what
production has, by its production name, is again the 292 pattern.

> **Correction, later the same day.** This paragraph originally said nine
> tables were left "with RLS on and no policy at all ... fail-closed to the
> direct path". Both halves were wrong, and in the unsafe direction. Eight of
> them — `credit_note_allocations`, `invoice_sequences`, `scheduler_runs`,
> `task_dependencies`, `task_tags`, `task_templates`, `task_timeline_events`,
> `user_capacity` — have RLS switched **OFF** in the migrations, not on, and
> `authenticated` holds table grants on every one (full DML on five). That is
> fail-**open**: no isolation whatsoever on the direct PostgREST path. Only
> `purchase_bill_lines` is genuinely RLS-on-no-policy, which is fail-closed and
> deliberate. Production is unaffected — it has RLS on for all eight — so no
> assertion pointed at the live database could see it. Migration 317 fixes it,
> `guard_drift.py` gained the mirror category `rls_off_in_the_migrations`, and
> `tests/test_rls_covers_every_granted_table_pg.py` now asserts the underlying
> invariant. The full account is in
> `docs/audits/2026-09-03-rls-off-on-eight-granted-tables.md`.

### 30 policies whose roles differ: `PUBLIC` here, `authenticated` there

Production's policies carry `TO authenticated`; the migrations' `CREATE
POLICY` has no `TO` clause, which means `PUBLIC`. Production is the stricter
side, and the stricter side is the one the Supabase linter recommends. Safe
direction; a future migration that re-creates one of these policies from the
repository would silently WIDEN it to anon, which is the reason to converge
the declarations to `TO authenticated` at some point.

## What the hash normalisation hides, on purpose

Five policies differed only in that production's expression reads
`( SELECT auth.uid() AS uid)` where the migrations' reads `auth.uid()` — the
linter's initplan rewrite, applied to some policies by migration 008 and to
others by hand in production. Same predicate, evaluated once per statement
instead of once per row. `guard_snapshot.py` folds the rewrite out before
hashing so the diff reports who a policy admits, not how the planner runs it.
A change to WHO still changes the hash.

## Refreshing the fixture

`tests/fixtures/README.md`. The `.meta.json` records `applied_through_migration`
(314 at capture) and `guards_md5`; the PG test excuses any guard named by a
migration above the mark, and refuses to run if the repository is more than ten
migrations ahead of the fixture, so the exclusion cannot quietly excuse
everything.

## Appendix — the full report as rendered

```
CHECK constraints whose expression differs — a value the migrations accept may be REJECTED in production while every test here passes  (2)
------------------------------------------------------------------------------
  clients.clients_status_check
  form_26as_uploads.form_26as_uploads_parse_status_check

UNIQUE constraints the migrations declare that the live database lacks — an upsert written against one fails there  (3)
------------------------------------------------------------------------------
  account_group_mappings.account_group_mappings_firm_id_account_id_key
  client_profiles.client_profiles_firm_id_client_id_key
  workflow_steps.workflow_steps_workflow_id_step_order_key

Tables the migrations declare that the live database does not have  (7)
------------------------------------------------------------------
  notes_to_accounts
  ri_client_entity_links
  ri_cross_client_signals
  ri_entities
  ri_entity_relationships
  year_end_checklists
  year_end_reviews

Tables in the live database that no migration declares  (11)
------------------------------------------------------
  _backup_247_invoices
  _backup_247_journal_lines
  _mig247_targets
  ai_memory_triggers
  assignment_rules
  client_profile_history
  pattern_anomalies
  workflow_conditions
  workflow_triggers
  xbrl_tag_mappings
  year_end_reports

Policies the migrations declare that the live database does not have  (19)
--------------------------------------------------------------------
  automation_executions.automation_executions_own_firm  [permissive cmd=* roles=PUBLIC]
  client_sales_invoice_lines.firm_client_isolation  [permissive cmd=* roles=authenticated]
  client_sales_invoices.firm_client_isolation  [permissive cmd=* roles=authenticated]
  client_timeline_events.firm_isolation  [permissive cmd=* roles=PUBLIC]
  credit_note_lines.firm_client_isolation  [permissive cmd=* roles=authenticated]
  credit_notes.firm_client_isolation  [permissive cmd=* roles=authenticated]
  filings.filings_own_firm  [permissive cmd=* roles=PUBLIC]
  fixed_assets.fixed_assets_own_firm  [permissive cmd=* roles=PUBLIC]
  form_26as_uploads.firm_isolation  [permissive cmd=* roles=PUBLIC]
  permission_grants.permission_grants_own_firm  [permissive cmd=* roles=PUBLIC]
  purchase_bills.firm_client_isolation  [permissive cmd=* roles=authenticated]
  receipt_allocations.firm_client_isolation  [permissive cmd=* roles=authenticated]
  receipts.firm_client_isolation  [permissive cmd=* roles=authenticated]
  reminders.reminders_own_firm  [permissive cmd=* roles=PUBLIC]
  task_escalations.task_escalations_own_firm  [permissive cmd=* roles=PUBLIC]
  team_members.team_members_own_firm  [permissive cmd=* roles=PUBLIC]
  workflow_steps.firm_isolation  [permissive cmd=* roles=authenticated]
  workflow_steps.workflow_steps_own_firm  [permissive cmd=* roles=PUBLIC]
  workflows.workflows_own_firm  [permissive cmd=* roles=PUBLIC]

Policies in the live database that no migration declares  (77)
--------------------------------------------------------
  account_group_mappings.agm_firm  [permissive cmd=* roles=PUBLIC]
  ai_actions.firm_iso_ai_actions  [permissive cmd=* roles=PUBLIC]
  ai_context_windows.firm_iso_ai_context_windows  [permissive cmd=* roles=PUBLIC]
  ai_conversations.firm_iso_ai_conversations  [permissive cmd=* roles=PUBLIC]
  ai_feedback.firm_iso_ai_feedback  [permissive cmd=* roles=PUBLIC]
  ai_messages.firm_iso_ai_messages  [permissive cmd=* roles=PUBLIC]
  ai_recommendations.firm_iso_ai_recommendations  [permissive cmd=* roles=PUBLIC]
  ai_summaries.firm_iso_ai_summaries  [permissive cmd=* roles=PUBLIC]
  audit_log.audit_log_own_firm  [permissive cmd=r roles=PUBLIC]
  brought_forward_losses.brought_forward_losses_assignment_scope  [RESTRICTIVE cmd=* roles=PUBLIC]
  brought_forward_losses.firm_isolation_bf_losses  [permissive cmd=* roles=authenticated]
  client_sales_invoice_lines.firm_client_sales_invoice_lines  [permissive cmd=* roles=authenticated]
  client_sales_invoices.firm_client_sales_invoices  [permissive cmd=* roles=authenticated]
  credit_note_allocations.firm_credit_note_allocations  [permissive cmd=* roles=authenticated]
  credit_note_lines.firm_credit_note_lines  [permissive cmd=* roles=authenticated]
  credit_notes.firm_credit_notes  [permissive cmd=* roles=authenticated]
  einvoice_records.einvoice_records_assignment_scope  [RESTRICTIVE cmd=* roles=PUBLIC]
  einvoice_records.firm_isolation_einvoice  [permissive cmd=* roles=authenticated]
  eway_bill_records.eway_bill_records_assignment_scope  [RESTRICTIVE cmd=* roles=PUBLIC]
  eway_bill_records.firm_isolation_eway_bills  [permissive cmd=* roles=authenticated]
  financial_statement_versions.financial_statement_versions_assignment_scope  [RESTRICTIVE cmd=* roles=PUBLIC]
  financial_statement_versions.fsv_firm  [permissive cmd=* roles=PUBLIC]
  form_26as_reconciliations.firm_isolation_26as_recon  [permissive cmd=* roles=authenticated]
  form_26as_reconciliations.form_26as_reconciliations_assignment_scope  [RESTRICTIVE cmd=* roles=PUBLIC]
  form_26as_records.firm_isolation_26as_records  [permissive cmd=* roles=authenticated]
  form_26as_records.form_26as_records_assignment_scope  [RESTRICTIVE cmd=* roles=PUBLIC]
  form_26as_uploads.firm_isolation_26as_uploads  [permissive cmd=* roles=authenticated]
  gst_portal_snapshots.firm_isolation_gst_snapshots  [permissive cmd=* roles=authenticated]
  gst_portal_snapshots.gst_portal_snapshots_assignment_scope  [RESTRICTIVE cmd=* roles=PUBLIC]
  gst_sync_jobs.firm_isolation_gst_sync_jobs  [permissive cmd=* roles=authenticated]
  gst_sync_jobs.gst_sync_jobs_assignment_scope  [RESTRICTIVE cmd=* roles=PUBLIC]
  invoice_sequences.invoice_sequences_own_firm  [permissive cmd=* roles=PUBLIC]
  itr_filing_versions.firm_isolation_itr_versions  [permissive cmd=* roles=authenticated]
  itr_filings.firm_isolation_itr_filings  [permissive cmd=* roles=authenticated]
  itr_filings.itr_filings_assignment_scope  [RESTRICTIVE cmd=* roles=PUBLIC]
  pending_invites.pending_invites_own_firm  [permissive cmd=* roles=PUBLIC]
  purchase_bill_lines.firm_purchase_bill_lines  [permissive cmd=* roles=authenticated]
  purchase_bills.firm_purchase_bills  [permissive cmd=* roles=authenticated]
  receipt_allocations.firm_receipt_allocations  [permissive cmd=* roles=authenticated]
  receipts.firm_receipts  [permissive cmd=* roles=authenticated]
  scheduler_runs.scheduler_runs_own_firm  [permissive cmd=* roles=PUBLIC]
  tally_migration_items.firm_isolation_tally_items  [permissive cmd=* roles=authenticated]
  tally_migration_jobs.firm_isolation_tally_jobs  [permissive cmd=* roles=authenticated]
  task_dependencies.task_dependencies_via_task  [permissive cmd=* roles=PUBLIC]
  task_escalations.task_escalations_via_task  [permissive cmd=* roles=PUBLIC]
  task_recurring_configs.task_recurring_configs_own_firm  [permissive cmd=* roles=PUBLIC]
  task_tags.task_tags_own_firm  [permissive cmd=* roles=PUBLIC]
  task_templates.task_templates_own_firm  [permissive cmd=* roles=PUBLIC]
  task_timeline_events.task_timeline_events_own_firm  [permissive cmd=* roles=PUBLIC]
  tax_computation_snapshots.firm_isolation_tax_snapshots  [permissive cmd=* roles=authenticated]
  tax_computation_snapshots.tax_computation_snapshots_assignment_scope  [RESTRICTIVE cmd=* roles=PUBLIC]
  tax_deduction_claims.firm_isolation_deduction_claims  [permissive cmd=* roles=authenticated]
  tax_deduction_claims.tax_deduction_claims_assignment_scope  [RESTRICTIVE cmd=* roles=PUBLIC]
  tax_disallowances.firm_isolation_tax_disallowances  [permissive cmd=* roles=authenticated]
  tax_disallowances.tax_disallowances_assignment_scope  [RESTRICTIVE cmd=* roles=PUBLIC]
  time_entries.time_entries_own_firm  [permissive cmd=* roles=PUBLIC]
  user_capacity.user_capacity_own_firm  [permissive cmd=* roles=PUBLIC]
  workflow_action_logs.firm_iso_wf_action_logs  [permissive cmd=* roles=PUBLIC]
  workflow_approvals.firm_iso_wf_approvals  [permissive cmd=* roles=PUBLIC]
  workflow_approvals.workflow_approvals_firm_isolation  [permissive cmd=* roles=PUBLIC]
  workflow_executions.firm_iso_wf_executions  [permissive cmd=* roles=PUBLIC]
  workflow_executions.workflow_executions_firm_isolation  [permissive cmd=* roles=PUBLIC]
  workflow_failures.firm_iso_wf_failures  [permissive cmd=* roles=PUBLIC]
  workflow_failures.workflow_failures_firm_isolation  [permissive cmd=* roles=PUBLIC]
  workflow_instances.firm_iso_wf_instances  [permissive cmd=* roles=PUBLIC]
  workflow_instances.workflow_instances_assignment_scope  [RESTRICTIVE cmd=* roles=PUBLIC]
  workflow_instances.workflow_instances_firm_isolation  [permissive cmd=* roles=PUBLIC]
  workflow_schedules.firm_iso_wf_schedules  [permissive cmd=* roles=PUBLIC]
  workflow_schedules.workflow_schedules_firm_isolation  [permissive cmd=* roles=PUBLIC]
  workflow_steps.firm_iso_wf_steps  [permissive cmd=* roles=PUBLIC]
  workflow_templates.firm_iso_wf_templates  [permissive cmd=* roles=PUBLIC]
  xbrl_packages.firm_isolation_xbrl_packages  [permissive cmd=* roles=authenticated]
  xbrl_packages.xbrl_packages_assignment_scope  [RESTRICTIVE cmd=* roles=PUBLIC]
  year_end_adjustments.yea_firm  [permissive cmd=* roles=PUBLIC]
  year_end_engagements.yee_firm  [permissive cmd=* roles=PUBLIC]
  year_end_exports.year_end_exports_assignment_scope  [RESTRICTIVE cmd=* roles=PUBLIC]
  year_end_exports.yex_firm  [permissive cmd=* roles=PUBLIC]

Policies whose kind, command, roles or expression differ  (30)
--------------------------------------------------------
  activity_logs.activity_logs_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  ai_insights.ai_insights_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  automation_rules.automation_rules_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  bank_reconciliation_matches.bank_recon_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  bank_statements.bank_statements_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  bank_transactions.bank_transactions_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  chart_of_accounts.chart_of_accounts_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  client_documents.client_documents_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  clients.clients_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  compliance_calendar.compliance_calendar_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  compliance_records.compliance_records_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  document_extractions.document_extractions_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  document_risks.document_risks_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  documents.documents_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  dsc_records.dsc_records_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  fee_engagements.fee_engagements_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  fee_invoices.fee_invoices_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  ledger_balances.ledger_balances_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  mca_filings.mca_filings_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  msme_vendors.msme_vendors_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  notifications.notifications_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  payroll_employees.payroll_employees_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  payroll_runs.payroll_runs_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  retainer_clients.retainer_clients_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  retainer_logs.retainer_logs_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  tasks.tasks_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  tax_audit_checklists.tax_audit_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  tax_notices.tax_notices_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  tax_planning_records.tax_planning_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated
  tds_deductions.tds_deductions_own_firm: migrations say permissive cmd=* roles=PUBLIC, live says permissive cmd=* roles=authenticated

Constraints the migrations declare that the live database does not have  (36)
-----------------------------------------------------------------------
  account_group_mappings.account_group_mappings_firm_id_account_id_key  [u]
  account_group_mappings.account_group_mappings_statement_type_check  [c]
  automation_executions.automation_executions_firm_id_fkey  [f]
  client_profiles.client_profiles_firm_id_client_id_key  [u]
  client_timeline_events.client_timeline_events_client_id_fkey  [f]
  customers.customers_gstin_format  [c]
  customers.customers_pan_format  [c]
  escalation_rules.escalation_rules_firm_id_fkey  [f]
  fee_invoices.fee_invoices_invoice_no_length  [c]
  filings.filings_firm_id_fkey  [f]
  firms.firms_gstin_format  [c]
  firms.firms_pan_format  [c]
  firms.firms_pincode_format  [c]
  gst_portal_snapshots.gst_portal_snapshots_sync_job_id_fkey  [f]
  gstr1_returns.gstr1_returns_gstin_format  [c]
  invoice_sequences.invoice_sequences_firm_id_fkey  [f]
  payroll_employees.payroll_employees_pan_format  [c]
  pending_invites.pending_invites_firm_id_fkey  [f]
  permission_grants.permission_grants_firm_id_fkey  [f]
  task_escalations.task_escalations_task_id_fkey  [f]
  tasks.tasks_workflow_step_id_fkey  [f]
  tds_certificates.tds_certificates_pan_format  [c]
  tds_challans.tds_challans_bsr_code_format  [c]
  vendors.vendors_gstin_format  [c]
  vendors.vendors_pan_format  [c]
  workflow_steps.workflow_steps_default_assignee_role_check  [c]
  workflow_steps.workflow_steps_workflow_id_fkey  [f]
  workflow_steps.workflow_steps_workflow_id_step_order_key  [u]
  year_end_engagements.year_end_engagements_approved_by_fkey  [f]
  year_end_engagements.year_end_engagements_final_approved_by_fkey  [f]
  year_end_engagements.year_end_engagements_prepared_by_fkey  [f]
  year_end_engagements.year_end_engagements_reviewed_by_fkey  [f]
  year_end_engagements.year_end_engagements_revision_requested_by_fkey  [f]
  year_end_engagements.year_end_engagements_submitted_by_fkey  [f]
  year_end_exports.year_end_exports_version_id_fkey  [f]
  year_end_review_events.year_end_review_events_actor_id_fkey  [f]

Constraints in the live database that no migration declares  (62)
-----------------------------------------------------------
  brought_forward_losses.brought_forward_losses_created_by_fkey  [f]
  brought_forward_losses.brought_forward_losses_loss_type_check  [c]
  brought_forward_losses.brought_forward_losses_original_amount_paise_check  [c]
  brought_forward_losses.chk_remaining_consistency  [c]
  brought_forward_losses.chk_utilized_lte_original  [c]
  einvoice_records.einvoice_records_created_by_fkey  [f]
  einvoice_records.einvoice_records_sales_invoice_id_fkey  [f]
  einvoice_records.einvoice_records_status_check  [c]
  eway_bill_records.eway_bill_records_created_by_fkey  [f]
  eway_bill_records.eway_bill_records_sales_invoice_id_fkey  [f]
  eway_bill_records.eway_bill_records_status_check  [c]
  eway_bill_records.eway_bill_records_taxable_value_paise_check  [c]
  eway_bill_records.eway_bill_records_transport_mode_check  [c]
  eway_bill_records.eway_bill_records_vehicle_type_check  [c]
  form_26as_reconciliations.form_26as_reconciliations_completed_by_fkey  [f]
  form_26as_reconciliations.form_26as_reconciliations_created_by_fkey  [f]
  form_26as_reconciliations.form_26as_reconciliations_status_check  [c]
  form_26as_reconciliations.form_26as_reconciliations_upload_id_fkey  [f]
  form_26as_records.form_26as_records_matched_tds_deduction_id_fkey  [f]
  form_26as_records.form_26as_records_reconciliation_status_check  [c]
  form_26as_records.form_26as_records_upload_id_fkey  [f]
  form_26as_uploads.form_26as_uploads_client_id_fkey  [f]
  form_26as_uploads.form_26as_uploads_document_id_fkey  [f]
  form_26as_uploads.form_26as_uploads_firm_id_fkey  [f]
  form_26as_uploads.form_26as_uploads_uploaded_by_fkey  [f]
  gst_portal_snapshots.gst_portal_snapshots_snapshot_type_check  [c]
  gst_sync_jobs.gst_sync_jobs_status_check  [c]
  gst_sync_jobs.gst_sync_jobs_sync_type_check  [c]
  gst_sync_jobs.gst_sync_jobs_triggered_by_fkey  [f]
  itr_filing_versions.itr_filing_versions_created_by_fkey  [f]
  itr_filing_versions.itr_filing_versions_itr_filing_id_version_key  [u]
  itr_filings.itr_filings_computation_snapshot_id_fkey  [f]
  itr_filings.itr_filings_created_by_fkey  [f]
  itr_filings.itr_filings_firm_id_client_id_financial_year_itr_form_key  [u]
  itr_filings.itr_filings_itr_form_check  [c]
  itr_filings.itr_filings_partner_reviewed_by_fkey  [f]
  itr_filings.itr_filings_reviewed_by_fkey  [f]
  itr_filings.itr_filings_status_check  [c]
  tally_migration_items.tally_migration_items_item_type_check  [c]
  tally_migration_items.tally_migration_items_status_check  [c]
  tally_migration_jobs.tally_migration_jobs_created_by_fkey  [f]
  tally_migration_jobs.tally_migration_jobs_rolled_back_by_fkey  [f]
  tally_migration_jobs.tally_migration_jobs_status_check  [c]
  task_escalations.task_escalations_escalation_type_check  [c]
  tax_computation_snapshots.tax_computation_snapshots_created_by_fkey  [f]
  tax_computation_snapshots.tax_computation_snapshots_firm_id_client_id_financial_year__key  [u]
  tax_computation_snapshots.tax_computation_snapshots_regime_check  [c]
  tax_computation_snapshots.tax_computation_snapshots_reviewed_by_fkey  [f]
  tax_computation_snapshots.tax_computation_snapshots_status_check  [c]
  tax_deduction_claims.tax_deduction_claims_claimed_amount_paise_check  [c]
  tax_deduction_claims.tax_deduction_claims_created_by_fkey  [f]
  tax_deduction_claims.tax_deduction_claims_evidence_document_id_fkey  [f]
  tax_deduction_claims.tax_deduction_claims_status_check  [c]
  tax_disallowances.tax_disallowances_amount_paise_check  [c]
  tax_disallowances.tax_disallowances_created_by_fkey  [f]
  tax_disallowances.tax_disallowances_evidence_document_id_fkey  [f]
  tax_disallowances.tax_disallowances_journal_entry_id_fkey  [f]
  tax_disallowances.tax_disallowances_status_check  [c]
  xbrl_packages.xbrl_packages_created_by_fkey  [f]
  xbrl_packages.xbrl_packages_reviewed_by_fkey  [f]
  xbrl_packages.xbrl_packages_status_check  [c]
  xbrl_packages.xbrl_packages_year_end_engagement_id_fkey  [f]

Constraints whose type or definition differs  (29)
--------------------------------------------
  brought_forward_losses.brought_forward_losses_client_id_fkey: definition differs
  brought_forward_losses.brought_forward_losses_firm_id_fkey: definition differs
  einvoice_records.einvoice_records_client_id_fkey: definition differs
  einvoice_records.einvoice_records_firm_id_fkey: definition differs
  eway_bill_records.eway_bill_records_client_id_fkey: definition differs
  eway_bill_records.eway_bill_records_firm_id_fkey: definition differs
  form_26as_reconciliations.form_26as_reconciliations_client_id_fkey: definition differs
  form_26as_reconciliations.form_26as_reconciliations_firm_id_fkey: definition differs
  form_26as_records.form_26as_records_client_id_fkey: definition differs
  form_26as_records.form_26as_records_firm_id_fkey: definition differs
  gst_portal_snapshots.gst_portal_snapshots_client_id_fkey: definition differs
  gst_portal_snapshots.gst_portal_snapshots_firm_id_fkey: definition differs
  gst_sync_jobs.gst_sync_jobs_client_id_fkey: definition differs
  gst_sync_jobs.gst_sync_jobs_firm_id_fkey: definition differs
  itr_filing_versions.itr_filing_versions_firm_id_fkey: definition differs
  itr_filing_versions.itr_filing_versions_itr_filing_id_fkey: definition differs
  itr_filings.itr_filings_client_id_fkey: definition differs
  itr_filings.itr_filings_firm_id_fkey: definition differs
  tally_migration_items.tally_migration_items_firm_id_fkey: definition differs
  tally_migration_items.tally_migration_items_job_id_fkey: definition differs
  tally_migration_jobs.tally_migration_jobs_firm_id_fkey: definition differs
  tax_computation_snapshots.tax_computation_snapshots_client_id_fkey: definition differs
  tax_computation_snapshots.tax_computation_snapshots_firm_id_fkey: definition differs
  tax_deduction_claims.tax_deduction_claims_client_id_fkey: definition differs
  tax_deduction_claims.tax_deduction_claims_firm_id_fkey: definition differs
  tax_disallowances.tax_disallowances_client_id_fkey: definition differs
  tax_disallowances.tax_disallowances_firm_id_fkey: definition differs
  xbrl_packages.xbrl_packages_client_id_fkey: definition differs
  xbrl_packages.xbrl_packages_firm_id_fkey: definition differs

276 difference(s).
```
