-- Migration 321: converge the last three guard differences with production
--
-- The guard comparison (316) reports three categories where BOTH sides have the
-- object and they disagree. 319 closed everything that was missing; this closes
-- what differs. After it, the only remaining entries are the seven tables
-- production does not have and the objects deliberately not declared, both
-- recorded in docs/audits/2026-09-03-guard-drift-first-run.md.
--
-- ── 1. Twenty-nine foreign keys: the migrations say CASCADE, production does not
--
-- Every one is a client_id, firm_id, job_id or itr_filing_id key on the tables
-- Supabase Studio created. The migrations declare ON DELETE CASCADE; production
-- declares no action, which REFUSES the delete instead.
--
-- Production is right, and the migrations converge to it. Hard-deleting a client
-- under CASCADE would silently destroy that client's ITR filings, tax
-- computation snapshots, disallowances, deduction claims, XBRL packages, 26AS
-- records and e-invoice/e-way records. Those are statutory records. A refused
-- delete is recoverable; a cascaded one is not, and this product soft-deletes
-- clients (deleted_at, status='archived') precisely so that nothing has to be.
--
-- This changes NOTHING in production, which already refuses. It changes the CI
-- template and every new environment, which today would cascade.
--
-- Two foreign keys on these tables are deliberately NOT touched, because
-- production declares them differently ON PURPOSE and the migrations already
-- agree: tally_migration_jobs.client_id and gst_portal_snapshots.sync_job_id are
-- ON DELETE SET NULL — a job outliving its client, and a snapshot outliving the
-- sync that made it, are both meaningful.
--
-- ── 2. Thirty policies: PUBLIC here, authenticated in production
--
-- The migrations' CREATE POLICY has no TO clause, which means PUBLIC — every
-- role, including anon. Production grants each of these to `authenticated`
-- only. Production is the stricter side and the one the Supabase linter
-- recommends, so the declarations converge to it.
--
-- Again a no-op in production. What it prevents is a future migration
-- re-creating one of these from the repository and silently WIDENING it to
-- anon.
--
-- ── 3. Seven tables where production runs the policy migration 053 replaced
--
-- 050 created firm_<table> policies checking only firm_id. 053 dropped them and
-- substituted firm_client_isolation, which additionally requires the client to
-- belong to the firm. Production never received 053's replacement: it still runs
-- the 050 policy under the old name.
--
-- So here, uniquely in this series, PRODUCTION is the side that moves. Each
-- table gets firm_client_isolation and loses the superseded name.
--
-- Checked against production before writing: across the seven tables, 15,916
-- rows, and ZERO would be excluded by the stricter predicate. Nothing a caller
-- can reach today becomes unreachable.
--
-- One of the seven, client_sales_invoices, also needs a correction HERE:
-- migration 319 declared its superseded policy (firm_client_sales_invoices)
-- while deliberately excluding the other six. That was inconsistent, and this
-- drops it so all seven are treated the same way.

-- ── 1. Foreign keys: drop the cascade the migrations declare ────────────────
DO $mig$
DECLARE
  spec record;
BEGIN
  FOR spec IN
    SELECT * FROM (VALUES
      ($q$brought_forward_losses$q$, $q$brought_forward_losses_client_id_fkey$q$, $q$FOREIGN KEY (client_id) REFERENCES clients(id)$q$),
      ($q$brought_forward_losses$q$, $q$brought_forward_losses_firm_id_fkey$q$, $q$FOREIGN KEY (firm_id) REFERENCES firms(id)$q$),
      ($q$einvoice_records$q$, $q$einvoice_records_client_id_fkey$q$, $q$FOREIGN KEY (client_id) REFERENCES clients(id)$q$),
      ($q$einvoice_records$q$, $q$einvoice_records_firm_id_fkey$q$, $q$FOREIGN KEY (firm_id) REFERENCES firms(id)$q$),
      ($q$eway_bill_records$q$, $q$eway_bill_records_client_id_fkey$q$, $q$FOREIGN KEY (client_id) REFERENCES clients(id)$q$),
      ($q$eway_bill_records$q$, $q$eway_bill_records_firm_id_fkey$q$, $q$FOREIGN KEY (firm_id) REFERENCES firms(id)$q$),
      ($q$form_26as_reconciliations$q$, $q$form_26as_reconciliations_client_id_fkey$q$, $q$FOREIGN KEY (client_id) REFERENCES clients(id)$q$),
      ($q$form_26as_reconciliations$q$, $q$form_26as_reconciliations_firm_id_fkey$q$, $q$FOREIGN KEY (firm_id) REFERENCES firms(id)$q$),
      ($q$form_26as_records$q$, $q$form_26as_records_client_id_fkey$q$, $q$FOREIGN KEY (client_id) REFERENCES clients(id)$q$),
      ($q$form_26as_records$q$, $q$form_26as_records_firm_id_fkey$q$, $q$FOREIGN KEY (firm_id) REFERENCES firms(id)$q$),
      ($q$gst_portal_snapshots$q$, $q$gst_portal_snapshots_client_id_fkey$q$, $q$FOREIGN KEY (client_id) REFERENCES clients(id)$q$),
      ($q$gst_portal_snapshots$q$, $q$gst_portal_snapshots_firm_id_fkey$q$, $q$FOREIGN KEY (firm_id) REFERENCES firms(id)$q$),
      ($q$gst_sync_jobs$q$, $q$gst_sync_jobs_client_id_fkey$q$, $q$FOREIGN KEY (client_id) REFERENCES clients(id)$q$),
      ($q$gst_sync_jobs$q$, $q$gst_sync_jobs_firm_id_fkey$q$, $q$FOREIGN KEY (firm_id) REFERENCES firms(id)$q$),
      ($q$itr_filing_versions$q$, $q$itr_filing_versions_firm_id_fkey$q$, $q$FOREIGN KEY (firm_id) REFERENCES firms(id)$q$),
      ($q$itr_filing_versions$q$, $q$itr_filing_versions_itr_filing_id_fkey$q$, $q$FOREIGN KEY (itr_filing_id) REFERENCES itr_filings(id)$q$),
      ($q$itr_filings$q$, $q$itr_filings_client_id_fkey$q$, $q$FOREIGN KEY (client_id) REFERENCES clients(id)$q$),
      ($q$itr_filings$q$, $q$itr_filings_firm_id_fkey$q$, $q$FOREIGN KEY (firm_id) REFERENCES firms(id)$q$),
      ($q$tally_migration_items$q$, $q$tally_migration_items_firm_id_fkey$q$, $q$FOREIGN KEY (firm_id) REFERENCES firms(id)$q$),
      ($q$tally_migration_items$q$, $q$tally_migration_items_job_id_fkey$q$, $q$FOREIGN KEY (job_id) REFERENCES tally_migration_jobs(id)$q$),
      ($q$tally_migration_jobs$q$, $q$tally_migration_jobs_firm_id_fkey$q$, $q$FOREIGN KEY (firm_id) REFERENCES firms(id)$q$),
      ($q$tax_computation_snapshots$q$, $q$tax_computation_snapshots_client_id_fkey$q$, $q$FOREIGN KEY (client_id) REFERENCES clients(id)$q$),
      ($q$tax_computation_snapshots$q$, $q$tax_computation_snapshots_firm_id_fkey$q$, $q$FOREIGN KEY (firm_id) REFERENCES firms(id)$q$),
      ($q$tax_deduction_claims$q$, $q$tax_deduction_claims_client_id_fkey$q$, $q$FOREIGN KEY (client_id) REFERENCES clients(id)$q$),
      ($q$tax_deduction_claims$q$, $q$tax_deduction_claims_firm_id_fkey$q$, $q$FOREIGN KEY (firm_id) REFERENCES firms(id)$q$),
      ($q$tax_disallowances$q$, $q$tax_disallowances_client_id_fkey$q$, $q$FOREIGN KEY (client_id) REFERENCES clients(id)$q$),
      ($q$tax_disallowances$q$, $q$tax_disallowances_firm_id_fkey$q$, $q$FOREIGN KEY (firm_id) REFERENCES firms(id)$q$),
      ($q$xbrl_packages$q$, $q$xbrl_packages_client_id_fkey$q$, $q$FOREIGN KEY (client_id) REFERENCES clients(id)$q$),
      ($q$xbrl_packages$q$, $q$xbrl_packages_firm_id_fkey$q$, $q$FOREIGN KEY (firm_id) REFERENCES firms(id)$q$)
    ) AS v(tbl, con, def)
  LOOP
    IF to_regclass('public.' || spec.tbl) IS NULL THEN CONTINUE; END IF;
    -- Only touch it when it actually differs, so this is a true no-op in
    -- production rather than a drop-and-recreate of a live constraint.
    CONTINUE WHEN EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conname = spec.con
        AND conrelid = ('public.' || spec.tbl)::regclass
        AND pg_get_constraintdef(oid) = spec.def);
    EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT IF EXISTS %I', spec.tbl, spec.con);
    EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I %s', spec.tbl, spec.con, spec.def);
  END LOOP;
END $mig$;

-- ── 2. Policies: TO authenticated, as production has them ───────────────────

DO $mig$
BEGIN
  IF to_regclass('public.activity_logs') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'activity_logs_own_firm' AND p.polrelid = 'public.activity_logs'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS activity_logs_own_firm ON public.activity_logs;
    CREATE POLICY activity_logs_own_firm ON public.activity_logs
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.ai_insights') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'ai_insights_own_firm' AND p.polrelid = 'public.ai_insights'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS ai_insights_own_firm ON public.ai_insights;
    CREATE POLICY ai_insights_own_firm ON public.ai_insights
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.automation_rules') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'automation_rules_own_firm' AND p.polrelid = 'public.automation_rules'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS automation_rules_own_firm ON public.automation_rules;
    CREATE POLICY automation_rules_own_firm ON public.automation_rules
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.bank_reconciliation_matches') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'bank_recon_own_firm' AND p.polrelid = 'public.bank_reconciliation_matches'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS bank_recon_own_firm ON public.bank_reconciliation_matches;
    CREATE POLICY bank_recon_own_firm ON public.bank_reconciliation_matches
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.bank_statements') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'bank_statements_own_firm' AND p.polrelid = 'public.bank_statements'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS bank_statements_own_firm ON public.bank_statements;
    CREATE POLICY bank_statements_own_firm ON public.bank_statements
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.bank_transactions') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'bank_transactions_own_firm' AND p.polrelid = 'public.bank_transactions'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS bank_transactions_own_firm ON public.bank_transactions;
    CREATE POLICY bank_transactions_own_firm ON public.bank_transactions
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.chart_of_accounts') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'chart_of_accounts_own_firm' AND p.polrelid = 'public.chart_of_accounts'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS chart_of_accounts_own_firm ON public.chart_of_accounts;
    CREATE POLICY chart_of_accounts_own_firm ON public.chart_of_accounts
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.client_documents') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'client_documents_own_firm' AND p.polrelid = 'public.client_documents'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS client_documents_own_firm ON public.client_documents;
    CREATE POLICY client_documents_own_firm ON public.client_documents
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.clients') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'clients_own_firm' AND p.polrelid = 'public.clients'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS clients_own_firm ON public.clients;
    CREATE POLICY clients_own_firm ON public.clients
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.compliance_calendar') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'compliance_calendar_own_firm' AND p.polrelid = 'public.compliance_calendar'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS compliance_calendar_own_firm ON public.compliance_calendar;
    CREATE POLICY compliance_calendar_own_firm ON public.compliance_calendar
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.compliance_records') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'compliance_records_own_firm' AND p.polrelid = 'public.compliance_records'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS compliance_records_own_firm ON public.compliance_records;
    CREATE POLICY compliance_records_own_firm ON public.compliance_records
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.document_extractions') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'document_extractions_own_firm' AND p.polrelid = 'public.document_extractions'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS document_extractions_own_firm ON public.document_extractions;
    CREATE POLICY document_extractions_own_firm ON public.document_extractions
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.document_risks') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'document_risks_own_firm' AND p.polrelid = 'public.document_risks'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS document_risks_own_firm ON public.document_risks;
    CREATE POLICY document_risks_own_firm ON public.document_risks
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.documents') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'documents_own_firm' AND p.polrelid = 'public.documents'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS documents_own_firm ON public.documents;
    CREATE POLICY documents_own_firm ON public.documents
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.dsc_records') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'dsc_records_own_firm' AND p.polrelid = 'public.dsc_records'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS dsc_records_own_firm ON public.dsc_records;
    CREATE POLICY dsc_records_own_firm ON public.dsc_records
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.fee_engagements') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'fee_engagements_own_firm' AND p.polrelid = 'public.fee_engagements'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS fee_engagements_own_firm ON public.fee_engagements;
    CREATE POLICY fee_engagements_own_firm ON public.fee_engagements
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.fee_invoices') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'fee_invoices_own_firm' AND p.polrelid = 'public.fee_invoices'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS fee_invoices_own_firm ON public.fee_invoices;
    CREATE POLICY fee_invoices_own_firm ON public.fee_invoices
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.ledger_balances') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'ledger_balances_own_firm' AND p.polrelid = 'public.ledger_balances'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS ledger_balances_own_firm ON public.ledger_balances;
    CREATE POLICY ledger_balances_own_firm ON public.ledger_balances
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.mca_filings') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'mca_filings_own_firm' AND p.polrelid = 'public.mca_filings'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS mca_filings_own_firm ON public.mca_filings;
    CREATE POLICY mca_filings_own_firm ON public.mca_filings
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.msme_vendors') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'msme_vendors_own_firm' AND p.polrelid = 'public.msme_vendors'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS msme_vendors_own_firm ON public.msme_vendors;
    CREATE POLICY msme_vendors_own_firm ON public.msme_vendors
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.notifications') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'notifications_own_firm' AND p.polrelid = 'public.notifications'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS notifications_own_firm ON public.notifications;
    CREATE POLICY notifications_own_firm ON public.notifications
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.payroll_employees') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'payroll_employees_own_firm' AND p.polrelid = 'public.payroll_employees'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS payroll_employees_own_firm ON public.payroll_employees;
    CREATE POLICY payroll_employees_own_firm ON public.payroll_employees
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.payroll_runs') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'payroll_runs_own_firm' AND p.polrelid = 'public.payroll_runs'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS payroll_runs_own_firm ON public.payroll_runs;
    CREATE POLICY payroll_runs_own_firm ON public.payroll_runs
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.retainer_clients') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'retainer_clients_own_firm' AND p.polrelid = 'public.retainer_clients'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS retainer_clients_own_firm ON public.retainer_clients;
    CREATE POLICY retainer_clients_own_firm ON public.retainer_clients
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.retainer_logs') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'retainer_logs_own_firm' AND p.polrelid = 'public.retainer_logs'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS retainer_logs_own_firm ON public.retainer_logs;
    CREATE POLICY retainer_logs_own_firm ON public.retainer_logs
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((retainer_id IN ( SELECT retainer_clients.id FROM retainer_clients WHERE (retainer_clients.firm_id = get_my_firm_id()))))
      WITH CHECK ((retainer_id IN ( SELECT retainer_clients.id FROM retainer_clients WHERE (retainer_clients.firm_id = get_my_firm_id()))));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.tasks') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'tasks_own_firm' AND p.polrelid = 'public.tasks'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS tasks_own_firm ON public.tasks;
    CREATE POLICY tasks_own_firm ON public.tasks
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.tax_audit_checklists') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'tax_audit_own_firm' AND p.polrelid = 'public.tax_audit_checklists'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS tax_audit_own_firm ON public.tax_audit_checklists;
    CREATE POLICY tax_audit_own_firm ON public.tax_audit_checklists
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.tax_notices') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'tax_notices_own_firm' AND p.polrelid = 'public.tax_notices'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS tax_notices_own_firm ON public.tax_notices;
    CREATE POLICY tax_notices_own_firm ON public.tax_notices
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.tax_planning_records') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'tax_planning_own_firm' AND p.polrelid = 'public.tax_planning_records'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS tax_planning_own_firm ON public.tax_planning_records;
    CREATE POLICY tax_planning_own_firm ON public.tax_planning_records
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.tds_deductions') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM pg_policy p JOIN pg_roles r ON r.oid = ANY(p.polroles)
       WHERE p.polname = 'tds_deductions_own_firm' AND p.polrelid = 'public.tds_deductions'::regclass
         AND r.rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS tds_deductions_own_firm ON public.tds_deductions;
    CREATE POLICY tds_deductions_own_firm ON public.tds_deductions
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((firm_id = get_my_firm_id()))
      WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

-- ── 3. The seven tables production still guards with the pre-053 policy ────

DO $mig$
BEGIN
  IF to_regclass('public.client_sales_invoice_lines') IS NULL THEN RETURN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policy
                 WHERE polname = 'firm_client_isolation'
                   AND polrelid = 'public.client_sales_invoice_lines'::regclass) THEN
    CREATE POLICY firm_client_isolation ON public.client_sales_invoice_lines
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((sales_invoice_id IN ( SELECT csi.id FROM client_sales_invoices csi WHERE ((csi.firm_id = get_my_firm_id()) AND (csi.client_id IN ( SELECT clients.id FROM clients WHERE (clients.firm_id = get_my_firm_id())))))));
  END IF;
  -- Only after the replacement exists, so the table is never left unguarded.
  DROP POLICY IF EXISTS firm_client_sales_invoice_lines ON public.client_sales_invoice_lines;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.client_sales_invoices') IS NULL THEN RETURN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policy
                 WHERE polname = 'firm_client_isolation'
                   AND polrelid = 'public.client_sales_invoices'::regclass) THEN
    CREATE POLICY firm_client_isolation ON public.client_sales_invoices
      AS PERMISSIVE FOR ALL TO authenticated
      USING (((firm_id = get_my_firm_id()) AND (client_id IN ( SELECT clients.id FROM clients WHERE (clients.firm_id = get_my_firm_id())))));
  END IF;
  -- Only after the replacement exists, so the table is never left unguarded.
  DROP POLICY IF EXISTS firm_client_sales_invoices ON public.client_sales_invoices;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.credit_note_lines') IS NULL THEN RETURN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policy
                 WHERE polname = 'firm_client_isolation'
                   AND polrelid = 'public.credit_note_lines'::regclass) THEN
    CREATE POLICY firm_client_isolation ON public.credit_note_lines
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((credit_note_id IN ( SELECT cn.id FROM credit_notes cn WHERE ((cn.firm_id = get_my_firm_id()) AND (cn.client_id IN ( SELECT clients.id FROM clients WHERE (clients.firm_id = get_my_firm_id())))))));
  END IF;
  -- Only after the replacement exists, so the table is never left unguarded.
  DROP POLICY IF EXISTS firm_credit_note_lines ON public.credit_note_lines;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.credit_notes') IS NULL THEN RETURN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policy
                 WHERE polname = 'firm_client_isolation'
                   AND polrelid = 'public.credit_notes'::regclass) THEN
    CREATE POLICY firm_client_isolation ON public.credit_notes
      AS PERMISSIVE FOR ALL TO authenticated
      USING (((firm_id = get_my_firm_id()) AND (client_id IN ( SELECT clients.id FROM clients WHERE (clients.firm_id = get_my_firm_id())))));
  END IF;
  -- Only after the replacement exists, so the table is never left unguarded.
  DROP POLICY IF EXISTS firm_credit_notes ON public.credit_notes;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.purchase_bills') IS NULL THEN RETURN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policy
                 WHERE polname = 'firm_client_isolation'
                   AND polrelid = 'public.purchase_bills'::regclass) THEN
    CREATE POLICY firm_client_isolation ON public.purchase_bills
      AS PERMISSIVE FOR ALL TO authenticated
      USING (((firm_id = get_my_firm_id()) AND (client_id IN ( SELECT clients.id FROM clients WHERE (clients.firm_id = get_my_firm_id())))));
  END IF;
  -- Only after the replacement exists, so the table is never left unguarded.
  DROP POLICY IF EXISTS firm_purchase_bills ON public.purchase_bills;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.receipt_allocations') IS NULL THEN RETURN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policy
                 WHERE polname = 'firm_client_isolation'
                   AND polrelid = 'public.receipt_allocations'::regclass) THEN
    CREATE POLICY firm_client_isolation ON public.receipt_allocations
      AS PERMISSIVE FOR ALL TO authenticated
      USING ((receipt_id IN ( SELECT r.id FROM receipts r WHERE ((r.firm_id = get_my_firm_id()) AND (r.client_id IN ( SELECT clients.id FROM clients WHERE (clients.firm_id = get_my_firm_id())))))));
  END IF;
  -- Only after the replacement exists, so the table is never left unguarded.
  DROP POLICY IF EXISTS firm_receipt_allocations ON public.receipt_allocations;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.receipts') IS NULL THEN RETURN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policy
                 WHERE polname = 'firm_client_isolation'
                   AND polrelid = 'public.receipts'::regclass) THEN
    CREATE POLICY firm_client_isolation ON public.receipts
      AS PERMISSIVE FOR ALL TO authenticated
      USING (((firm_id = get_my_firm_id()) AND (client_id IN ( SELECT clients.id FROM clients WHERE (clients.firm_id = get_my_firm_id())))));
  END IF;
  -- Only after the replacement exists, so the table is never left unguarded.
  DROP POLICY IF EXISTS firm_receipts ON public.receipts;
END $mig$;
