-- Migration 227: account_period_balances — the reporting "passbook" (Phase 1).
--
-- Per-account, per-CALENDAR-MONTH running totals of posted journal activity, so
-- accrual reports (Trial Balance / P&L / Balance Sheet) can read a small,
-- time-bounded table instead of replaying a client's entire posted history on
-- every load. One row = the summed debit/credit posted to one account in one
-- month for one client. Its definition is exactly the accrual line stream the
-- reporting engine already sums (see domain/reporting/balance_cache.build_buckets).
--
-- PHASE 1 SCOPE: this table exists and can be backfilled + audited, but NOTHING
-- reads it into a live report yet. Reports still use the existing engine. The
-- switch-over happens in a later phase, in shadow mode, only after the stored
-- buckets have been proven to reproduce the live numbers to the paise.
--
-- It is a derived cache: it can always be rebuilt from journal_entries +
-- journal_lines, and a background auditor re-derives and compares it. It is
-- never a source of truth on its own.
CREATE TABLE IF NOT EXISTS public.account_period_balances (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id       UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id     UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  account_id    UUID NOT NULL REFERENCES public.chart_of_accounts(id) ON DELETE CASCADE,
  -- First day of the calendar month this bucket sums (e.g. 2026-04-01 for April
  -- 2026), keyed off journal_entries.entry_date — the same date the reports window on.
  period_month  DATE   NOT NULL,
  debit_paise   BIGINT NOT NULL DEFAULT 0,
  credit_paise  BIGINT NOT NULL DEFAULT 0,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  -- One bucket per (client, account, month). The unique key is what the
  -- backfill / incremental maintenance upserts on.
  UNIQUE (firm_id, client_id, account_id, period_month)
);

-- Reports read all buckets for one client (optionally up to an as-of month), so
-- the client + month ordering is the hot path.
CREATE INDEX IF NOT EXISTS idx_account_period_balances_client_month
  ON public.account_period_balances (firm_id, client_id, period_month);

ALTER TABLE public.account_period_balances ENABLE ROW LEVEL SECURITY;

-- Same firm + client isolation as every other client-scoped table (migration 053).
DROP POLICY IF EXISTS "firm_client_isolation" ON public.account_period_balances;
CREATE POLICY "firm_client_isolation" ON public.account_period_balances
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (SELECT id FROM public.clients WHERE firm_id = get_my_firm_id())
    )
    WITH CHECK (
        firm_id = get_my_firm_id()
        AND client_id IN (SELECT id FROM public.clients WHERE firm_id = get_my_firm_id())
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON public.account_period_balances TO authenticated, service_role;
