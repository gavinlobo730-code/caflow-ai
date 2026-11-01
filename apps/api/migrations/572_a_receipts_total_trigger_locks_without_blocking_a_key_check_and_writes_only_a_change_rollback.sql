-- Rollback of 572: put migration 571's definition of the function back (FOR UPDATE, and the UPDATE on every call). The trigger itself is
-- untouched by 572 and by this file.
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
REVOKE ALL ON FUNCTION public.keep_receipt_allocated_total() FROM PUBLIC, anon, authenticated;
COMMIT;
