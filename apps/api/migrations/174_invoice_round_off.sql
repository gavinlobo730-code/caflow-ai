-- Migration 174: invoice-level round-off (Batch 1 — money correctness)
--
-- Adds client_sales_invoices.round_off_paise (nearest-rupee adjustment, integer
-- paise, DEFAULT 0 so every EXISTING invoice is byte-for-byte unchanged) and
-- ensures a firm-wide 'Round Off' ledger exists so journal_for_sales_invoice can
-- post the rounding delta (Dr/Cr) and keep the journal balanced.
--
-- CGST Act §15: the value of supply and the GST thereon are NOT affected by
-- round-off. taxable_amount_paise / cgst_paise / sgst_paise / igst_paise remain
-- exactly as computed at source; only the invoice total carries the rounding.

-- 1) Round-off column (additive, defaulted — no backfill of existing rows).
ALTER TABLE public.client_sales_invoices
  ADD COLUMN IF NOT EXISTS round_off_paise BIGINT NOT NULL DEFAULT 0;

-- 2) Seed a firm-wide 'Round Off' ledger for every firm that already has a
--    firm-wide Chart of Accounts but no round-off account yet. Idempotent:
--    guarded by NOT EXISTS on the name, and ON CONFLICT on the (firm_id,
--    account_code) unique constraint so a firm that happens to already use code
--    5015 does not abort the migration (it simply keeps its existing account and
--    can add a 'Round Off' ledger manually if needed).
--    New firms receive this account from coa_seed_service.STANDARD_COA.
INSERT INTO public.chart_of_accounts
  (firm_id, client_id, account_code, account_name, account_type, account_subtype,
   is_active, system_account_key)
SELECT DISTINCT c.firm_id, NULL, '5015', 'Round Off', 'Expense', 'Overhead',
       TRUE, 'round_off'
FROM public.chart_of_accounts c
WHERE c.client_id IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM public.chart_of_accounts r
    WHERE r.firm_id = c.firm_id
      AND r.client_id IS NULL
      AND (r.system_account_key = 'round_off' OR r.account_name ILIKE 'Round Off')
  )
ON CONFLICT ON CONSTRAINT chart_of_accounts_firm_code_unique DO NOTHING;

-- 3) Backfill the system key on any pre-existing 'Round Off' account that lacks
--    it, so key-first resolution works for those firms too.
UPDATE public.chart_of_accounts
  SET system_account_key = 'round_off'
  WHERE client_id IS NULL
    AND system_account_key IS NULL
    AND account_name ILIKE 'Round Off';
