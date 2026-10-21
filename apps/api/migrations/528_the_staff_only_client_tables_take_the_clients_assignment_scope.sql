-- Migration 528 — eleven client tables only the API uses take the client's assignment scope and the internal practice's
-- Partner-only guard, five tables (two of them among the eleven, three with no client of their own) follow the row they belong
-- to, and the guard of three tables with a nullable client learns that a row with no client is not the practice's (POST-A-299,
-- first tranche; the hole 527 named and the catalog rule it added).
--
-- THE HOLE
--
--   Each table below carries a `client_id` and a firm policy (and, for the AIS data, the income-tax workings and the
--   Schedule III tables, a role tier on writes), and nothing per client. Migration 084 gave the tables of its day a
--   RESTRICTIVE assignment scope and 074 gave them the internal practice's Partner-only guard; these were created
--   afterwards, or were left out, on the premise that "nothing reaches them from the browser and the backend bypasses row
--   security". Both halves of that are false: PostgREST answers for every table the signed-in role is granted, and the API
--   reads and writes them under the CALLER's sign-in when USE_USER_JWT is on, the production default (the scheduler's
--   sweep, which has no caller, runs with the service role and is not touched). So a member of the firm assigned to NO
--   client, or to a different one, could select, change and delete another client's rows straight over PostgREST, and
--   insert a row into a client they are not assigned to:
--
--       ais_uploads, ais_records, ais_reconciliations   the Annual Information Statement by PAN: every payer, every
--                                                       amount and the CA's decision on each line
--       income_tax_asset_blocks                         a client's block-of-assets depreciation workings
--       schedule_iii_ratio_inputs, _explanations        the figures and the wording of a client's ratio note
--       schedule_iii_unbilled_reviews                   when a client's unbilled revenue was last reviewed
--       properties                                      a client's house properties (nullable client)
--       recurring_invoice_templates                     what a client is billed, how often, to which customer
--       onboarding_checklists                           a client's onboarding workflow
--       tally_migration_jobs                            a client's Tally import (nullable client)
--
--   and the tables that hang from them read their parent's row through a bare firm policy:
--
--       ais_records -> ais_uploads, ais_reconciliations -> ais_records, tally_migration_items -> tally_migration_jobs
--       (every ledger, customer and vendor parsed out of the client's Tally file), onboarding_checklist_steps ->
--       onboarding_checklists, recurring_invoice_runs -> recurring_invoice_templates
--
--   (`recurring_invoice_template_lines` already follows its template through a subquery, so it follows it here too.)
--
-- WHAT THIS DOES
--
--   1. On each of the eleven: the two RESTRICTIVE FOR ALL policies the parents carry, written the way migrations 525, 526
--      and 527 write them so they are asked once per query and not once per row:
--
--          <table>_assignment_scope       COALESCE(client_id::text IS NULL OR (SELECT get_my_role()) = 'Partner'
--                                                  OR client_id::text IN (SELECT my_assigned_client_ids()), false)
--          <table>_internal_partner_only  (SELECT get_my_role()) = 'Partner'
--                                         OR client_id::text IS DISTINCT FROM (SELECT my_internal_client_id())::text
--
--      in the USING and in the WITH CHECK, so a person cannot insert a row for a client they cannot see, nor move one to
--      it. A row with NO client (`properties` and `tally_migration_jobs` may carry none) stays open to the firm, which is
--      what `can_access_client` and the routes' `filter_by_client` already say of it. THE INTERNAL-PRACTICE GUARD OF THOSE
--      TWO SAYS `client_id IS NULL OR` TOO, and the other nine do not need it: the comparison with the firm's internal
--      client is `NULL IS DISTINCT FROM NULL`, which is FALSE for a client-less row in a firm that has no internal practice
--      (onboarding provisions it non-fatally and migration 405 measured one of two firms in that state), so without the
--      branch the row is hidden from, and refused to, every non-Partner of such a firm: a firm-level Tally job could not be
--      created by a Manager, and the items under it vanished. Migration 074's note that a NULL internal client never hides
--      is true of a row that has a client and not of one that has none. (Found by two of the three independent reviews of
--      this change.)
--   2. On the five children: `<table>_parent_visible`, one RESTRICTIVE FOR ALL policy asking that the row they hang from
--      is one the caller can see (an EXISTS over the parent, read as the caller, so the parent's own scope applies inside
--      it). A child is exactly as visible as its parent, and a child carrying a client of its own (`ais_records`,
--      `ais_reconciliations`) cannot be written onto another client's parent.
--
--   3. The same defect, already live, in `knowledge_articles_internal_partner_only` (migration 079): the table's client is
--      nullable (a firm-wide article carries none) and the guard is the same comparison, so in a firm with no internal
--      practice every firm-wide article is hidden from the Managers and Executives that its own assignment policy admits
--      it to. ALTER POLICY gives it the same `client_id IS NULL OR` branch (the rollback restores 079's expression). It
--      widens nothing that policy meant to hide: a client-less article was never the internal practice's.
--
--   Items 1 and 2 narrow the firm policy already there and cannot widen anything. Nothing a Partner can do changes, and nothing an
--   assigned Manager or Executive does for their own clients changes: every route that reaches these tables asserts the
--   client first (`routers/ais.py`, `routers/income_tax.py`, `routers/recurring_invoices.py`, `routers/lifecycle.py`,
--   `routers/tally_migration.py`, `routers/relationships.py` and the Schedule III services), and no screen reads them
--   over PostgREST. ONE LIST CHANGES FOR A MEMBER WHO IS NOT A PARTNER, AND IT IS THE POINT: `GET /api/relationships/
--   properties` with no client asks for every property of the firm and the route does not narrow it (the other lists,
--   `filter_by_client` on recurring templates, onboarding workflows and Tally jobs, already do), so until now the
--   intelligence page showed an Executive every client's properties; the database now hands it the caller's clients'
--   properties and the ones with no client.
--
--   Every CREATE POLICY below is written out with its name as a literal, on purpose: `test_guards_match_production_pg`
--   excuses a restrictive policy that production does not hold yet only when a migration after its snapshot names it in
--   plain text (527's header says what happens to a name built by `format()`).
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--
--   * A Tally job whose client is deleted keeps its row (`tally_migration_jobs.client_id` is ON DELETE SET NULL), becomes a
--     client-less job and is therefore open to the firm with its items (POST-A-303). Nothing here changes that; before 528
--     every job was open to the firm anyway.
--   * The twelve client tables still on the shrink-only list `tests/fixtures/assignment_scope_exceptions.json` (kind
--     `pending`, POST-A-299): the statutory identity, payroll settings and PT registrations (a read-only grant since 519,
--     and an employee or portal branch to keep), the year locks, engagements, the FX tables, the stock ledger, the party
--     credit tables, the demo filings and the portal sessions.
--   * The eighteen other tables that hang from a client table and carry a bare firm policy (allocations, versions, logs,
--     steps): a second population of the same catalog rule finds them, by the foreign keys, and lists them under
--     `children` in the same file (POST-A-302), to be fixed in the next migration.
--   * `bank_accounts`, the documents and Storage half of POST-A-005, and the SQL function `schedule_iii_ageing` (a
--     SECURITY DEFINER function that reads `schedule_iii_unbilled_reviews`; it takes the client from its caller's
--     arguments and its result does not change).
--
-- Idempotent (DROP POLICY IF EXISTS before each CREATE; ALTER POLICY is a set). Reversible: 528_..._rollback.sql drops the twenty-seven policies
-- and puts knowledge_articles' guard back to 079's expression, which restores the firm-only behaviour and nothing else.
--
-- LOCKS. DROP POLICY and CREATE POLICY take an ACCESS EXCLUSIVE lock on their table until the migration commits (it is one
-- transaction); the fifteen tables are small. A lock_timeout of 15 seconds for this transaction (as 525, 526 and 527 set)
-- makes a long-running transaction that holds one of them fail the migration, to be re-run, instead of queueing every
-- later request on the table behind it.

SELECT set_config('lock_timeout', '15s', true);

-- ── the eleven client tables: the client and the internal practice ──────────────────────────────────────────────

-- ais_uploads: the AIS statement uploaded for a client
DROP POLICY IF EXISTS "ais_uploads_assignment_scope" ON public.ais_uploads;
CREATE POLICY "ais_uploads_assignment_scope" ON public.ais_uploads
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "ais_uploads_internal_partner_only" ON public.ais_uploads;
CREATE POLICY "ais_uploads_internal_partner_only" ON public.ais_uploads
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

-- ais_records: every line of that statement
DROP POLICY IF EXISTS "ais_records_assignment_scope" ON public.ais_records;
CREATE POLICY "ais_records_assignment_scope" ON public.ais_records
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "ais_records_internal_partner_only" ON public.ais_records;
CREATE POLICY "ais_records_internal_partner_only" ON public.ais_records
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

-- ais_reconciliations: the CA's decision on each line
DROP POLICY IF EXISTS "ais_reconciliations_assignment_scope" ON public.ais_reconciliations;
CREATE POLICY "ais_reconciliations_assignment_scope" ON public.ais_reconciliations
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "ais_reconciliations_internal_partner_only" ON public.ais_reconciliations;
CREATE POLICY "ais_reconciliations_internal_partner_only" ON public.ais_reconciliations
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

-- income_tax_asset_blocks: the client's block-of-assets depreciation workings
DROP POLICY IF EXISTS "income_tax_asset_blocks_assignment_scope" ON public.income_tax_asset_blocks;
CREATE POLICY "income_tax_asset_blocks_assignment_scope" ON public.income_tax_asset_blocks
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "income_tax_asset_blocks_internal_partner_only" ON public.income_tax_asset_blocks;
CREATE POLICY "income_tax_asset_blocks_internal_partner_only" ON public.income_tax_asset_blocks
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

-- schedule_iii_ratio_explanations: the client's Schedule III ratio explanations
DROP POLICY IF EXISTS "schedule_iii_ratio_explanations_assignment_scope" ON public.schedule_iii_ratio_explanations;
CREATE POLICY "schedule_iii_ratio_explanations_assignment_scope" ON public.schedule_iii_ratio_explanations
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "schedule_iii_ratio_explanations_internal_partner_only" ON public.schedule_iii_ratio_explanations;
CREATE POLICY "schedule_iii_ratio_explanations_internal_partner_only" ON public.schedule_iii_ratio_explanations
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

-- schedule_iii_ratio_inputs: the client's Schedule III ratio inputs
DROP POLICY IF EXISTS "schedule_iii_ratio_inputs_assignment_scope" ON public.schedule_iii_ratio_inputs;
CREATE POLICY "schedule_iii_ratio_inputs_assignment_scope" ON public.schedule_iii_ratio_inputs
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "schedule_iii_ratio_inputs_internal_partner_only" ON public.schedule_iii_ratio_inputs;
CREATE POLICY "schedule_iii_ratio_inputs_internal_partner_only" ON public.schedule_iii_ratio_inputs
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

-- schedule_iii_unbilled_reviews: the client's unbilled-revenue review dates
DROP POLICY IF EXISTS "schedule_iii_unbilled_reviews_assignment_scope" ON public.schedule_iii_unbilled_reviews;
CREATE POLICY "schedule_iii_unbilled_reviews_assignment_scope" ON public.schedule_iii_unbilled_reviews
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "schedule_iii_unbilled_reviews_internal_partner_only" ON public.schedule_iii_unbilled_reviews;
CREATE POLICY "schedule_iii_unbilled_reviews_internal_partner_only" ON public.schedule_iii_unbilled_reviews
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

-- properties: the client's house properties
DROP POLICY IF EXISTS "properties_assignment_scope" ON public.properties;
CREATE POLICY "properties_assignment_scope" ON public.properties
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "properties_internal_partner_only" ON public.properties;
CREATE POLICY "properties_internal_partner_only" ON public.properties
  AS RESTRICTIVE FOR ALL
  USING ((client_id IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
          OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text))
  WITH CHECK ((client_id IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
               OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text));

-- recurring_invoice_templates: the client's recurring invoice templates
DROP POLICY IF EXISTS "recurring_invoice_templates_assignment_scope" ON public.recurring_invoice_templates;
CREATE POLICY "recurring_invoice_templates_assignment_scope" ON public.recurring_invoice_templates
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "recurring_invoice_templates_internal_partner_only" ON public.recurring_invoice_templates;
CREATE POLICY "recurring_invoice_templates_internal_partner_only" ON public.recurring_invoice_templates
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

-- onboarding_checklists: the client's onboarding workflow
DROP POLICY IF EXISTS "onboarding_checklists_assignment_scope" ON public.onboarding_checklists;
CREATE POLICY "onboarding_checklists_assignment_scope" ON public.onboarding_checklists
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "onboarding_checklists_internal_partner_only" ON public.onboarding_checklists;
CREATE POLICY "onboarding_checklists_internal_partner_only" ON public.onboarding_checklists
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

-- tally_migration_jobs: a client's Tally migration job
DROP POLICY IF EXISTS "tally_migration_jobs_assignment_scope" ON public.tally_migration_jobs;
CREATE POLICY "tally_migration_jobs_assignment_scope" ON public.tally_migration_jobs
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "tally_migration_jobs_internal_partner_only" ON public.tally_migration_jobs;
CREATE POLICY "tally_migration_jobs_internal_partner_only" ON public.tally_migration_jobs
  AS RESTRICTIVE FOR ALL
  USING ((client_id IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
          OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text))
  WITH CHECK ((client_id IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
               OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text));

-- ── the children: each follows the row it hangs from ──────────────────────────────────────────────────────────

DROP POLICY IF EXISTS "ais_records_parent_visible" ON public.ais_records;
CREATE POLICY "ais_records_parent_visible" ON public.ais_records
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.ais_uploads p WHERE p.id = ais_records.upload_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.ais_uploads p WHERE p.id = ais_records.upload_id));

DROP POLICY IF EXISTS "ais_reconciliations_parent_visible" ON public.ais_reconciliations;
CREATE POLICY "ais_reconciliations_parent_visible" ON public.ais_reconciliations
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.ais_records p WHERE p.id = ais_reconciliations.record_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.ais_records p WHERE p.id = ais_reconciliations.record_id));

DROP POLICY IF EXISTS "tally_migration_items_parent_visible" ON public.tally_migration_items;
CREATE POLICY "tally_migration_items_parent_visible" ON public.tally_migration_items
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.tally_migration_jobs p WHERE p.id = tally_migration_items.job_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.tally_migration_jobs p WHERE p.id = tally_migration_items.job_id));

DROP POLICY IF EXISTS "onboarding_checklist_steps_parent_visible" ON public.onboarding_checklist_steps;
CREATE POLICY "onboarding_checklist_steps_parent_visible" ON public.onboarding_checklist_steps
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.onboarding_checklists p WHERE p.id = onboarding_checklist_steps.workflow_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.onboarding_checklists p WHERE p.id = onboarding_checklist_steps.workflow_id));

DROP POLICY IF EXISTS "recurring_invoice_runs_parent_visible" ON public.recurring_invoice_runs;
CREATE POLICY "recurring_invoice_runs_parent_visible" ON public.recurring_invoice_runs
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.recurring_invoice_templates p WHERE p.id = recurring_invoice_runs.template_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.recurring_invoice_templates p WHERE p.id = recurring_invoice_runs.template_id));

-- ── knowledge_articles: the same NULL branch on a guard that already exists (item 3 of the header) ─────────────────────
ALTER POLICY "knowledge_articles_internal_partner_only" ON public.knowledge_articles
  USING ((client_id IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
          OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text))
  WITH CHECK ((client_id IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
               OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text));
