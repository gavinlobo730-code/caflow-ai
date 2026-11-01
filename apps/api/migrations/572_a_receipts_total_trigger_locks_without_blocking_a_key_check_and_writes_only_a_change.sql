-- 572 — the receipt total's trigger takes a lock a foreign-key check can share, and writes the receipt only when the total changes
-- (POST-A-369, from the independent review of migration 571).
--
-- WHAT THE REVIEW FOUND IN 571 (already applied to production on 1-11-2026; the total it keeps was right on all 101 receipts)
--
-- 1. A DEADLOCK WINDOW. The trigger locked the receipt with `SELECT ... FOR UPDATE`. Every INSERT into `receipt_allocations` first runs
--    its foreign-key check on `receipt_id`, which holds `FOR KEY SHARE` on the receipt row, and FOR UPDATE conflicts with KEY SHARE. Two
--    transactions writing allocations for one receipt (a double-submitted allocation request, an allocation racing a reversal) could each
--    pass the key check, hold KEY SHARE, and then each ask to upgrade to FOR UPDATE and wait for the other: Postgres aborts one of them
--    after about a second with 40P01. The window is the gap between one statement's key check and its trigger, so it is small, and 571's own
--    two-writer test could not hit it. `FOR NO KEY UPDATE` does not conflict with KEY SHARE, still conflicts with itself (so concurrent
--    recomputes of one receipt are still serialised, which is the whole reason for the lock), and is the strength the UPDATE below takes anyway.
--
-- 2. A WRITE ON EVERY ROW. The trigger ran its UPDATE of the receipt whether or not the total had changed. A multi-row statement fires the
--    trigger once per row after the statement, and every call after the first re-wrote the same value: a new version of the receipt row
--    each time and, where an acting person is carried (migrations 545 and 547), a full `update` row in `audit_log` each time. The header of 571
--    said the receipt's edit log was unaffected; it is not. The UPDATE now says `AND allocated_paise IS DISTINCT FROM <the sum>`, so a call
--    that finds the total already right writes nothing.
--
-- WHAT IS DELIBERATELY NOT CHANGED: the sum (live rows only), the lock-then-sum order, the columns that fire the trigger, the grants. A change
-- of the total that really happens (an allocation added, taken away, moved or voided) still updates the receipt and so still leaves an
-- `audit_log` row for the receipt where a person is carried; that row is an honest record of the figure moving.
--
-- Derived from migration 571, the last definer of this function (found by number). Nothing here transmits anything to a portal.

BEGIN;

CREATE OR REPLACE FUNCTION public.keep_receipt_allocated_total() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    v_new   uuid;
    v_old   uuid;
    v_id    uuid;
    v_total bigint;
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN v_new := NEW.receipt_id; END IF;
    IF TG_OP IN ('DELETE', 'UPDATE') THEN v_old := OLD.receipt_id; END IF;
    -- Each receipt this row touches (one, or two when a row is moved), locked in id order.
    FOR v_id IN SELECT DISTINCT x FROM unnest(ARRAY[v_new, v_old]) AS x WHERE x IS NOT NULL ORDER BY x LOOP
        PERFORM 1 FROM public.receipts WHERE id = v_id FOR NO KEY UPDATE;
        SELECT COALESCE(SUM(a.allocated_paise), 0) INTO v_total
          FROM public.receipt_allocations a
         WHERE a.receipt_id = v_id AND NOT a.is_voided;
        UPDATE public.receipts r
           SET allocated_paise = v_total
         WHERE r.id = v_id AND r.allocated_paise IS DISTINCT FROM v_total;
    END LOOP;
    RETURN NULL;
END
$fn$;

-- CREATE OR REPLACE keeps the function's grants; say them again so this file does not depend on that.
REVOKE ALL ON FUNCTION public.keep_receipt_allocated_total() FROM PUBLIC, anon, authenticated;

COMMIT;
