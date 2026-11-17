-- Rollback of migration 651. Refuses while a lot is retracted: dropping the columns would bring it back.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'delivery_challan_returns' AND column_name = 'retracted_at') THEN
    IF (SELECT count(*) FROM public.delivery_challan_returns WHERE retracted_at IS NOT NULL) > 0 THEN
      RAISE EXCEPTION 'rollback of 651 refused: retracted lots exist, and dropping the columns would bring them back';
    END IF;
  END IF;
END $$;
-- Migration 585's definitions of the two functions 651 restated, put back BEFORE the columns they no longer read go.
CREATE OR REPLACE FUNCTION public.delivery_challans_with_lots_are_not_cancelled()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_catalog
AS $$
BEGIN
    IF NEW.status = 'cancelled' AND OLD.status IS DISTINCT FROM 'cancelled'
       AND EXISTS (SELECT 1 FROM public.delivery_challan_returns WHERE challan_id = NEW.id) THEN
        RAISE EXCEPTION 'challan_has_lots' USING ERRCODE = 'P0001',
            DETAIL = 'goods have been recorded as back from the job worker on this challan, so it is finished by recording the rest and is not cancelled';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION public.record_challan_lot_atomic(p_firm_id uuid, p_client_id uuid, p_challan_id uuid, p_lot jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
DECLARE
    v_status   text;
    v_reason   text;
    v_line_id  uuid;
    v_sent     numeric;
    v_back     numeric;
    v_lost     numeric;
    v_now_back numeric;
    v_now_lost numeric;
    v_keys     text;
    v_lot      jsonb;
    v_open     bigint;
    v_last     date;
    v_stamped  boolean := false;
BEGIN
    IF p_lot IS NULL OR jsonb_typeof(p_lot) <> 'object' THEN
        RAISE EXCEPTION 'record_challan_lot_atomic: the lot must be a JSON object' USING ERRCODE = '22023';
    END IF;

    -- The challan's lock first: a cancel or another lot in flight finishes before this is judged.
    SELECT status, reason INTO v_status, v_reason FROM public.delivery_challans
     WHERE id = p_challan_id AND firm_id = p_firm_id AND client_id = p_client_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'challan_not_found' USING ERRCODE = 'P0002';
    END IF;
    IF v_status IS DISTINCT FROM 'issued' THEN
        RAISE EXCEPTION 'challan_not_issued' USING ERRCODE = 'P0001', DETAIL = format('status is %s', coalesce(v_status, 'null'));
    END IF;
    -- A lot is goods back from a JOB WORKER (FORM GST ITC-04): a challan for another reason has none. The caller's other floors (the day
    -- the goods came back is not before the day they went, nor after today in India) stay with the caller, which words them.
    IF v_reason IS DISTINCT FROM 'job_work' THEN
        RAISE EXCEPTION 'challan_not_job_work' USING ERRCODE = 'P0001', DETAIL = format('reason is %s', coalesce(v_reason, 'null'));
    END IF;

    IF NOT (p_lot ? 'challan_line_id') OR (p_lot ->> 'challan_line_id') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
        RAISE EXCEPTION 'line_not_found' USING ERRCODE = 'P0002';
    END IF;
    v_line_id := (p_lot ->> 'challan_line_id')::uuid;
    SELECT quantity INTO v_sent FROM public.delivery_challan_lines
     WHERE id = v_line_id AND challan_id = p_challan_id AND firm_id = p_firm_id AND client_id = p_client_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'line_not_found' USING ERRCODE = 'P0002';
    END IF;

    SELECT coalesce(sum(quantity_returned), 0), coalesce(sum(quantity_lost_or_wasted), 0) INTO v_back, v_lost
      FROM public.delivery_challan_returns WHERE challan_line_id = v_line_id;
    -- Judged on the quantities as the column will STORE them (three decimals): a lot of 1.0005 and 1.0005 against a line of 2.001 is 2.002
    -- once stored.
    v_now_back := round(coalesce((p_lot ->> 'quantity_returned')::numeric, 0), 3);
    v_now_lost := round(coalesce((p_lot ->> 'quantity_lost_or_wasted')::numeric, 0), 3);
    IF v_now_back + v_now_lost > v_sent - v_back - v_lost THEN
        RAISE EXCEPTION 'lot_exceeds_line' USING ERRCODE = 'P0001',
            DETAIL = format('sent %s, back %s, lost %s, now %s and %s', v_sent, v_back, v_lost, v_now_back, v_now_lost);
    END IF;

    -- The challan, the line, the firm and the client are the ones judged above, whatever the lot says.
    SELECT string_agg(quote_ident(k), ', ') INTO v_keys
      FROM jsonb_object_keys(p_lot) AS k WHERE k NOT IN ('challan_id', 'challan_line_id', 'firm_id', 'client_id');
    EXECUTE format(
        'INSERT INTO public.delivery_challan_returns (challan_id, challan_line_id, firm_id, client_id%1$s) '
        'SELECT $2, $3, $4, $5%1$s FROM jsonb_populate_record(NULL::public.delivery_challan_returns, $1) '
        'RETURNING to_jsonb(delivery_challan_returns)', coalesce(', ' || v_keys, ''))
        INTO v_lot USING p_lot, p_challan_id, v_line_id, p_firm_id, p_client_id;

    -- Has EVERY line of the challan now come back in full? Then the clock stops, on the latest day any lot came back (the same stamp
    -- the whole-challan door writes). Lost or wasted goods are not goods that came back.
    SELECT count(*) INTO v_open
      FROM public.delivery_challan_lines l
     WHERE l.challan_id = p_challan_id
       AND l.quantity > (SELECT coalesce(sum(r.quantity_returned), 0) FROM public.delivery_challan_returns r WHERE r.challan_line_id = l.id);
    IF v_open = 0 THEN
        SELECT max(returned_on) INTO v_last FROM public.delivery_challan_returns WHERE challan_id = p_challan_id;
        UPDATE public.delivery_challans
           SET status = 'received_back', received_back_on = v_last, updated_at = now()
         WHERE id = p_challan_id AND firm_id = p_firm_id AND client_id = p_client_id AND status = 'issued';
        v_stamped := true;
    END IF;

    RETURN jsonb_build_object('lot', v_lot, 'challan_marked_received_back', v_stamped, 'received_back_on', v_last);
END
$$;

DROP FUNCTION IF EXISTS public.retract_challan_lot_atomic(uuid, uuid, uuid, uuid, text, uuid);
DROP TRIGGER IF EXISTS trg_delivery_challan_returns_retraction_is_final ON public.delivery_challan_returns;
DROP FUNCTION IF EXISTS public.delivery_challan_returns_retraction_is_final();
ALTER TABLE public.delivery_challan_returns DROP CONSTRAINT IF EXISTS delivery_challan_returns_retraction_says_why;
DROP INDEX IF EXISTS public.idx_delivery_challan_returns_live;
ALTER TABLE public.delivery_challan_returns DROP COLUMN IF EXISTS retracted_at, DROP COLUMN IF EXISTS retracted_by, DROP COLUMN IF EXISTS retraction_reason;
