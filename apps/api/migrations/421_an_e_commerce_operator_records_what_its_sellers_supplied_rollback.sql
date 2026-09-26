-- Rollback for 421. Additive-only migration, so a plain DROP undoes it fully.

BEGIN;

DROP TABLE IF EXISTS public.ecommerce_operator_unregistered_supplies;
DROP TABLE IF EXISTS public.ecommerce_operator_supplies;

COMMIT;
