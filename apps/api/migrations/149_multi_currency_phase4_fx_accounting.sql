-- Migration 149: Multi-Currency — Phase 4 (FX Accounting). ADDITIVE ONLY.
--
-- Adds the objects for realized FX (on settlement at a different rate) and
-- unrealized FX (period-end revaluation), per the frozen architecture. The GL
-- keeps balancing in base (INR); FX differences post as append-only journals to
-- dedicated P&L accounts. Nothing here changes INR behaviour or historical data.
--
-- NOT here (Phase 5+): foreign TB/BS/P&L, presentation currency, translation
-- reserve (OCI/FCTR), consolidation.

-- ── FX Gain/Loss accounts (G: fx_realized / fx_unrealized) ────────────────────
-- One net P&L account each (a debit is a loss, a credit is a gain). Seeded
-- firm-level (client_id NULL) for every firm that doesn't already have them.
-- Resolved by system_account_key, so the account_code only needs to be present.
INSERT INTO chart_of_accounts (firm_id, client_id, account_code, account_name, account_type, account_subtype, system_account_key, is_active)
SELECT f.id, NULL, '9910', 'Foreign Exchange Gain/Loss (Realized)', 'Expense', 'Finance Costs', 'fx_realized', TRUE
FROM firms f
WHERE NOT EXISTS (SELECT 1 FROM chart_of_accounts c WHERE c.firm_id = f.id AND c.system_account_key = 'fx_realized');

INSERT INTO chart_of_accounts (firm_id, client_id, account_code, account_name, account_type, account_subtype, system_account_key, is_active)
SELECT f.id, NULL, '9920', 'Foreign Exchange Gain/Loss (Unrealized)', 'Expense', 'Finance Costs', 'fx_unrealized', TRUE
FROM firms f
WHERE NOT EXISTS (SELECT 1 FROM chart_of_accounts c WHERE c.firm_id = f.id AND c.system_account_key = 'fx_unrealized');

-- ── Foreign-settled tracking (partial settlement without rounding drift) ──────
-- Foreign minor units already settled against a document. base stays in paid_paise;
-- foreign_outstanding = txn_total(_net_payable) − paid_txn is tracked exactly in the
-- transaction currency, so partial settlements never drift and the final settlement
-- snaps the base to clear the document exactly.
ALTER TABLE public.client_sales_invoices ADD COLUMN IF NOT EXISTS paid_txn BIGINT NOT NULL DEFAULT 0;
ALTER TABLE public.purchase_bills        ADD COLUMN IF NOT EXISTS paid_txn BIGINT NOT NULL DEFAULT 0;

-- ── fx_revaluations — append-only run log for period-end revaluation ──────────
-- One row PER RUN per (firm, client, period_end, currency, item_type). Re-running
-- posts only the DELTA needed to reach the new target (idempotent + self-healing);
-- prior rows are never edited. cumulative target for a key = sum(delta_paise).
CREATE TABLE IF NOT EXISTS public.fx_revaluations (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                 UUID NOT NULL,
  client_id               UUID NOT NULL,
  period_end              DATE NOT NULL,
  currency                CHAR(3) NOT NULL REFERENCES public.currencies(code),
  item_type               TEXT NOT NULL CHECK (item_type IN ('receivable','payable','bank')),
  closing_rate            NUMERIC(18,8) NOT NULL CHECK (closing_rate > 0),
  target_adjustment_paise BIGINT NOT NULL,   -- desired cumulative revaluation for this key
  delta_paise             BIGINT NOT NULL,   -- what THIS run posted (target − prior cumulative)
  journal_entry_id        UUID,              -- the revaluation journal (NULL when delta = 0)
  reversal_entry_id       UUID,              -- its auto-reversal on day 1 of the next period
  run_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  run_by                  UUID
);
CREATE INDEX IF NOT EXISTS idx_fx_reval_key
  ON public.fx_revaluations (firm_id, client_id, period_end, currency, item_type);

-- ── fx_adjustments — immutable audit trail for every FX difference (Task 7) ───
CREATE TABLE IF NOT EXISTS public.fx_adjustments (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id          UUID NOT NULL,
  client_id        UUID NOT NULL,
  kind             TEXT NOT NULL CHECK (kind IN ('realized','unrealized')),
  document_type    TEXT,               -- sales_invoice | purchase_bill | receipt | purchase_payment | revaluation
  document_id      UUID,
  currency         CHAR(3) NOT NULL,
  original_rate    NUMERIC(18,8),      -- document's frozen booking rate
  settlement_rate  NUMERIC(18,8),      -- rate at settlement (realized)
  closing_rate     NUMERIC(18,8),      -- period-end rate (unrealized)
  base_delta_paise BIGINT NOT NULL,    -- FX gain (+) / loss (−) in base paise
  journal_entry_id UUID,               -- the FX journal (append-only)
  rate_source      TEXT,               -- provider / "manual-override" / "settlement"
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by       UUID
);
CREATE INDEX IF NOT EXISTS idx_fx_adj_firm_client ON public.fx_adjustments (firm_id, client_id);
CREATE INDEX IF NOT EXISTS idx_fx_adj_document    ON public.fx_adjustments (document_type, document_id);

-- ── RLS (Phase 4 posture) ─────────────────────────────────────────────────────
ALTER TABLE public.fx_revaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fx_adjustments  ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS firm_fx_revaluations ON public.fx_revaluations;
CREATE POLICY firm_fx_revaluations ON public.fx_revaluations FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id()) WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS firm_fx_adjustments ON public.fx_adjustments;
CREATE POLICY firm_fx_adjustments ON public.fx_adjustments FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id()) WITH CHECK (firm_id = public.get_my_firm_id());
