-- Rollback of migration 536: gives back exactly what migrations 214, 188 and 087 granted to `authenticated` and drops the six
-- policies. The party-credit and stock-ledger Python keeps working either way (the privileged client is a superset).
SELECT set_config('lock_timeout', '15s', true);

DROP POLICY IF EXISTS "party_credit_balances_assignment_scope" ON public.party_credit_balances;
DROP POLICY IF EXISTS "party_credit_balances_internal_partner_only" ON public.party_credit_balances;

DROP POLICY IF EXISTS "party_credit_ledger_assignment_scope" ON public.party_credit_ledger;
DROP POLICY IF EXISTS "party_credit_ledger_internal_partner_only" ON public.party_credit_ledger;

DROP POLICY IF EXISTS "inventory_stock_ledger_assignment_scope" ON public.inventory_stock_ledger;
DROP POLICY IF EXISTS "inventory_stock_ledger_internal_partner_only" ON public.inventory_stock_ledger;

GRANT SELECT, INSERT, UPDATE ON public.party_credit_balances TO authenticated;
GRANT SELECT, INSERT         ON public.party_credit_ledger   TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.inventory_stock_ledger TO authenticated;
GRANT ALL ON public.demo_filings TO authenticated;
