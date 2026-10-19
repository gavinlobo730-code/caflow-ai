-- Rollback of migration 521: drops fixed_deposits.maturity_amount_is_estimate. After this the register can no longer say which of
-- its maturity amounts are estimates and which were typed from a receipt. For fidelity with the previous schema, not for use.
ALTER TABLE IF EXISTS public.fixed_deposits DROP COLUMN IF EXISTS maturity_amount_is_estimate;
