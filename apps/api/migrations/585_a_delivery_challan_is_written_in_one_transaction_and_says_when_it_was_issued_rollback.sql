-- Rollback of migration 585: drop the three functions, the two triggers and the moment-of-issue column.
--
-- REFUSES while any challan holds a moment of issue: dropping the column would lose a fact that cannot be reconstructed (updated_at is not
-- that moment). Run it only before the API reads the column, or after the moments have been kept elsewhere. Safe to run twice: with the
-- column already gone the guard has nothing to look at and the DROP ... IF EXISTS statements do nothing.

DO $$
DECLARE
    v_held bigint;
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'delivery_challans' AND column_name = 'issued_at') THEN
        -- A string, because a statement that names the column is parsed before the test above is evaluated.
        EXECUTE 'SELECT count(*) FROM public.delivery_challans WHERE issued_at IS NOT NULL' INTO v_held;
        IF v_held > 0 THEN
            RAISE EXCEPTION 'rollback of 585 refused: challans hold a stored moment of issue, which dropping the column would lose';
        END IF;
    END IF;
END $$;

DROP FUNCTION IF EXISTS public.correct_draft_challan_lines_atomic(uuid, uuid, uuid, jsonb, jsonb);
DROP FUNCTION IF EXISTS public.record_challan_lot_atomic(uuid, uuid, uuid, jsonb);
DROP FUNCTION IF EXISTS public.create_delivery_challan_atomic(jsonb, jsonb);
DROP TRIGGER IF EXISTS trg_delivery_challans_with_lots_are_not_cancelled ON public.delivery_challans;
DROP FUNCTION IF EXISTS public.delivery_challans_with_lots_are_not_cancelled();
DROP TRIGGER IF EXISTS trg_delivery_challans_issued_at_is_written_once ON public.delivery_challans;
DROP FUNCTION IF EXISTS public.delivery_challans_issued_at_is_written_once();
ALTER TABLE public.delivery_challans DROP COLUMN IF EXISTS issued_at;
