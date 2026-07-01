-- Migration 150: Multi-Currency — Phase 5 (foreign-currency bank accounts). ADDITIVE ONLY.
--
-- Adds a denomination currency to bank_accounts so a client can hold a
-- foreign-currency bank account (e.g. an EEFC / USD account). The base (INR)
-- ledger is unchanged: the account's GL control still posts in base paise, and the
-- foreign balance is DERIVED from the posted journal lines' Phase-2 FX memo
-- (txn_debit/txn_credit) — no new balance column, no historical recompute.
--
-- Existing rows default to 'INR', so behaviour is byte-for-byte today's until a
-- foreign-currency account is explicitly created (which the API allows only when
-- multi-currency is active for the client). The FX revaluation service revalues
-- these foreign bank balances at period-end exactly like open AR/AP.

ALTER TABLE public.bank_accounts
  ADD COLUMN IF NOT EXISTS currency CHAR(3) NOT NULL DEFAULT 'INR';

-- Reference the ISO 4217 master (seeded from migration 146; 'INR' always present),
-- so a bank account can never carry an unknown currency code.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'bank_accounts_currency_fkey'
      AND table_name = 'bank_accounts'
  ) THEN
    ALTER TABLE public.bank_accounts
      ADD CONSTRAINT bank_accounts_currency_fkey
      FOREIGN KEY (currency) REFERENCES public.currencies(code);
  END IF;
END$$;

-- ── fx_revaluations.item_ref — disambiguate multiple same-currency bank accounts ─
-- AR/AP revalue as one aggregate per (currency, item_type) so item_ref stays NULL
-- (unchanged behaviour). Each foreign BANK account revalues against its own GL
-- account, so its runs are keyed by item_ref = the bank's coa_account_id, keeping
-- the idempotent-delta log distinct per account.
ALTER TABLE public.fx_revaluations
  ADD COLUMN IF NOT EXISTS item_ref UUID;

CREATE INDEX IF NOT EXISTS idx_fx_reval_key_ref
  ON public.fx_revaluations (firm_id, client_id, period_end, currency, item_type, item_ref);
