-- Migration 319: the guards production enforces and no migration declared
--
-- The guard comparison added in 316 found 62 constraints and 77 policies that
-- exist in the live database and in no migration in this repository. They came
-- from Supabase Studio migrations the repo never had — the same story
-- migration 252 tells for the tables themselves.
--
-- WHY DECLARING THEM MATTERS
--
-- This is the "migration 292 pattern": say in the migrations what production
-- already enforces. In production every statement below is a no-op, guarded on
-- its own existence. Everywhere else — the CI template that every test in this
-- suite runs against, and any new environment — they start enforcing what
-- production has always enforced.
--
-- That direction is the dangerous one, and it is not hypothetical. Reading the
-- first run of this comparison turned up three writes the code makes that
-- production refuses (migration 318 and its commit): a client-portal upload
-- rejected by a foreign key, a GST sync status outside its CHECK, a Tally job
-- status outside its CHECK. Each passed every test here, because the template
-- had none of those constraints.
--
-- WHAT IS DECLARED
--
--   59 constraints — 31 foreign keys, 25 CHECKs, 3 UNIQUEs — across 17 tables.
--   52 policies — 37 permissive, 15 RESTRICTIVE — across 37 tables.
--
-- Each was verified individually against a clone of the migration-built
-- template before being written here: the statement runs, and for a CHECK
-- nothing in the repository writes a value it would reject. The RESTRICTIVE
-- policies are the ones that matter most — a restrictive policy is a check
-- EVERY row must pass, so its absence widens what a caller can reach, and 15 of
-- them (the *_assignment_scope family of migrations 260/261) existed only in
-- production.
--
-- WHAT IS DELIBERATELY NOT DECLARED, AND WHY
--
-- Declaring "what production has" is not uniformly right, because some of what
-- production has is stale. Left out on purpose:
--
--   * The 8 firm_iso_wf_* policies on the workflow tables. Their predicate is
--     firm_id = current_setting('app.current_firm_id', true)::uuid. That GUC
--     appears NOWHERE in this repository, so nothing sets it and the policy
--     admits nothing; the migrations declare firm_isolation on the same tables
--     using the current helper get_my_firm_id(). Copying the legacy mechanism
--     into the migrations would entrench a superseded one.
--
--   * The 7 firm_iso_* policies on the ai_* tables, for the same reason: each
--     table already carries a declared *_firm_isolation policy with the current
--     predicate, and a second PERMISSIVE policy is OR'd with the first.
--
--   * audit_log_own_firm. The migrations declare audit_log_partner_read;
--     production's policy lets the whole firm read the audit log. That is a
--     change to who can read, in the widening direction, and belongs to
--     whoever owns the audit trail.
--
--   * 6 policies on purchase_bills, receipts, receipt_allocations,
--     credit_notes, credit_note_lines and client_sales_invoice_lines.
--     Migration 053 explicitly DROPPED these names and replaced them with
--     firm_client_isolation, which additionally requires the client to belong
--     to the firm. Production still runs the older, weaker ones. The right
--     direction there is to bring PRODUCTION up to the stricter policy, not to
--     copy the weaker one down — recorded as its own task.
--
--   * client_profiles_firm_id_client_id_key, already recorded in the 316 audit:
--     production violates it on purpose because profiles are versioned, so the
--     declaration is what is wrong.
--
-- Everything above is written up in
-- docs/audits/2026-09-03-guard-drift-first-run.md.

-- ── Constraints ─────────────────────────────────────────────────────────────
DO $mig$
DECLARE
  spec record;
BEGIN
  FOR spec IN
    SELECT * FROM (VALUES
      ($d$brought_forward_losses$d$, $d$brought_forward_losses_created_by_fkey$d$, $d$FOREIGN KEY (created_by) REFERENCES users(id)$d$),
      ($d$brought_forward_losses$d$, $d$brought_forward_losses_loss_type_check$d$, $d$CHECK ((loss_type = ANY (ARRAY['business'::text, 'speculation'::text, 'capital_short_term'::text, 'capital_long_term'::text, 'house_property'::text, 'other'::text])))$d$),
      ($d$brought_forward_losses$d$, $d$brought_forward_losses_original_amount_paise_check$d$, $d$CHECK ((original_amount_paise >= 0))$d$),
      ($d$brought_forward_losses$d$, $d$chk_remaining_consistency$d$, $d$CHECK ((remaining_amount_paise = (original_amount_paise - utilized_amount_paise)))$d$),
      ($d$brought_forward_losses$d$, $d$chk_utilized_lte_original$d$, $d$CHECK ((utilized_amount_paise <= original_amount_paise))$d$),
      ($d$einvoice_records$d$, $d$einvoice_records_created_by_fkey$d$, $d$FOREIGN KEY (created_by) REFERENCES users(id)$d$),
      ($d$einvoice_records$d$, $d$einvoice_records_sales_invoice_id_fkey$d$, $d$FOREIGN KEY (sales_invoice_id) REFERENCES client_sales_invoices(id)$d$),
      ($d$einvoice_records$d$, $d$einvoice_records_status_check$d$, $d$CHECK ((status = ANY (ARRAY['draft'::text, 'generated'::text, 'cancelled'::text])))$d$),
      ($d$eway_bill_records$d$, $d$eway_bill_records_created_by_fkey$d$, $d$FOREIGN KEY (created_by) REFERENCES users(id)$d$),
      ($d$eway_bill_records$d$, $d$eway_bill_records_sales_invoice_id_fkey$d$, $d$FOREIGN KEY (sales_invoice_id) REFERENCES client_sales_invoices(id)$d$),
      ($d$eway_bill_records$d$, $d$eway_bill_records_status_check$d$, $d$CHECK ((status = ANY (ARRAY['draft'::text, 'generated'::text, 'extended'::text, 'cancelled'::text])))$d$),
      ($d$eway_bill_records$d$, $d$eway_bill_records_taxable_value_paise_check$d$, $d$CHECK ((taxable_value_paise >= 0))$d$),
      ($d$eway_bill_records$d$, $d$eway_bill_records_transport_mode_check$d$, $d$CHECK ((transport_mode = ANY (ARRAY['road'::text, 'rail'::text, 'air'::text, 'ship'::text])))$d$),
      ($d$eway_bill_records$d$, $d$eway_bill_records_vehicle_type_check$d$, $d$CHECK ((vehicle_type = ANY (ARRAY['regular'::text, 'over_dimensional'::text])))$d$),
      ($d$form_26as_reconciliations$d$, $d$form_26as_reconciliations_completed_by_fkey$d$, $d$FOREIGN KEY (completed_by) REFERENCES users(id)$d$),
      ($d$form_26as_reconciliations$d$, $d$form_26as_reconciliations_created_by_fkey$d$, $d$FOREIGN KEY (created_by) REFERENCES users(id)$d$),
      ($d$form_26as_reconciliations$d$, $d$form_26as_reconciliations_status_check$d$, $d$CHECK ((status = ANY (ARRAY['pending'::text, 'in_progress'::text, 'completed'::text])))$d$),
      ($d$form_26as_reconciliations$d$, $d$form_26as_reconciliations_upload_id_fkey$d$, $d$FOREIGN KEY (upload_id) REFERENCES form_26as_uploads(id)$d$),
      ($d$form_26as_records$d$, $d$form_26as_records_matched_tds_deduction_id_fkey$d$, $d$FOREIGN KEY (matched_tds_deduction_id) REFERENCES tds_deductions(id)$d$),
      ($d$form_26as_records$d$, $d$form_26as_records_reconciliation_status_check$d$, $d$CHECK ((reconciliation_status = ANY (ARRAY['unmatched'::text, 'matched'::text, 'mismatch'::text, 'duplicate'::text])))$d$),
      ($d$form_26as_records$d$, $d$form_26as_records_upload_id_fkey$d$, $d$FOREIGN KEY (upload_id) REFERENCES form_26as_uploads(id)$d$),
      ($d$form_26as_uploads$d$, $d$form_26as_uploads_client_id_fkey$d$, $d$FOREIGN KEY (client_id) REFERENCES clients(id)$d$),
      ($d$form_26as_uploads$d$, $d$form_26as_uploads_document_id_fkey$d$, $d$FOREIGN KEY (document_id) REFERENCES client_documents(id)$d$),
      ($d$form_26as_uploads$d$, $d$form_26as_uploads_firm_id_fkey$d$, $d$FOREIGN KEY (firm_id) REFERENCES firms(id)$d$),
      ($d$form_26as_uploads$d$, $d$form_26as_uploads_uploaded_by_fkey$d$, $d$FOREIGN KEY (uploaded_by) REFERENCES users(id)$d$),
      ($d$gst_portal_snapshots$d$, $d$gst_portal_snapshots_snapshot_type_check$d$, $d$CHECK ((snapshot_type = ANY (ARRAY['profile'::text, 'filing_status'::text, 'return_history'::text, 'liability_summary'::text, 'gstr1_status'::text, 'gstr3b_status'::text])))$d$),
      ($d$gst_sync_jobs$d$, $d$gst_sync_jobs_sync_type_check$d$, $d$CHECK ((sync_type = ANY (ARRAY['manual'::text, 'scheduled'::text])))$d$),
      ($d$gst_sync_jobs$d$, $d$gst_sync_jobs_triggered_by_fkey$d$, $d$FOREIGN KEY (triggered_by) REFERENCES users(id)$d$),
      ($d$itr_filing_versions$d$, $d$itr_filing_versions_created_by_fkey$d$, $d$FOREIGN KEY (created_by) REFERENCES users(id)$d$),
      ($d$itr_filing_versions$d$, $d$itr_filing_versions_itr_filing_id_version_key$d$, $d$UNIQUE (itr_filing_id, version)$d$),
      ($d$itr_filings$d$, $d$itr_filings_computation_snapshot_id_fkey$d$, $d$FOREIGN KEY (computation_snapshot_id) REFERENCES tax_computation_snapshots(id)$d$),
      ($d$itr_filings$d$, $d$itr_filings_created_by_fkey$d$, $d$FOREIGN KEY (created_by) REFERENCES users(id)$d$),
      ($d$itr_filings$d$, $d$itr_filings_firm_id_client_id_financial_year_itr_form_key$d$, $d$UNIQUE (firm_id, client_id, financial_year, itr_form)$d$),
      ($d$itr_filings$d$, $d$itr_filings_itr_form_check$d$, $d$CHECK ((itr_form = ANY (ARRAY['ITR-1'::text, 'ITR-2'::text, 'ITR-3'::text, 'ITR-4'::text, 'ITR-5'::text, 'ITR-6'::text, 'ITR-7'::text])))$d$),
      ($d$itr_filings$d$, $d$itr_filings_partner_reviewed_by_fkey$d$, $d$FOREIGN KEY (partner_reviewed_by) REFERENCES users(id)$d$),
      ($d$itr_filings$d$, $d$itr_filings_reviewed_by_fkey$d$, $d$FOREIGN KEY (reviewed_by) REFERENCES users(id)$d$),
      ($d$itr_filings$d$, $d$itr_filings_status_check$d$, $d$CHECK ((status = ANY (ARRAY['draft'::text, 'review'::text, 'partner_review'::text, 'ready_for_filing'::text, 'filed'::text])))$d$),
      ($d$tally_migration_items$d$, $d$tally_migration_items_item_type_check$d$, $d$CHECK ((item_type = ANY (ARRAY['ledger'::text, 'journal'::text, 'customer'::text, 'vendor'::text, 'opening_balance'::text, 'master'::text])))$d$),
      ($d$tally_migration_jobs$d$, $d$tally_migration_jobs_created_by_fkey$d$, $d$FOREIGN KEY (created_by) REFERENCES users(id)$d$),
      ($d$tally_migration_jobs$d$, $d$tally_migration_jobs_rolled_back_by_fkey$d$, $d$FOREIGN KEY (rolled_back_by) REFERENCES users(id)$d$),
      ($d$task_escalations$d$, $d$task_escalations_escalation_type_check$d$, $d$CHECK ((escalation_type = ANY (ARRAY['due_soon'::text, 'overdue'::text, 'reassigned'::text])))$d$),
      ($d$tax_computation_snapshots$d$, $d$tax_computation_snapshots_created_by_fkey$d$, $d$FOREIGN KEY (created_by) REFERENCES users(id)$d$),
      ($d$tax_computation_snapshots$d$, $d$tax_computation_snapshots_firm_id_client_id_financial_year__key$d$, $d$UNIQUE (firm_id, client_id, financial_year, version)$d$),
      ($d$tax_computation_snapshots$d$, $d$tax_computation_snapshots_regime_check$d$, $d$CHECK ((regime = ANY (ARRAY['new'::text, 'old'::text])))$d$),
      ($d$tax_computation_snapshots$d$, $d$tax_computation_snapshots_reviewed_by_fkey$d$, $d$FOREIGN KEY (reviewed_by) REFERENCES users(id)$d$),
      ($d$tax_computation_snapshots$d$, $d$tax_computation_snapshots_status_check$d$, $d$CHECK ((status = ANY (ARRAY['draft'::text, 'reviewed'::text, 'finalized'::text])))$d$),
      ($d$tax_deduction_claims$d$, $d$tax_deduction_claims_claimed_amount_paise_check$d$, $d$CHECK ((claimed_amount_paise >= 0))$d$),
      ($d$tax_deduction_claims$d$, $d$tax_deduction_claims_created_by_fkey$d$, $d$FOREIGN KEY (created_by) REFERENCES users(id)$d$),
      ($d$tax_deduction_claims$d$, $d$tax_deduction_claims_evidence_document_id_fkey$d$, $d$FOREIGN KEY (evidence_document_id) REFERENCES client_documents(id)$d$),
      ($d$tax_deduction_claims$d$, $d$tax_deduction_claims_status_check$d$, $d$CHECK ((status = ANY (ARRAY['pending'::text, 'verified'::text, 'rejected'::text])))$d$),
      ($d$tax_disallowances$d$, $d$tax_disallowances_amount_paise_check$d$, $d$CHECK ((amount_paise >= 0))$d$),
      ($d$tax_disallowances$d$, $d$tax_disallowances_created_by_fkey$d$, $d$FOREIGN KEY (created_by) REFERENCES users(id)$d$),
      ($d$tax_disallowances$d$, $d$tax_disallowances_evidence_document_id_fkey$d$, $d$FOREIGN KEY (evidence_document_id) REFERENCES client_documents(id)$d$),
      ($d$tax_disallowances$d$, $d$tax_disallowances_journal_entry_id_fkey$d$, $d$FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id)$d$),
      ($d$tax_disallowances$d$, $d$tax_disallowances_status_check$d$, $d$CHECK ((status = ANY (ARRAY['pending'::text, 'accepted'::text, 'rejected'::text])))$d$),
      ($d$xbrl_packages$d$, $d$xbrl_packages_created_by_fkey$d$, $d$FOREIGN KEY (created_by) REFERENCES users(id)$d$),
      ($d$xbrl_packages$d$, $d$xbrl_packages_reviewed_by_fkey$d$, $d$FOREIGN KEY (reviewed_by) REFERENCES users(id)$d$),
      ($d$xbrl_packages$d$, $d$xbrl_packages_status_check$d$, $d$CHECK ((status = ANY (ARRAY['draft'::text, 'validation_pending'::text, 'validation_failed'::text, 'validated'::text, 'reviewed'::text, 'filed'::text])))$d$),
      ($d$xbrl_packages$d$, $d$xbrl_packages_year_end_engagement_id_fkey$d$, $d$FOREIGN KEY (year_end_engagement_id) REFERENCES year_end_engagements(id)$d$)
    ) AS v(tbl, con, def)
  LOOP
    IF to_regclass('public.' || spec.tbl) IS NULL THEN CONTINUE; END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint
               WHERE conname = spec.con
                 AND conrelid = ('public.' || spec.tbl)::regclass) THEN
      CONTINUE;
    END IF;
    EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I %s',
                   spec.tbl, spec.con, spec.def);
  END LOOP;
END $mig$;

-- ── Policies ────────────────────────────────────────────────────────────────
-- One guarded block each: a policy body is arbitrary SQL and building it by
-- string concatenation in a loop would hide what is being created.

DO $mig$
BEGIN
  IF to_regclass('public.account_group_mappings') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'agm_firm'
                       AND polrelid = 'public.account_group_mappings'::regclass) THEN
    CREATE POLICY "agm_firm" ON public.account_group_mappings
  AS PERMISSIVE FOR ALL
  USING (firm_id = public.get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.brought_forward_losses') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'brought_forward_losses_assignment_scope'
                       AND polrelid = 'public.brought_forward_losses'::regclass) THEN
    CREATE POLICY "brought_forward_losses_assignment_scope" ON public.brought_forward_losses
  AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.brought_forward_losses') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_bf_losses'
                       AND polrelid = 'public.brought_forward_losses'::regclass) THEN
    CREATE POLICY "firm_isolation_bf_losses" ON public.brought_forward_losses
  AS PERMISSIVE FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.client_sales_invoices') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_client_sales_invoices'
                       AND polrelid = 'public.client_sales_invoices'::regclass) THEN
    CREATE POLICY "firm_client_sales_invoices" ON public.client_sales_invoices
    AS PERMISSIVE FOR ALL TO authenticated
    USING (firm_id = get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.credit_note_allocations') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_credit_note_allocations'
                       AND polrelid = 'public.credit_note_allocations'::regclass) THEN
    CREATE POLICY "firm_credit_note_allocations" ON public.credit_note_allocations
    AS PERMISSIVE FOR ALL TO authenticated
    USING (firm_id = get_my_firm_id())
    WITH CHECK (firm_id = get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.einvoice_records') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'einvoice_records_assignment_scope'
                       AND polrelid = 'public.einvoice_records'::regclass) THEN
    CREATE POLICY einvoice_records_assignment_scope ON public.einvoice_records
    AS RESTRICTIVE
    FOR ALL
    USING (public.can_access_client(client_id::text))
    WITH CHECK (public.can_access_client(client_id::text));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.einvoice_records') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_einvoice'
                       AND polrelid = 'public.einvoice_records'::regclass) THEN
    CREATE POLICY firm_isolation_einvoice ON public.einvoice_records
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.eway_bill_records') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'eway_bill_records_assignment_scope'
                       AND polrelid = 'public.eway_bill_records'::regclass) THEN
    CREATE POLICY eway_bill_records_assignment_scope ON public.eway_bill_records
    AS RESTRICTIVE
    FOR ALL
    USING (public.can_access_client(client_id::text))
    WITH CHECK (public.can_access_client(client_id::text));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.eway_bill_records') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_eway_bills'
                       AND polrelid = 'public.eway_bill_records'::regclass) THEN
    CREATE POLICY firm_isolation_eway_bills ON public.eway_bill_records
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.financial_statement_versions') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'financial_statement_versions_assignment_scope'
                       AND polrelid = 'public.financial_statement_versions'::regclass) THEN
    CREATE POLICY "financial_statement_versions_assignment_scope" ON public.financial_statement_versions
  AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.financial_statement_versions') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'fsv_firm'
                       AND polrelid = 'public.financial_statement_versions'::regclass) THEN
    CREATE POLICY "fsv_firm" ON public.financial_statement_versions
  AS PERMISSIVE FOR ALL
  USING (firm_id = public.get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.form_26as_reconciliations') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_26as_recon'
                       AND polrelid = 'public.form_26as_reconciliations'::regclass) THEN
    CREATE POLICY "firm_isolation_26as_recon" ON public.form_26as_reconciliations
  AS PERMISSIVE FOR ALL TO authenticated
  USING (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.form_26as_reconciliations') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'form_26as_reconciliations_assignment_scope'
                       AND polrelid = 'public.form_26as_reconciliations'::regclass) THEN
    CREATE POLICY "form_26as_reconciliations_assignment_scope" ON public.form_26as_reconciliations
  AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.form_26as_records') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_26as_records'
                       AND polrelid = 'public.form_26as_records'::regclass) THEN
    CREATE POLICY "firm_isolation_26as_records" ON public.form_26as_records
  AS PERMISSIVE FOR ALL TO authenticated
  USING (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.form_26as_records') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'form_26as_records_assignment_scope'
                       AND polrelid = 'public.form_26as_records'::regclass) THEN
    CREATE POLICY "form_26as_records_assignment_scope" ON public.form_26as_records
  AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.form_26as_uploads') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_26as_uploads'
                       AND polrelid = 'public.form_26as_uploads'::regclass) THEN
    CREATE POLICY "firm_isolation_26as_uploads" ON public.form_26as_uploads
  AS PERMISSIVE FOR ALL TO authenticated
  USING (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.gst_portal_snapshots') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_gst_snapshots'
                       AND polrelid = 'public.gst_portal_snapshots'::regclass) THEN
    CREATE POLICY firm_isolation_gst_snapshots ON public.gst_portal_snapshots
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.gst_portal_snapshots') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'gst_portal_snapshots_assignment_scope'
                       AND polrelid = 'public.gst_portal_snapshots'::regclass) THEN
    CREATE POLICY gst_portal_snapshots_assignment_scope ON public.gst_portal_snapshots
    AS RESTRICTIVE
    FOR ALL
    USING (public.can_access_client(client_id::text))
    WITH CHECK (public.can_access_client(client_id::text));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.gst_sync_jobs') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_gst_sync_jobs'
                       AND polrelid = 'public.gst_sync_jobs'::regclass) THEN
    CREATE POLICY firm_isolation_gst_sync_jobs ON public.gst_sync_jobs
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.gst_sync_jobs') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'gst_sync_jobs_assignment_scope'
                       AND polrelid = 'public.gst_sync_jobs'::regclass) THEN
    CREATE POLICY gst_sync_jobs_assignment_scope ON public.gst_sync_jobs
    AS RESTRICTIVE
    FOR ALL
    USING (public.can_access_client(client_id::text))
    WITH CHECK (public.can_access_client(client_id::text));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.itr_filing_versions') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_itr_versions'
                       AND polrelid = 'public.itr_filing_versions'::regclass) THEN
    CREATE POLICY "firm_isolation_itr_versions" ON public.itr_filing_versions
  AS PERMISSIVE FOR ALL TO authenticated
  USING (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.itr_filings') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_itr_filings'
                       AND polrelid = 'public.itr_filings'::regclass) THEN
    CREATE POLICY "firm_isolation_itr_filings" ON public.itr_filings
  AS PERMISSIVE FOR ALL TO authenticated
  USING (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.itr_filings') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'itr_filings_assignment_scope'
                       AND polrelid = 'public.itr_filings'::regclass) THEN
    CREATE POLICY "itr_filings_assignment_scope" ON public.itr_filings
  AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.pending_invites') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'pending_invites_own_firm'
                       AND polrelid = 'public.pending_invites'::regclass) THEN
    CREATE POLICY "pending_invites_own_firm" ON public.pending_invites
  AS PERMISSIVE FOR ALL
  USING (firm_id = public.get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.purchase_bill_lines') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_purchase_bill_lines'
                       AND polrelid = 'public.purchase_bill_lines'::regclass) THEN
    CREATE POLICY "firm_purchase_bill_lines" ON public.purchase_bill_lines
  AS PERMISSIVE
  FOR ALL
  TO authenticated
  USING (bill_id IN ( SELECT purchase_bills.id
   FROM purchase_bills
  WHERE (purchase_bills.firm_id = get_my_firm_id())));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.tally_migration_items') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_tally_items'
                       AND polrelid = 'public.tally_migration_items'::regclass) THEN
    CREATE POLICY firm_isolation_tally_items ON public.tally_migration_items
  AS PERMISSIVE
  FOR ALL
  TO authenticated
  USING ((firm_id = get_my_firm_id()))
  WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.tally_migration_jobs') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_tally_jobs'
                       AND polrelid = 'public.tally_migration_jobs'::regclass) THEN
    CREATE POLICY firm_isolation_tally_jobs ON public.tally_migration_jobs
  AS PERMISSIVE
  FOR ALL
  TO authenticated
  USING ((firm_id = get_my_firm_id()))
  WITH CHECK ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.task_dependencies') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'task_dependencies_via_task'
                       AND polrelid = 'public.task_dependencies'::regclass) THEN
    CREATE POLICY task_dependencies_via_task ON public.task_dependencies
  AS PERMISSIVE
  FOR ALL
  USING ((EXISTS ( SELECT 1
   FROM tasks t
  WHERE ((t.id = task_dependencies.task_id) AND (t.firm_id = get_my_firm_id())))));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.task_escalations') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'task_escalations_via_task'
                       AND polrelid = 'public.task_escalations'::regclass) THEN
    CREATE POLICY task_escalations_via_task ON public.task_escalations
  AS PERMISSIVE
  FOR ALL
  USING ((EXISTS ( SELECT 1
   FROM tasks t
  WHERE ((t.id = task_escalations.task_id) AND (t.firm_id = get_my_firm_id())))));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.task_recurring_configs') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'task_recurring_configs_own_firm'
                       AND polrelid = 'public.task_recurring_configs'::regclass) THEN
    CREATE POLICY task_recurring_configs_own_firm ON public.task_recurring_configs
  AS PERMISSIVE
  FOR ALL
  USING ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.task_tags') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'task_tags_own_firm'
                       AND polrelid = 'public.task_tags'::regclass) THEN
    CREATE POLICY task_tags_own_firm ON public.task_tags
  AS PERMISSIVE
  FOR ALL
  USING ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.task_templates') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'task_templates_own_firm'
                       AND polrelid = 'public.task_templates'::regclass) THEN
    CREATE POLICY task_templates_own_firm ON public.task_templates
  AS PERMISSIVE
  FOR ALL
  USING (((firm_id IS NULL) OR (firm_id = get_my_firm_id())));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.task_timeline_events') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'task_timeline_events_own_firm'
                       AND polrelid = 'public.task_timeline_events'::regclass) THEN
    CREATE POLICY task_timeline_events_own_firm ON public.task_timeline_events
  AS PERMISSIVE
  FOR ALL
  USING ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.tax_computation_snapshots') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_tax_snapshots'
                       AND polrelid = 'public.tax_computation_snapshots'::regclass) THEN
    CREATE POLICY firm_isolation_tax_snapshots ON public.tax_computation_snapshots
    AS PERMISSIVE
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.tax_computation_snapshots') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'tax_computation_snapshots_assignment_scope'
                       AND polrelid = 'public.tax_computation_snapshots'::regclass) THEN
    CREATE POLICY tax_computation_snapshots_assignment_scope ON public.tax_computation_snapshots
    AS RESTRICTIVE
    FOR ALL
    USING (public.can_access_client(client_id::text))
    WITH CHECK (public.can_access_client(client_id::text));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.tax_deduction_claims') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_deduction_claims'
                       AND polrelid = 'public.tax_deduction_claims'::regclass) THEN
    CREATE POLICY firm_isolation_deduction_claims ON public.tax_deduction_claims
    AS PERMISSIVE
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.tax_deduction_claims') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'tax_deduction_claims_assignment_scope'
                       AND polrelid = 'public.tax_deduction_claims'::regclass) THEN
    CREATE POLICY tax_deduction_claims_assignment_scope ON public.tax_deduction_claims
    AS RESTRICTIVE
    FOR ALL
    USING (public.can_access_client(client_id::text))
    WITH CHECK (public.can_access_client(client_id::text));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.tax_disallowances') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_tax_disallowances'
                       AND polrelid = 'public.tax_disallowances'::regclass) THEN
    CREATE POLICY firm_isolation_tax_disallowances ON public.tax_disallowances
    AS PERMISSIVE
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.tax_disallowances') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'tax_disallowances_assignment_scope'
                       AND polrelid = 'public.tax_disallowances'::regclass) THEN
    CREATE POLICY tax_disallowances_assignment_scope ON public.tax_disallowances
    AS RESTRICTIVE
    FOR ALL
    USING (public.can_access_client(client_id::text))
    WITH CHECK (public.can_access_client(client_id::text));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.time_entries') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'time_entries_own_firm'
                       AND polrelid = 'public.time_entries'::regclass) THEN
    CREATE POLICY time_entries_own_firm ON public.time_entries
  AS PERMISSIVE
  FOR ALL
  USING ((firm_id = get_my_firm_id()));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.workflow_approvals') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'workflow_approvals_firm_isolation'
                       AND polrelid = 'public.workflow_approvals'::regclass) THEN
    CREATE POLICY workflow_approvals_firm_isolation ON public.workflow_approvals
  AS PERMISSIVE FOR ALL
  USING (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.workflow_executions') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'workflow_executions_firm_isolation'
                       AND polrelid = 'public.workflow_executions'::regclass) THEN
    CREATE POLICY workflow_executions_firm_isolation ON public.workflow_executions
  AS PERMISSIVE FOR ALL
  USING (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.workflow_failures') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'workflow_failures_firm_isolation'
                       AND polrelid = 'public.workflow_failures'::regclass) THEN
    CREATE POLICY workflow_failures_firm_isolation ON public.workflow_failures
  AS PERMISSIVE FOR ALL
  USING (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.workflow_instances') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'workflow_instances_assignment_scope'
                       AND polrelid = 'public.workflow_instances'::regclass) THEN
    CREATE POLICY workflow_instances_assignment_scope ON public.workflow_instances
  AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.workflow_instances') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'workflow_instances_firm_isolation'
                       AND polrelid = 'public.workflow_instances'::regclass) THEN
    CREATE POLICY workflow_instances_firm_isolation ON public.workflow_instances
  AS PERMISSIVE FOR ALL
  USING (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.workflow_schedules') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'workflow_schedules_firm_isolation'
                       AND polrelid = 'public.workflow_schedules'::regclass) THEN
    CREATE POLICY workflow_schedules_firm_isolation ON public.workflow_schedules
  AS PERMISSIVE FOR ALL
  USING (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.xbrl_packages') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'firm_isolation_xbrl_packages'
                       AND polrelid = 'public.xbrl_packages'::regclass) THEN
    CREATE POLICY firm_isolation_xbrl_packages ON public.xbrl_packages
    AS PERMISSIVE
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.xbrl_packages') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'xbrl_packages_assignment_scope'
                       AND polrelid = 'public.xbrl_packages'::regclass) THEN
    CREATE POLICY xbrl_packages_assignment_scope ON public.xbrl_packages
    AS RESTRICTIVE
    FOR ALL
    USING (public.can_access_client(client_id::text))
    WITH CHECK (public.can_access_client(client_id::text));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.year_end_adjustments') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'yea_firm'
                       AND polrelid = 'public.year_end_adjustments'::regclass) THEN
    CREATE POLICY yea_firm ON public.year_end_adjustments
  AS PERMISSIVE FOR ALL
  USING (firm_id = get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.year_end_engagements') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'yee_firm'
                       AND polrelid = 'public.year_end_engagements'::regclass) THEN
    CREATE POLICY yee_firm ON public.year_end_engagements
  AS PERMISSIVE FOR ALL
  USING (firm_id = get_my_firm_id());
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.year_end_exports') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'year_end_exports_assignment_scope'
                       AND polrelid = 'public.year_end_exports'::regclass) THEN
    CREATE POLICY year_end_exports_assignment_scope ON public.year_end_exports
  AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));
  END IF;
END $mig$;

DO $mig$
BEGIN
  IF to_regclass('public.year_end_exports') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pg_policy
                     WHERE polname = 'yex_firm'
                       AND polrelid = 'public.year_end_exports'::regclass) THEN
    CREATE POLICY yex_firm ON public.year_end_exports
  AS PERMISSIVE FOR ALL
  USING (firm_id = get_my_firm_id());
  END IF;
END $mig$;
