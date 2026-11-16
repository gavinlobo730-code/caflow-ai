-- Rollback of migration 617: drops the two GSTR-8 amendment tables (Table 4 and Table 4.1) and the amendments recorded in them. The API that
-- reads and writes them must be rolled back first; Table 3 and Table 3.1 (migration 421) are untouched.
BEGIN;
DROP TABLE IF EXISTS public.ecommerce_operator_unregistered_supply_amendments;
DROP TABLE IF EXISTS public.ecommerce_operator_supply_amendments;
COMMIT;
