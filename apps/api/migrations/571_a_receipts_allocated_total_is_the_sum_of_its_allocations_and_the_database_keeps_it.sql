-- 571 — a receipt's allocated total is the sum of its allocation rows, and the database keeps it (POST-A-369).
--
-- THE DEFECT
--
-- `receipts.allocated_paise` (migration 050) was never written by anything. The comment above the pair said "unallocated = amount -
-- allocated; maintained at application layer" and the application kept only the second half: `settle_receipt_atomic` inserts the receipt
-- with `unallocated_paise` and leaves this column at its default of 0, the allocation route rewrites `unallocated_paise` and not this,
-- and the foreign-currency receipt path does the same. So on production on 1-11-2026 all 101 receipts held 0 here while their allocation
-- rows covered each of them in full, and the Receipts
-- tab, which prints this column as "Allocated", showed ₹0.00 allocated and ₹0.00 unallocated for a receipt of any size: two figures that
-- do not add up to the receipt, one of them false. (The tab's Unallocated column reads the stored `unallocated_paise`, which IS
-- maintained, so only the Allocated column was wrong.)
--
-- THE FIX, AND WHY IN THE DATABASE
--
-- The figure is a sum over rows the database owns, written by the API's privileged client, by `settle_receipt_atomic` (SECURITY DEFINER)
-- and by the reversal path, so keeping it in the one place every writer passes through is the only way it cannot be missed again. A row
-- trigger on `receipt_allocations` recomputes the receipt's total from its rows after every insert, delete, or update of the amount, of
-- the receipt a row belongs to (an update that moves a row recomputes BOTH receipts) or of `is_voided`. The existing receipts are
-- corrected once here.
--
-- WHAT COUNTS: only LIVE rows, those not `is_voided`. Reversing a receipt voids its allocation rows (migration 215) and the receipt
-- applies to nothing from then on, which is what the reversal path itself means by an allocation (it works on the non-voided rows
-- alone); the Receipts tab marks the receipt Reversed beside a total of nothing. This is a different question from migration 282's
-- party position, which deliberately does not filter on `is_voided` because it drops a reversed receipt whole before it reads them.
--
-- The recomputation is a SUM, not a delta, so it is idempotent and cannot drift if a statement is retried. It takes the receipt's row
-- lock BEFORE it sums, as a separate statement: under READ COMMITTED a second writer then waits for the first to commit and sums with
-- the first's rows in view (a sum taken in the same statement as the update would be read before the wait and written after it, and the
-- first writer's row would be missing from the total). Two receipts are locked in id order so a row moved between two receipts cannot
-- deadlock against another. It runs as the function's owner so the receipt update does not depend on the grants of whoever wrote the
-- allocation, and the receipt's own row-level edit log is unaffected (that trigger records signed-in writers only; a privileged write is
-- audited in the application).
--
-- WHAT IS DELIBERATELY NOT DONE: `unallocated_paise` is left as it is (the application maintains it and the screen reads it first); a
-- receipt's total is not checked against the settlement value here, because that is a rule about the receipt (cash plus tax deducted)
-- and the allocation route already refuses an over-allocation.
--
-- Nothing here transmits anything to a portal.

BEGIN;

CREATE OR REPLACE FUNCTION public.keep_receipt_allocated_total() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    v_new uuid;
    v_old uuid;
    v_id  uuid;
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN v_new := NEW.receipt_id; END IF;
    IF TG_OP IN ('DELETE', 'UPDATE') THEN v_old := OLD.receipt_id; END IF;
    -- Each receipt this row touches (one, or two when a row is moved), locked in id order.
    FOR v_id IN SELECT DISTINCT x FROM unnest(ARRAY[v_new, v_old]) AS x WHERE x IS NOT NULL ORDER BY x LOOP
        PERFORM 1 FROM public.receipts WHERE id = v_id FOR UPDATE;
        UPDATE public.receipts r
           SET allocated_paise = COALESCE((SELECT SUM(a.allocated_paise) FROM public.receipt_allocations a
                                            WHERE a.receipt_id = v_id AND NOT a.is_voided), 0)
         WHERE r.id = v_id;
    END LOOP;
    RETURN NULL;
END
$fn$;

-- A trigger function is not callable by anybody: take the default execute away so no signed-in role is ever offered it.
REVOKE ALL ON FUNCTION public.keep_receipt_allocated_total() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS receipt_allocations_keep_total ON public.receipt_allocations;
CREATE TRIGGER receipt_allocations_keep_total
    AFTER INSERT OR DELETE OR UPDATE OF allocated_paise, receipt_id, is_voided ON public.receipt_allocations
    FOR EACH ROW EXECUTE FUNCTION public.keep_receipt_allocated_total();

-- Correct what is there: every receipt whose stored figure differs from the sum of its live rows (nothing, for one with none).
DO $$
DECLARE
    v_fixed integer;
BEGIN
    WITH sums AS (
        SELECT receipt_id, SUM(allocated_paise) AS total FROM public.receipt_allocations WHERE NOT is_voided GROUP BY receipt_id
    ), wanted AS (
        SELECT r.id, COALESCE(s.total, 0) AS total FROM public.receipts r LEFT JOIN sums s ON s.receipt_id = r.id
    ), fixed AS (
        UPDATE public.receipts r
           SET allocated_paise = w.total
          FROM wanted w
         WHERE r.id = w.id AND r.allocated_paise IS DISTINCT FROM w.total
        RETURNING r.id
    )
    SELECT count(*) INTO v_fixed FROM fixed;
    RAISE NOTICE 'migration 571: % receipt(s) had an allocated total that differed from their live allocation rows and now carry the sum.', v_fixed;
END $$;

COMMENT ON COLUMN public.receipts.allocated_paise IS
    'The sum of this receipt''s live (not voided) receipt_allocations rows, kept by the receipt_allocations_keep_total trigger (migration 571). It was never written before that. POST-A-369.';

COMMIT;
