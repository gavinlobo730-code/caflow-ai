-- Rollback for 386. Restores migration 093's four-value CHECK.
--
-- A card account created in the meantime would violate it, so those rows are
-- listed rather than silently deleted: dropping a client's card account takes
-- its statement, its coding and its reconciliation with it, and that is an
-- owner decision rather than a rollback's to make.
DO $$
DECLARE
  v_cards int;
BEGIN
  SELECT count(*) INTO v_cards FROM public.bank_accounts WHERE account_type = 'Credit Card';
  IF v_cards > 0 THEN
    RAISE EXCEPTION
      'Rollback refused: % credit-card bank account(s) exist. Re-type or delete '
      'them first — narrowing the CHECK under them would leave rows the '
      'constraint forbids.', v_cards;
  END IF;
END $$;

ALTER TABLE public.bank_accounts
  DROP CONSTRAINT IF EXISTS bank_accounts_account_type_check;

ALTER TABLE public.bank_accounts
  ADD CONSTRAINT bank_accounts_account_type_check
  CHECK (account_type IN ('Current', 'Savings', 'Cash Credit', 'Overdraft'));
