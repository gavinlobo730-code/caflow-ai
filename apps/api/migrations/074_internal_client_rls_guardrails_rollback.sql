-- PracticeSync AI — Migration 074 ROLLBACK (Internal-Client RLS Guardrails)
-- Drops only the RESTRICTIVE policies + helper added by 074. The existing
-- permissive firm-isolation policies are untouched. Idempotent.

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
    'billing_schedules','client_firm_customer_links','client_instructions'
  ];
BEGIN
  FOREACH t IN ARRAY tbls LOOP
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema='public' AND table_name=t) THEN
      EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I',
                     t || '_internal_partner_only', t);
    END IF;
  END LOOP;
END $$;

DROP POLICY IF EXISTS "clients_internal_partner_only" ON clients;
DROP FUNCTION IF EXISTS my_internal_client_id();
