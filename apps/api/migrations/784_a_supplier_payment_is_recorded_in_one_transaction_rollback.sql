-- Rollback of migration 784: the two functions that record a supplier payment in one transaction are dropped.
--
-- Roll this back only with a service that does not call settle_payment_atomic: a service that does would fail every supplier
-- payment with "function not found". Nothing else reads or depends on either function, and no row is touched.

BEGIN;

DROP FUNCTION IF EXISTS public.settle_payment_atomic(jsonb, jsonb, jsonb, jsonb);
DROP FUNCTION IF EXISTS public.settle_payment_atomic__unguarded(jsonb, jsonb, jsonb, jsonb);

COMMIT;
