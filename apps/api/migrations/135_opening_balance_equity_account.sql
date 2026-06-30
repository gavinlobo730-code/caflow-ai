-- Migration 135: "Opening Balance Equity" account for opening-balance journalisation.
--
-- Opening balances on master records (customers/vendors/bank_accounts.opening_balance_paise)
-- are now posted to the General Ledger as a balanced opening journal (entry_type=
-- 'opening_balance'), contra'd to this Opening Balance Equity control account, so the
-- Trial Balance / Balance Sheet reconcile with customer & vendor balances.
--
-- COA is a firm-wide master (Migration 057: client_id = NULL, shared by all clients).
-- New firms get this account from coa_seed_service.STANDARD_COA; this backfills firms
-- that were already seeded. Idempotent: skips firms that already have the account (by
-- name) or that already use account_code 3004, and only touches firms that have a CoA.

INSERT INTO public.chart_of_accounts
    (firm_id, client_id, account_code, account_name, account_type, account_subtype, is_active)
SELECT f.id, NULL, '3004', 'Opening Balance Equity', 'Equity', 'Capital', true
FROM public.firms f
WHERE NOT EXISTS (
        SELECT 1 FROM public.chart_of_accounts c
        WHERE c.firm_id = f.id AND c.client_id IS NULL
          AND c.account_name ILIKE 'Opening Balance Equity'
      )
  AND NOT EXISTS (
        SELECT 1 FROM public.chart_of_accounts c2
        WHERE c2.firm_id = f.id AND c2.client_id IS NULL AND c2.account_code = '3004'
      )
  AND EXISTS (
        SELECT 1 FROM public.chart_of_accounts c3
        WHERE c3.firm_id = f.id AND c3.client_id IS NULL
      );
