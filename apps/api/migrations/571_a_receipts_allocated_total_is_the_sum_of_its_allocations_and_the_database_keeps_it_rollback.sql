-- Rollback of 571: take the trigger and its function away. The corrected totals are left as they are (they were true when written, and
-- nothing keeps them true any more), and the column's comment says so rather than claiming a trigger that no longer exists.
BEGIN;
DROP TRIGGER IF EXISTS receipt_allocations_keep_total ON public.receipt_allocations;
DROP FUNCTION IF EXISTS public.keep_receipt_allocated_total();
COMMENT ON COLUMN public.receipts.allocated_paise IS
    'Not maintained by anything after the rollback of migration 571: the figure was last corrected by that migration and drifts from the receipt_allocations rows from then on. POST-A-369.';
COMMIT;
