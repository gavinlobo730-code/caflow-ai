-- PracticeSync AI — Migration 074: Internal-Client RLS Guardrails (G1 defence-in-depth)
-- Amendment v1.1 (Phase 10B) — BATCH 2.
--
-- The application backend connects with the Supabase SERVICE_ROLE key, which
-- BYPASSES RLS; G1/G2 are therefore enforced primarily in the Python API/repo
-- layer. These RESTRICTIVE policies are DEFENCE-IN-DEPTH for any direct
-- (non-service-role / PostgREST / anon+JWT) access to the database.
--
-- Effect: non-Partner users cannot see or write the internal practice client's
-- row or its financial rows. RESTRICTIVE policies AND with the existing
-- permissive firm-isolation policies (they only ever remove access, never add).
-- "Partner" is the Owner-equivalent role per the approved mapping.
--
-- Additive & idempotent. Rollback: 074_internal_client_rls_guardrails_rollback.sql.

-- Memoised lookup of the caller's firm internal client id (SECURITY DEFINER so
-- it can read firms regardless of the caller's own RLS).
CREATE OR REPLACE FUNCTION my_internal_client_id()
RETURNS uuid AS $$
  SELECT internal_client_id FROM firms WHERE id = get_my_firm_id();
$$ LANGUAGE sql SECURITY DEFINER STABLE;

-- ── clients: hide the internal row from non-Partners ─────────────────────────
DROP POLICY IF EXISTS "clients_internal_partner_only" ON clients;
CREATE POLICY "clients_internal_partner_only" ON clients
  AS RESTRICTIVE FOR ALL
  USING (get_my_role() = 'Partner' OR NOT is_internal)
  WITH CHECK (get_my_role() = 'Partner' OR NOT is_internal);

-- ── financial / client-scoped tables: hide internal-client rows from non-Partners ─
-- Applied to every listed table that exists AND has a client_id column. Uses
-- IS DISTINCT FROM so a NULL internal_client_id (unprovisioned firm) never hides
-- ordinary client rows.
--
-- TYPE-SAFETY (repository consistency fix, 2026-06-14): client_id is uuid on every
-- table in this list EXCEPT client_timeline_events, whose client_id is TEXT. The
-- helper my_internal_client_id() returns uuid, so a bare
--   client_id IS DISTINCT FROM my_internal_client_id()
-- raised `ERROR: operator does not exist: text = uuid` on client_timeline_events
-- and rolled the entire migration back. Both sides are cast to ::text below; that
-- comparison is valid for uuid and text client_id columns alike, so a fresh
-- environment applies 073–080 in sequence with no manual intervention.
DO $$
DECLARE
  t    text;
  tbls text[] := ARRAY[
    'journal_entries','ledger_balances',
    'sales_invoices','receipts','credit_notes',
    'purchase_bills','purchase_payments',
    'customers','vendors',
    'bank_accounts','bank_transactions','bank_statements','bank_reconciliations',
    'gstr1_returns','gstr3b_returns','gstr2a_records','gstr2b_uploads','gst_challans',
    'tds_returns','tds_deductions','tds_challans','tds_certificates',
    'fixed_assets','loans','fixed_deposits',
    'advance_tax_payments','compliance_records','compliance_tasks',
    'year_end_engagements',
    'payroll_employees','payroll_runs','salary_structures','attendance','leave_balances',
    -- client-scoped read surfaces (Batch 2.1 defence-in-depth)
    'client_timeline_events','documents','document_extractions','document_requests',
    'ai_insights','government_notices','it_notices','tax_notices',
    'billing_schedules','client_firm_customer_links','client_instructions'
  ];
BEGIN
  FOREACH t IN ARRAY tbls LOOP
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema='public' AND table_name=t)
       AND EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name=t AND column_name='client_id') THEN
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
      EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I',
                     t || '_internal_partner_only', t);
      -- ::text on both sides: works for uuid client_id and the lone text one
      -- (client_timeline_events). See TYPE-SAFETY note above.
      EXECUTE format(
        'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR ALL '
        || 'USING (get_my_role() = ''Partner'' OR client_id::text IS DISTINCT FROM my_internal_client_id()::text) '
        || 'WITH CHECK (get_my_role() = ''Partner'' OR client_id::text IS DISTINCT FROM my_internal_client_id()::text)',
        t || '_internal_partner_only', t);
    END IF;
  END LOOP;
END $$;
