-- Migration 376: a budget is a firm record, not one browser's (ACC-06).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- `/accounting/budget` kept every figure a CA typed in
-- `localStorage["practicesync_budget_<fy>"]`. No table, no RLS, no sharing.
-- A partner who budgeted on their laptop found an empty grid on the office
-- machine; a second user saw nothing at all; clearing site data lost the year.
--
-- There is no budget table anywhere in the migration history — grep for
-- `budget` across apps/api/migrations returns nothing before this file — so
-- this is a genuine build rather than a rival to something already there.
-- (The retainer third of ACC-06 is the opposite case and is handled
-- separately: `billing_schedules` already carries `arrangement = 'retainer'`.)
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THE ROW IS KEYED ON A CLIENT, WHEN THE SCREEN WAS FIRM-WIDE
-- ═══════════════════════════════════════════════════════════════════════════
-- The screen loaded `chart_of_accounts` filtered on `firm_id` alone, so it
-- listed EVERY client's Revenue and Expense accounts in one table and set them
-- against firm-wide actuals. A practice with seven clients got one grid mixing
-- seven sets of books, and a variance that belonged to nobody.
--
-- Every report in this product is client-scoped and `account_period_balances`
-- — the table the actuals now come from — is keyed
-- (firm_id, client_id, account_id, period_month). A budget that is not
-- client-scoped cannot be compared with it. So `client_id` is NOT NULL: a
-- budget is a statement about one entity's year.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY ONE ANNUAL FIGURE AND NOT TWELVE
-- ═══════════════════════════════════════════════════════════════════════════
-- Deliberately the same grain the screen already has: an annual budget per
-- account, shown against the four quarters' actuals. A monthly or quarterly
-- budget grain is a better product and it is a DIFFERENT product — it changes
-- what the CA is asked to enter — so it is not smuggled in behind a storage
-- fix. Moving to a finer grain later is an additive column plus a backfill
-- that divides, not a rewrite.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE FY IS A LABEL, AND IT IS CHECKED
-- ═══════════════════════════════════════════════════════════════════════════
-- `YYYY-YY` canonical, the spelling `core.ist_clock.normalise_fy_label`
-- produces. The CHECK is shape-only — it cannot see that the second half
-- follows the first, which is why `models/fy.FYLabel` guards the boundary and
-- this only stops something that is not a year label at all.
--
-- Additive. Idempotent. Reversible: 376_..._rollback.sql.

CREATE TABLE IF NOT EXISTS public.account_budgets (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id       uuid NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    client_id     uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    account_id    uuid NOT NULL REFERENCES public.chart_of_accounts(id) ON DELETE CASCADE,
    -- Financial year label, canonical YYYY-YY (IT Act: 1 April to 31 March).
    fy            text NOT NULL,
    -- Integer paise, like every monetary column in this schema. A budget of
    -- zero is a real statement ("we plan to spend nothing here"), which is why
    -- the row existing and the row being zero are different facts and the
    -- screen deletes rather than zeroing when a CA clears the box.
    budget_paise  bigint NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    created_by    uuid REFERENCES public.users(id),
    updated_by    uuid REFERENCES public.users(id),
    CONSTRAINT account_budgets_fy_is_a_label
        CHECK (fy ~ '^[0-9]{4}-[0-9]{2}$'),
    -- Negative is allowed: a contra-revenue or a credit-balance expense head
    -- can legitimately be budgeted below zero, and refusing it would make the
    -- grid unusable for exactly the accounts a CA thinks hardest about.
    CONSTRAINT account_budgets_one_per_account_year
        UNIQUE (firm_id, client_id, account_id, fy)
);

COMMENT ON TABLE public.account_budgets IS
    'One annual budget figure per (client, account, financial year). Written '
    'only through POST/PUT /api/accounting/budgets — the actuals it is shown '
    'against come from account_period_balances server-side, never from a '
    'browser query over journal_lines. Migration 376 (ACC-06).';
COMMENT ON COLUMN public.account_budgets.fy IS
    'Canonical YYYY-YY, the spelling core.ist_clock.normalise_fy_label '
    'produces. The CHECK is shape-only; models/fy.FYLabel guards the boundary.';
COMMENT ON COLUMN public.account_budgets.budget_paise IS
    'Integer paise. May be negative — a contra-revenue head is legitimately '
    'budgeted below zero.';

CREATE INDEX IF NOT EXISTS idx_account_budgets_lookup
    ON public.account_budgets (firm_id, client_id, fy);

ALTER TABLE public.account_budgets ENABLE ROW LEVEL SECURITY;

-- Firm isolation, assignment scope, and role-guarded writes, in the shape
-- migrations 260/261 established and 359 last used.
--
-- The assignment-scope policy is here at CREATE time rather than waiting for
-- another sweep like migration 370's: 084's one-shot DO loop has never run
-- again, so every client_id table created since has had to remember this for
-- itself, and six of them did not.
--
-- The role tiers: a budget is a management figure, not a statutory one, and
-- getting it wrong misstates no return — so Executive+ to write, and the same
-- Manager+ to delete that every other table here uses, because deleting a
-- year's budget is the destructive act.
DO $$
BEGIN
  EXECUTE 'DROP POLICY IF EXISTS firm_account_budgets ON public.account_budgets';
  EXECUTE 'CREATE POLICY firm_account_budgets ON public.account_budgets '
          'FOR ALL TO authenticated '
          'USING (firm_id = public.get_my_firm_id()) '
          'WITH CHECK (firm_id = public.get_my_firm_id())';

  -- "ON public.<table> AS RESTRICTIVE" kept contiguous in ONE string literal:
  -- tests/test_direct_write_tables_are_role_guarded.py reads the migration
  -- FILE, and a policy split across adjacent literals is valid SQL and
  -- invisible to that scan.
  EXECUTE 'DROP POLICY IF EXISTS account_budgets_assignment_scope ON public.account_budgets';
  EXECUTE 'CREATE POLICY account_budgets_assignment_scope '
          'ON public.account_budgets AS RESTRICTIVE '
          'FOR ALL USING (public.can_access_client(client_id::text)) '
          'WITH CHECK (public.can_access_client(client_id::text))';

  EXECUTE 'DROP POLICY IF EXISTS account_budgets_role_insert ON public.account_budgets';
  EXECUTE 'CREATE POLICY account_budgets_role_insert '
          'ON public.account_budgets AS RESTRICTIVE '
          'FOR INSERT WITH CHECK (public.my_role_at_least(''Executive''))';

  EXECUTE 'DROP POLICY IF EXISTS account_budgets_role_update ON public.account_budgets';
  EXECUTE 'CREATE POLICY account_budgets_role_update '
          'ON public.account_budgets AS RESTRICTIVE '
          'FOR UPDATE USING (public.my_role_at_least(''Executive'')) '
          'WITH CHECK (public.my_role_at_least(''Executive''))';

  EXECUTE 'DROP POLICY IF EXISTS account_budgets_role_delete ON public.account_budgets';
  EXECUTE 'CREATE POLICY account_budgets_role_delete '
          'ON public.account_budgets AS RESTRICTIVE '
          'FOR DELETE USING (public.my_role_at_least(''Manager''))';

  EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.account_budgets TO authenticated';
END $$;
