-- Migration 370: six client tables the browser reads with no assignment scope.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (PUR-28, and it is wider than the finding said)
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 084 gave every table with a `client_id` column a RESTRICTIVE
-- `<table>_assignment_scope` policy, so that on the DIRECT PostgREST path — the
-- one the frontend uses, where RLS is the only control — a Manager, Executive
-- or Reviewer sees only the clients they are assigned to. A Partner
-- short-circuits to TRUE.
--
-- It did that with a one-shot `DO` loop over
-- `information_schema.columns WHERE column_name = 'client_id'`. The loop caught
-- everything that existed in 2024 and HAS NEVER RUN AGAIN. Every `client_id`
-- table created since carries only its firm-wide PERMISSIVE policy, which
-- scopes to the firm and nothing else.
--
-- Six of them are read straight from the browser today:
--
--   bank_accounts                      migration 093 — nine after 084
--   debit_notes                        migration 145
--   purchase_credit_notes              migration 210
--   sales_debit_notes                  migration 210
--   gstr2b_reconciliations             migration 341
--   tds_lower_deduction_certificates   migration 359
--
-- So any signed-in user of the firm — assigned to nothing — could read and
-- write every client's bank accounts (account number included, which
-- docs/compliance/06 treats as DPDP `bank_data`), every purchase- and
-- sales-side note, every 2B reconciliation and every §197 certificate.
-- `apps/web/app/clients/[id]/purchases/page.tsx` reads two of them,
-- `components/banking/BankBook.tsx` and the client sales page read
-- `bank_accounts`.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THIS IS SIX EXPLICIT TABLES AND NOT 084'S LOOP AGAIN
-- ═══════════════════════════════════════════════════════════════════════════
-- Re-running the loop is the obvious fix and it is WRONG, twice over.
--
-- 1. It would DROP AND RECREATE policies migration 262 deliberately replaced.
--    262 split `payroll_employees_assignment_scope` and
--    `payroll_runs_assignment_scope` into four per-command policies each so the
--    EMPLOYEE PORTAL can read a payslip. An employee is not an internal user:
--    they have no `users` row and no `user_client_assignments` row, so
--    `can_access_client` denies them. Restoring 084's single FOR ALL policy
--    would break the portal.
--
-- 2. It would put a RESTRICTIVE `can_access_client` policy on ~44 further
--    tables nothing reaches from the browser, several of them portal-side
--    (`client_portal_sessions`, `payroll_it_declarations`, the payroll loan and
--    settlement tables), for the same reason.
--
-- The durable half of the fix is therefore a TEST, not a loop:
-- `tests/test_a_table_the_browser_reads_is_assignment_scoped_pg.py` asserts the
-- RULE — a `client_id` table the browser reads directly must be
-- assignment-scoped — so the next such table fails CI instead of waiting for
-- an audit. A loop cannot know which tables are portal-side; the rule can be
-- read and the exceptions written down.
--
-- No application code changes. The backend connects with the service-role key
-- and BYPASSES RLS entirely, so nothing on the API path is affected; the
-- app-layer `.eq("firm_id", …)` filter with `core.authz` stays the control
-- there. A Partner is unaffected on both paths.
--
-- Idempotent. Reversible: 370_..._rollback.sql.

-- `can_access_client` is migration 084's own helper: NULL client_id (a
-- firm-level row) is allowed, a Partner is allowed, everyone else needs a
-- `user_client_assignments` row. RESTRICTIVE means it AND-s with the existing
-- firm policy — it can only REMOVE access, never grant it.
DO $$
DECLARE
  t text;
  targets text[] := ARRAY[
    'bank_accounts',
    'debit_notes',
    'purchase_credit_notes',
    'sales_debit_notes',
    'gstr2b_reconciliations',
    'tds_lower_deduction_certificates'
  ];
BEGIN
  FOREACH t IN ARRAY targets LOOP
    -- Skip a table this deployment does not have rather than failing the
    -- migration: the runner replays the whole set on a fresh database and on
    -- production alike.
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = 'public' AND table_name = t AND table_type = 'BASE TABLE'
    ) THEN
      CONTINUE;
    END IF;
    -- ...and never overwrite an assignment rule somebody wrote deliberately.
    -- Migration 262 is why: its per-command payroll policies are the shape a
    -- blind DROP/CREATE would destroy.
    IF EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public' AND tablename = t AND policyname LIKE '%assignment%'
    ) THEN
      CONTINUE;
    END IF;

    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR ALL '
      || 'USING (public.can_access_client(client_id::text)) '
      || 'WITH CHECK (public.can_access_client(client_id::text))',
      t || '_assignment_scope', t);
  END LOOP;
END $$;
