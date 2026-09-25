-- Migration 417: what a client's year looked like, stored once a night.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING (STUCK.md §1; plan rows 3c-1, 3c-2, 3c-4 and the tax half
-- of 3c-5; decided as D30)
-- ═══════════════════════════════════════════════════════════════════════════
-- A client's effective tax rate, ITC as a proportion of purchases, or
-- GST-to-turnover ratio is derived from that client's WHOLE ledger for the
-- period. Computing it for one client is already a read proportional to
-- transaction volume; computing it for every client so that one can be
-- compared against them multiplies that by the client count. That is
-- CLAUDE.md's reporting rule — "No report may fetch rows proportional to
-- transaction volume" — broken twice over, on a firm with fifty clients, on an
-- endpoint a Partner would leave open. The measured comparison is the
-- cash-flow case: 12,836 entries took 54.34s unaggregated against 2.15s off
-- `account_period_balances`.
--
-- So the commercial half of the benchmark shipped (`domain/practice/
-- concentration.py`, fee revenue and cost per client, one aggregated read
-- each) and the TAX half did not ship at all.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE SHAPE IS `account_period_balances`', AND SO IS THE REASONING
-- ═══════════════════════════════════════════════════════════════════════════
-- One row per (client, financial year). The nightly sweep — which already runs
-- `audit_and_heal_firm` and `run_reconciliation_for_firm` per client, and so
-- already pays the per-client read — computes the figures and writes them
-- here. The benchmark is then ONE read of a few dozen rows, and the trends are
-- free, because a year of rows IS the trend.
--
-- ⚠️ THE SWEEP RE-DERIVES, IT DOES NOT ACCUMULATE. Every run recomputes the
-- year from the books and replaces the row, the same self-healing discipline
-- `balance_cache_audit` takes: a back-dated journal, a corrected invoice or a
-- revised return moves a figure that was already written, and a row that could
-- only ever be added to would drift from the ledger with nothing to catch it.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- EVERY FIGURE IS NULLABLE, WITH NO DEFAULT, AND THAT IS THE LOAD-BEARING PART
-- ═══════════════════════════════════════════════════════════════════════════
-- `DEFAULT 0` would make "this client had no output tax" and "nobody could
-- derive this client's output tax" the same row — the distinction CLAUDE.md
-- keeps having to record (`table_4a_gaps`, `_undeclarable_rows`, the three
-- kinds of nil on the firm hub). A benchmark is a DISTRIBUTION, so the
-- difference is not cosmetic: a nil that means "not derived" drags every
-- median and every average it is counted in towards zero, and the client it
-- belongs to reads as the firm's best performer on ratios it has no figures
-- for. NULL is excluded from the distribution; zero is a real answer.
--
-- `gaps` says WHICH figures are absent and why, so a screen can name them
-- rather than showing a blank a reader takes for nil.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY A TABLE AND NOT A VIEW
-- ═══════════════════════════════════════════════════════════════════════════
-- A view would re-derive on every read and reintroduce exactly the cost this
-- exists to remove. It would also lose HISTORY: the figures are computed from
-- the books as they stand, and a year whose books are later locked, restated
-- or migrated away cannot be recomputed afterwards. A stored row is the record
-- of what the year looked like.
--
-- Which is also why D30 fixed the COLUMN LIST once: a column added later
-- cannot be back-filled for a period whose books have since been locked, so
-- the twelve figures are chosen now — turnover, profit before tax, tax
-- expense, output tax, ITC availed, ITC reversed, GST cash paid, purchases,
-- TDS deducted, TDS deposited, payroll cost and employee count.
--
-- `domain/practice/client_metrics.py` is the authority for what each figure
-- MEANS and which source is allowed to answer it. This migration holds only
-- the shape.

CREATE TABLE IF NOT EXISTS public.client_period_metrics (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id        UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
    client_id      UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

    -- `YYYY-YY`, the one financial-year label this product uses. CHECKed to
    -- the shape only: `core.ist_clock.normalise_fy_label` is the authority for
    -- whether the second half follows the first, and a CHECK that tried would
    -- be a second implementation of it. See CLAUDE.md on `FYLabel` — `2026-28`
    -- passes `^\d{4}-\d{2}$` and means 2026-27.
    financial_year TEXT NOT NULL CHECK (financial_year ~ '^[0-9]{4}-[0-9]{2}$'),

    -- ── The books (domain/reporting) ──────────────────────────────────────
    turnover_paise           BIGINT,
    profit_before_tax_paise  BIGINT,
    tax_expense_paise        BIGINT,
    purchases_paise          BIGINT,

    -- ── GST (the returns as filed, never re-derived from the ledger) ──────
    output_tax_paise         BIGINT,
    itc_availed_paise        BIGINT,
    itc_reversed_paise       BIGINT,
    gst_cash_paid_paise      BIGINT,

    -- ── TDS (the register and the challans) ───────────────────────────────
    tds_deducted_paise       BIGINT,
    tds_deposited_paise      BIGINT,

    -- ── Payroll (released runs only — PAY-04) ─────────────────────────────
    payroll_cost_paise       BIGINT,
    employee_count           INTEGER CHECK (employee_count IS NULL OR employee_count >= 0),

    -- One entry per figure the run could not derive: {"figure": …, "why": …}.
    -- NOT NULL with an empty default, because "no gaps" is a real answer and
    -- an absent list is not.
    gaps           JSONB NOT NULL DEFAULT '[]'::jsonb,

    computed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- The sweep re-derives and replaces, so the row is keyed on what it
    -- describes. Not (firm, client, year): `clients.id` already determines the
    -- firm, and a two-column key is what the upsert can state.
    CONSTRAINT client_period_metrics_one_row_per_client_year
        UNIQUE (client_id, financial_year)
);

-- The benchmark's own read: every client of one firm for one year. The
-- client-year unique index above serves the per-client trend.
CREATE INDEX IF NOT EXISTS client_period_metrics_firm_year_idx
    ON public.client_period_metrics (firm_id, financial_year);

COMMENT ON TABLE public.client_period_metrics IS
  'Per-client, per-financial-year aggregates, re-derived nightly by the 06:00 '
  'IST sweep so a cross-client benchmark is one read of a few dozen rows '
  'rather than every client''s whole ledger. Every figure is NULLABLE: NULL '
  'means the run could not derive it and is EXCLUDED from a distribution, '
  'where 0 is a real answer that belongs in one. `gaps` says which and why. '
  'domain/practice/client_metrics.py is the authority for what each means.';

COMMENT ON COLUMN public.client_period_metrics.employee_count IS
  'Distinct employees paid in a RELEASED run during the year (PAY-04), not '
  'headcount at any date: a point-in-time headcount is stale the moment '
  'somebody joins, and cost per employee is measured over the same population '
  'the cost was paid to.';

ALTER TABLE public.client_period_metrics ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_isolation" ON public.client_period_metrics;
CREATE POLICY "firm_isolation" ON public.client_period_metrics
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- Migration 084's assignment scope, applied at creation rather than left for a
-- sweep that has not run since 2024. This row names a client and carries that
-- client's turnover, profit and tax, so an Executive who is not assigned to
-- them must not see it. See CLAUDE.md on why 084's one-shot DO loop never runs
-- again.
DROP POLICY IF EXISTS "client_period_metrics_assignment_scope"
  ON public.client_period_metrics;
CREATE POLICY "client_period_metrics_assignment_scope"
  ON public.client_period_metrics
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_period_metrics TO authenticated;
