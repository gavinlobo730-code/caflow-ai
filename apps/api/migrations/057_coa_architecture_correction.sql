-- COA Architecture Correction
-- Approved: One Firm → One Master COA. Clients share firm COA. Balances isolated via firm_id + client_id + account_id.

ALTER TABLE chart_of_accounts
  ADD COLUMN IF NOT EXISTS parent_group         TEXT,
  ADD COLUMN IF NOT EXISTS sub_group            TEXT,
  ADD COLUMN IF NOT EXISTS tax_category         TEXT,
  ADD COLUMN IF NOT EXISTS schedule_iii_mapping TEXT;

-- Archive any client-specific overrides — per approved architecture clients do not have their own COA
UPDATE chart_of_accounts
  SET is_active = false, updated_at = NOW()
  WHERE client_id IS NOT NULL AND is_active = true;

CREATE INDEX IF NOT EXISTS idx_coa_schedule_iii ON chart_of_accounts(schedule_iii_mapping) WHERE schedule_iii_mapping IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_coa_tax_category  ON chart_of_accounts(tax_category)         WHERE tax_category         IS NOT NULL;

COMMENT ON TABLE chart_of_accounts IS 'Firm-level master COA. client_id is deprecated. Balance isolation via ledger_balances(firm_id, client_id, account_id).';
