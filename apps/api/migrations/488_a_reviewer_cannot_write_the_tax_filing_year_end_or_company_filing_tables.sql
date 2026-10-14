-- Migration 488 — a Reviewer can no longer write the tax, filing, year-end or company-filing tables
-- (security_privacy-34; ledger POST-B-005, second slice of three).
--
-- THE HOLE
--   Seventeen tables carry a firm policy and an assignment scope and no write tier, so a Reviewer assigned to a
--   client inserted, updated and deleted that client's GSTR-1 and GSTR-3B returns, 2A/2B reconciliations, income-tax
--   filings, computation snapshots, disallowances and carried-forward losses, Form 26AS uploads and reconciliations,
--   year-end engagements, adjustments, exports, financial-statement versions and XBRL packages, and company
--   registrations and directors, straight over PostgREST. The API never lets a Reviewer near them. A read-only audit
--   of every writer (routers, services, domain, jobs, the browser, the database's own functions) found no legitimate
--   Reviewer write and no read that writes under the caller's sign-in.
--
-- WHAT THIS DOES
--   RESTRICTIVE per-command policies asking `my_permission(resource, action, floor)`, the function the route's own
--   `rbac()` resolves through, so the per-person grid counts. A command passes if ANY of its pairs does, and the pairs
--   are the ones the table's writing routes ask (a refused UPDATE or DELETE affects zero rows with no error and
--   several handlers index the empty result and answer 500, so a stricter policy than the routes would turn a
--   permitted action into a server error):
--
--     gstr1_returns, gstr3b_returns, gstr2a_records, gstr2b_reconciliations   gst:compute (Executive)
--     itr_filings, tax_computation_snapshots, tax_disallowances
--                      INSERT, DELETE  income_tax:compute (Executive)
--                      UPDATE          income_tax:approve (Manager): every UPDATE route is an approval or a transition
--     brought_forward_losses, form_26as_reconciliations      income_tax:compute
--     form_26as_uploads                                      income_tax:compute OR tds:compute (two upload doors)
--     xbrl_packages, year_end_engagements
--                      INSERT, DELETE  year_end:write (Executive)
--                      UPDATE          year_end:write OR year_end:approve (Manager) OR year_end:final_approve (Partner)
--     year_end_adjustments    INSERT, DELETE year_end:write;  UPDATE year_end:write OR year_end:approve
--     year_end_exports, financial_statement_versions         year_end:write
--     mca_companies, mca_directors                           mca:write (Executive)
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * THE BROWSER STILL APPROVES A GST RETURN WITHOUT THE API. lib/data/gst.ts sets `ca_approved` on gstr1_returns and
--     gstr3b_returns over PostgREST, and a row policy cannot tell an approval from any other UPDATE, so an Executive
--     (gst:compute) can still do it here; the API door that checks gst:approve exists and the screens do not use it
--     (ledger POST-A-223).
--   * The definer functions that write gstr2a_records and gstr2b_reconciliations (replace_gstr2b_reconciliation) bypass
--     these policies by design and ask who is calling since migration 486.
--   * SELECT is untouched. The last nine tables of the class are the next migration.
--   * No function, grant, table or row changes. No backfill.
--
-- Idempotent: DROP POLICY IF EXISTS before each CREATE, and the closing check fails the migration if any policy is
-- missing. Reversible: 488_..._rollback.sql drops them, which RE-OPENS the hole.
-- ── gstr1_returns ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "gstr1_returns_write_tier_insert" ON public.gstr1_returns;
CREATE POLICY "gstr1_returns_write_tier_insert" ON public.gstr1_returns
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('gst', 'compute', 'Executive'));

DROP POLICY IF EXISTS "gstr1_returns_write_tier_update" ON public.gstr1_returns;
CREATE POLICY "gstr1_returns_write_tier_update" ON public.gstr1_returns
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('gst', 'compute', 'Executive'))
  WITH CHECK (public.my_permission('gst', 'compute', 'Executive'));

DROP POLICY IF EXISTS "gstr1_returns_write_tier_delete" ON public.gstr1_returns;
CREATE POLICY "gstr1_returns_write_tier_delete" ON public.gstr1_returns
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('gst', 'compute', 'Executive'));

-- ── gstr3b_returns ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "gstr3b_returns_write_tier_insert" ON public.gstr3b_returns;
CREATE POLICY "gstr3b_returns_write_tier_insert" ON public.gstr3b_returns
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('gst', 'compute', 'Executive'));

DROP POLICY IF EXISTS "gstr3b_returns_write_tier_update" ON public.gstr3b_returns;
CREATE POLICY "gstr3b_returns_write_tier_update" ON public.gstr3b_returns
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('gst', 'compute', 'Executive'))
  WITH CHECK (public.my_permission('gst', 'compute', 'Executive'));

DROP POLICY IF EXISTS "gstr3b_returns_write_tier_delete" ON public.gstr3b_returns;
CREATE POLICY "gstr3b_returns_write_tier_delete" ON public.gstr3b_returns
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('gst', 'compute', 'Executive'));

-- ── gstr2a_records ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "gstr2a_records_write_tier_insert" ON public.gstr2a_records;
CREATE POLICY "gstr2a_records_write_tier_insert" ON public.gstr2a_records
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('gst', 'compute', 'Executive'));

DROP POLICY IF EXISTS "gstr2a_records_write_tier_update" ON public.gstr2a_records;
CREATE POLICY "gstr2a_records_write_tier_update" ON public.gstr2a_records
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('gst', 'compute', 'Executive'))
  WITH CHECK (public.my_permission('gst', 'compute', 'Executive'));

DROP POLICY IF EXISTS "gstr2a_records_write_tier_delete" ON public.gstr2a_records;
CREATE POLICY "gstr2a_records_write_tier_delete" ON public.gstr2a_records
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('gst', 'compute', 'Executive'));

-- ── gstr2b_reconciliations ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "gstr2b_reconciliations_write_tier_insert" ON public.gstr2b_reconciliations;
CREATE POLICY "gstr2b_reconciliations_write_tier_insert" ON public.gstr2b_reconciliations
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('gst', 'compute', 'Executive'));

DROP POLICY IF EXISTS "gstr2b_reconciliations_write_tier_update" ON public.gstr2b_reconciliations;
CREATE POLICY "gstr2b_reconciliations_write_tier_update" ON public.gstr2b_reconciliations
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('gst', 'compute', 'Executive'))
  WITH CHECK (public.my_permission('gst', 'compute', 'Executive'));

DROP POLICY IF EXISTS "gstr2b_reconciliations_write_tier_delete" ON public.gstr2b_reconciliations;
CREATE POLICY "gstr2b_reconciliations_write_tier_delete" ON public.gstr2b_reconciliations
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('gst', 'compute', 'Executive'));

-- ── itr_filings ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "itr_filings_write_tier_insert" ON public.itr_filings;
CREATE POLICY "itr_filings_write_tier_insert" ON public.itr_filings
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('income_tax', 'compute', 'Executive'));

DROP POLICY IF EXISTS "itr_filings_write_tier_update" ON public.itr_filings;
CREATE POLICY "itr_filings_write_tier_update" ON public.itr_filings
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('income_tax', 'approve', 'Manager'))
  WITH CHECK (public.my_permission('income_tax', 'approve', 'Manager'));

DROP POLICY IF EXISTS "itr_filings_write_tier_delete" ON public.itr_filings;
CREATE POLICY "itr_filings_write_tier_delete" ON public.itr_filings
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('income_tax', 'compute', 'Executive'));

-- ── tax_computation_snapshots ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "tax_computation_snapshots_write_tier_insert" ON public.tax_computation_snapshots;
CREATE POLICY "tax_computation_snapshots_write_tier_insert" ON public.tax_computation_snapshots
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('income_tax', 'compute', 'Executive'));

DROP POLICY IF EXISTS "tax_computation_snapshots_write_tier_update" ON public.tax_computation_snapshots;
CREATE POLICY "tax_computation_snapshots_write_tier_update" ON public.tax_computation_snapshots
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('income_tax', 'approve', 'Manager'))
  WITH CHECK (public.my_permission('income_tax', 'approve', 'Manager'));

DROP POLICY IF EXISTS "tax_computation_snapshots_write_tier_delete" ON public.tax_computation_snapshots;
CREATE POLICY "tax_computation_snapshots_write_tier_delete" ON public.tax_computation_snapshots
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('income_tax', 'compute', 'Executive'));

-- ── tax_disallowances ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "tax_disallowances_write_tier_insert" ON public.tax_disallowances;
CREATE POLICY "tax_disallowances_write_tier_insert" ON public.tax_disallowances
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('income_tax', 'compute', 'Executive'));

DROP POLICY IF EXISTS "tax_disallowances_write_tier_update" ON public.tax_disallowances;
CREATE POLICY "tax_disallowances_write_tier_update" ON public.tax_disallowances
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('income_tax', 'approve', 'Manager'))
  WITH CHECK (public.my_permission('income_tax', 'approve', 'Manager'));

DROP POLICY IF EXISTS "tax_disallowances_write_tier_delete" ON public.tax_disallowances;
CREATE POLICY "tax_disallowances_write_tier_delete" ON public.tax_disallowances
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('income_tax', 'compute', 'Executive'));

-- ── brought_forward_losses ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "brought_forward_losses_write_tier_insert" ON public.brought_forward_losses;
CREATE POLICY "brought_forward_losses_write_tier_insert" ON public.brought_forward_losses
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('income_tax', 'compute', 'Executive'));

DROP POLICY IF EXISTS "brought_forward_losses_write_tier_update" ON public.brought_forward_losses;
CREATE POLICY "brought_forward_losses_write_tier_update" ON public.brought_forward_losses
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('income_tax', 'compute', 'Executive'))
  WITH CHECK (public.my_permission('income_tax', 'compute', 'Executive'));

DROP POLICY IF EXISTS "brought_forward_losses_write_tier_delete" ON public.brought_forward_losses;
CREATE POLICY "brought_forward_losses_write_tier_delete" ON public.brought_forward_losses
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('income_tax', 'compute', 'Executive'));

-- ── form_26as_uploads ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "form_26as_uploads_write_tier_insert" ON public.form_26as_uploads;
CREATE POLICY "form_26as_uploads_write_tier_insert" ON public.form_26as_uploads
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK ((public.my_permission('income_tax', 'compute', 'Executive')
          OR public.my_permission('tds', 'compute', 'Executive')));

DROP POLICY IF EXISTS "form_26as_uploads_write_tier_update" ON public.form_26as_uploads;
CREATE POLICY "form_26as_uploads_write_tier_update" ON public.form_26as_uploads
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('income_tax', 'compute', 'Executive'))
  WITH CHECK (public.my_permission('income_tax', 'compute', 'Executive'));

DROP POLICY IF EXISTS "form_26as_uploads_write_tier_delete" ON public.form_26as_uploads;
CREATE POLICY "form_26as_uploads_write_tier_delete" ON public.form_26as_uploads
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING ((public.my_permission('income_tax', 'compute', 'Executive')
          OR public.my_permission('tds', 'compute', 'Executive')));

-- ── form_26as_reconciliations ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "form_26as_reconciliations_write_tier_insert" ON public.form_26as_reconciliations;
CREATE POLICY "form_26as_reconciliations_write_tier_insert" ON public.form_26as_reconciliations
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('income_tax', 'compute', 'Executive'));

DROP POLICY IF EXISTS "form_26as_reconciliations_write_tier_update" ON public.form_26as_reconciliations;
CREATE POLICY "form_26as_reconciliations_write_tier_update" ON public.form_26as_reconciliations
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('income_tax', 'compute', 'Executive'))
  WITH CHECK (public.my_permission('income_tax', 'compute', 'Executive'));

DROP POLICY IF EXISTS "form_26as_reconciliations_write_tier_delete" ON public.form_26as_reconciliations;
CREATE POLICY "form_26as_reconciliations_write_tier_delete" ON public.form_26as_reconciliations
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('income_tax', 'compute', 'Executive'));

-- ── xbrl_packages ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "xbrl_packages_write_tier_insert" ON public.xbrl_packages;
CREATE POLICY "xbrl_packages_write_tier_insert" ON public.xbrl_packages
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('year_end', 'write', 'Executive'));

DROP POLICY IF EXISTS "xbrl_packages_write_tier_update" ON public.xbrl_packages;
CREATE POLICY "xbrl_packages_write_tier_update" ON public.xbrl_packages
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING ((public.my_permission('year_end', 'write', 'Executive')
          OR public.my_permission('year_end', 'approve', 'Manager')
          OR public.my_permission('year_end', 'final_approve', 'Partner')))
  WITH CHECK ((public.my_permission('year_end', 'write', 'Executive')
          OR public.my_permission('year_end', 'approve', 'Manager')
          OR public.my_permission('year_end', 'final_approve', 'Partner')));

DROP POLICY IF EXISTS "xbrl_packages_write_tier_delete" ON public.xbrl_packages;
CREATE POLICY "xbrl_packages_write_tier_delete" ON public.xbrl_packages
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('year_end', 'write', 'Executive'));

-- ── year_end_adjustments ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "year_end_adjustments_write_tier_insert" ON public.year_end_adjustments;
CREATE POLICY "year_end_adjustments_write_tier_insert" ON public.year_end_adjustments
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('year_end', 'write', 'Executive'));

DROP POLICY IF EXISTS "year_end_adjustments_write_tier_update" ON public.year_end_adjustments;
CREATE POLICY "year_end_adjustments_write_tier_update" ON public.year_end_adjustments
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING ((public.my_permission('year_end', 'write', 'Executive')
          OR public.my_permission('year_end', 'approve', 'Manager')))
  WITH CHECK ((public.my_permission('year_end', 'write', 'Executive')
          OR public.my_permission('year_end', 'approve', 'Manager')));

DROP POLICY IF EXISTS "year_end_adjustments_write_tier_delete" ON public.year_end_adjustments;
CREATE POLICY "year_end_adjustments_write_tier_delete" ON public.year_end_adjustments
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('year_end', 'write', 'Executive'));

-- ── year_end_engagements ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "year_end_engagements_write_tier_insert" ON public.year_end_engagements;
CREATE POLICY "year_end_engagements_write_tier_insert" ON public.year_end_engagements
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('year_end', 'write', 'Executive'));

DROP POLICY IF EXISTS "year_end_engagements_write_tier_update" ON public.year_end_engagements;
CREATE POLICY "year_end_engagements_write_tier_update" ON public.year_end_engagements
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING ((public.my_permission('year_end', 'write', 'Executive')
          OR public.my_permission('year_end', 'approve', 'Manager')
          OR public.my_permission('year_end', 'final_approve', 'Partner')))
  WITH CHECK ((public.my_permission('year_end', 'write', 'Executive')
          OR public.my_permission('year_end', 'approve', 'Manager')
          OR public.my_permission('year_end', 'final_approve', 'Partner')));

DROP POLICY IF EXISTS "year_end_engagements_write_tier_delete" ON public.year_end_engagements;
CREATE POLICY "year_end_engagements_write_tier_delete" ON public.year_end_engagements
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('year_end', 'write', 'Executive'));

-- ── year_end_exports ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "year_end_exports_write_tier_insert" ON public.year_end_exports;
CREATE POLICY "year_end_exports_write_tier_insert" ON public.year_end_exports
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('year_end', 'write', 'Executive'));

DROP POLICY IF EXISTS "year_end_exports_write_tier_update" ON public.year_end_exports;
CREATE POLICY "year_end_exports_write_tier_update" ON public.year_end_exports
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('year_end', 'write', 'Executive'))
  WITH CHECK (public.my_permission('year_end', 'write', 'Executive'));

DROP POLICY IF EXISTS "year_end_exports_write_tier_delete" ON public.year_end_exports;
CREATE POLICY "year_end_exports_write_tier_delete" ON public.year_end_exports
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('year_end', 'write', 'Executive'));

-- ── financial_statement_versions ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "financial_statement_versions_write_tier_insert" ON public.financial_statement_versions;
CREATE POLICY "financial_statement_versions_write_tier_insert" ON public.financial_statement_versions
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('year_end', 'write', 'Executive'));

DROP POLICY IF EXISTS "financial_statement_versions_write_tier_update" ON public.financial_statement_versions;
CREATE POLICY "financial_statement_versions_write_tier_update" ON public.financial_statement_versions
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('year_end', 'write', 'Executive'))
  WITH CHECK (public.my_permission('year_end', 'write', 'Executive'));

DROP POLICY IF EXISTS "financial_statement_versions_write_tier_delete" ON public.financial_statement_versions;
CREATE POLICY "financial_statement_versions_write_tier_delete" ON public.financial_statement_versions
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('year_end', 'write', 'Executive'));

-- ── mca_companies ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "mca_companies_write_tier_insert" ON public.mca_companies;
CREATE POLICY "mca_companies_write_tier_insert" ON public.mca_companies
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('mca', 'write', 'Executive'));

DROP POLICY IF EXISTS "mca_companies_write_tier_update" ON public.mca_companies;
CREATE POLICY "mca_companies_write_tier_update" ON public.mca_companies
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('mca', 'write', 'Executive'))
  WITH CHECK (public.my_permission('mca', 'write', 'Executive'));

DROP POLICY IF EXISTS "mca_companies_write_tier_delete" ON public.mca_companies;
CREATE POLICY "mca_companies_write_tier_delete" ON public.mca_companies
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('mca', 'write', 'Executive'));

-- ── mca_directors ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "mca_directors_write_tier_insert" ON public.mca_directors;
CREATE POLICY "mca_directors_write_tier_insert" ON public.mca_directors
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('mca', 'write', 'Executive'));

DROP POLICY IF EXISTS "mca_directors_write_tier_update" ON public.mca_directors;
CREATE POLICY "mca_directors_write_tier_update" ON public.mca_directors
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('mca', 'write', 'Executive'))
  WITH CHECK (public.my_permission('mca', 'write', 'Executive'));

DROP POLICY IF EXISTS "mca_directors_write_tier_delete" ON public.mca_directors;
CREATE POLICY "mca_directors_write_tier_delete" ON public.mca_directors
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('mca', 'write', 'Executive'));

-- ── the closing check: all 51 policies exist and every one is RESTRICTIVE ───────────────────────
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n
    FROM pg_policies
   WHERE schemaname = 'public'
     AND permissive = 'RESTRICTIVE'
     AND policyname IN (
       'gstr1_returns_write_tier_insert',
       'gstr1_returns_write_tier_update',
       'gstr1_returns_write_tier_delete',
       'gstr3b_returns_write_tier_insert',
       'gstr3b_returns_write_tier_update',
       'gstr3b_returns_write_tier_delete',
       'gstr2a_records_write_tier_insert',
       'gstr2a_records_write_tier_update',
       'gstr2a_records_write_tier_delete',
       'gstr2b_reconciliations_write_tier_insert',
       'gstr2b_reconciliations_write_tier_update',
       'gstr2b_reconciliations_write_tier_delete',
       'itr_filings_write_tier_insert',
       'itr_filings_write_tier_update',
       'itr_filings_write_tier_delete',
       'tax_computation_snapshots_write_tier_insert',
       'tax_computation_snapshots_write_tier_update',
       'tax_computation_snapshots_write_tier_delete',
       'tax_disallowances_write_tier_insert',
       'tax_disallowances_write_tier_update',
       'tax_disallowances_write_tier_delete',
       'brought_forward_losses_write_tier_insert',
       'brought_forward_losses_write_tier_update',
       'brought_forward_losses_write_tier_delete',
       'form_26as_uploads_write_tier_insert',
       'form_26as_uploads_write_tier_update',
       'form_26as_uploads_write_tier_delete',
       'form_26as_reconciliations_write_tier_insert',
       'form_26as_reconciliations_write_tier_update',
       'form_26as_reconciliations_write_tier_delete',
       'xbrl_packages_write_tier_insert',
       'xbrl_packages_write_tier_update',
       'xbrl_packages_write_tier_delete',
       'year_end_adjustments_write_tier_insert',
       'year_end_adjustments_write_tier_update',
       'year_end_adjustments_write_tier_delete',
       'year_end_engagements_write_tier_insert',
       'year_end_engagements_write_tier_update',
       'year_end_engagements_write_tier_delete',
       'year_end_exports_write_tier_insert',
       'year_end_exports_write_tier_update',
       'year_end_exports_write_tier_delete',
       'financial_statement_versions_write_tier_insert',
       'financial_statement_versions_write_tier_update',
       'financial_statement_versions_write_tier_delete',
       'mca_companies_write_tier_insert',
       'mca_companies_write_tier_update',
       'mca_companies_write_tier_delete',
       'mca_directors_write_tier_insert',
       'mca_directors_write_tier_update',
       'mca_directors_write_tier_delete');
  IF n <> 51 THEN
    RAISE EXCEPTION 'migration 488: expected 51 restrictive policies, found %', n;
  END IF;
END $$;
