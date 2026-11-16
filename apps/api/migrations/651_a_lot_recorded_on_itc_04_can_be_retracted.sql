-- Migration 651: a lot recorded on FORM GST ITC-04 can be retracted (ledger POST-A-418).
--
-- WHAT WAS WRONG. `itc_04_service.record_return` inserted a lot (goods returned from a job worker, or lost or wasted) and nothing
-- changed or removed one. POST-A-398 refuses to cancel a challan with a lot against it (right for a true lot), which left no way out for
-- a lot recorded on the wrong challan: the challan could be neither corrected nor cancelled.
--
-- WHAT THIS DOES.
--  * `delivery_challan_returns.retracted_at / retracted_by / retraction_reason`: a retraction is a soft delete that keeps the row, the day
--    it was made, the person (an internal `users.id`, as `created_by`) and a reason. A CHECK needs a non-blank reason with a retraction,
--    and a trigger makes a retraction final: the three columns are written once, and a retracted row's figures are not changed.
--  * `retract_challan_lot_atomic(firm, client, challan, lot, reason, by)`: takes the challan's lock first (the lock a new lot and a cancel
--    take), refuses a lot that is not this challan's or is already retracted, retracts it and, if the challan was marked received back by
--    the lots and the live lots no longer bring every line back, puts it back to issued with no back day (the s.143 clock runs again),
--    all in one transaction.
--  * `record_challan_lot_atomic` (restated from migration 585, the last to define it) counts only live lots, for the room a line has left
--    and for the stamp that the challan is back, and refuses to write the retraction columns through a lot.
--  * the cancel trigger of 585 asks only about live lots, so a challan whose every lot was retracted can be cancelled.
-- Every other reader of the table (the ITC-04 statement, the record door's sums, the challan's received-back day, the order re-derivation)
-- is the API's and excludes retracted rows in the same change.
--
-- WHAT IT DOES NOT DO. It does not refuse a retraction once the period's ITC-04 is filed: the product records no ITC-04 filing (no table,
-- obligation or route), so there is nothing to ask. The statement is prepare-only and the CA furnishes it on the portal; the screen says so.
--
-- DEPLOY ORDER: ships with the code; the API falls back to the old readers' behaviour only by not filtering, so the code is deployed
-- with the migration (the columns must exist for the filters). SECURITY INVOKER, EXECUTE to service_role alone.
-- Reversible: 651_..._rollback.sql refuses while a lot is retracted (it would resurrect it).

BEGIN;

ALTER TABLE public.delivery_challan_returns
  ADD COLUMN IF NOT EXISTS retracted_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS retracted_by UUID,
  ADD COLUMN IF NOT EXISTS retraction_reason TEXT;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'delivery_challan_returns_retraction_says_why') THEN
    ALTER TABLE public.delivery_challan_returns ADD CONSTRAINT delivery_challan_returns_retraction_says_why
      CHECK ((retracted_at IS NULL AND retraction_reason IS NULL AND retracted_by IS NULL)
          OR (retracted_at IS NOT NULL AND btrim(coalesce(retraction_reason, '')) <> ''));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_delivery_challan_returns_live
  ON public.delivery_challan_returns (challan_id) WHERE retracted_at IS NULL;

CREATE OR REPLACE FUNCTION public.delivery_challan_returns_retraction_is_final()
RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_catalog AS $$
BEGIN
    IF OLD.retracted_at IS NOT NULL THEN
        RAISE EXCEPTION 'a retracted lot is not changed' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_delivery_challan_returns_retraction_is_final ON public.delivery_challan_returns;
CREATE TRIGGER trg_delivery_challan_returns_retraction_is_final
    BEFORE UPDATE ON public.delivery_challan_returns
    FOR EACH ROW EXECUTE FUNCTION public.delivery_challan_returns_retraction_is_final();

CREATE OR REPLACE FUNCTION public.delivery_challans_with_lots_are_not_cancelled()
RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_catalog AS $$
BEGIN
    IF NEW.status = 'cancelled' AND OLD.status IS DISTINCT FROM 'cancelled'
       AND EXISTS (SELECT 1 FROM public.delivery_challan_returns WHERE challan_id = NEW.id AND retracted_at IS NULL) THEN
        RAISE EXCEPTION 'challan_has_lots' USING ERRCODE = 'P0001',
            DETAIL = 'goods have been recorded as back from the job worker on this challan, so it is finished by recording the rest and is not cancelled';
    END IF;
    RETURN NEW;
END $$;

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
      FROM public.delivery_challan_returns WHERE challan_line_id = v_line_id AND retracted_at IS NULL;
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
      FROM jsonb_object_keys(p_lot) AS k
     WHERE k NOT IN ('challan_id', 'challan_line_id', 'firm_id', 'client_id', 'retracted_at', 'retracted_by', 'retraction_reason');
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
       AND l.quantity > (SELECT coalesce(sum(r.quantity_returned), 0) FROM public.delivery_challan_returns r
                          WHERE r.challan_line_id = l.id AND r.retracted_at IS NULL);
    IF v_open = 0 THEN
        SELECT max(returned_on) INTO v_last FROM public.delivery_challan_returns WHERE challan_id = p_challan_id AND retracted_at IS NULL;
        UPDATE public.delivery_challans
           SET status = 'received_back', received_back_on = v_last, updated_at = now()
         WHERE id = p_challan_id AND firm_id = p_firm_id AND client_id = p_client_id AND status = 'issued';
        v_stamped := true;
    END IF;

    RETURN jsonb_build_object('lot', v_lot, 'challan_marked_received_back', v_stamped, 'received_back_on', v_last);
END
$$;

CREATE OR REPLACE FUNCTION public.retract_challan_lot_atomic(
    p_firm_id uuid, p_client_id uuid, p_challan_id uuid, p_lot_id uuid, p_reason text, p_by uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = public, pg_catalog AS $$
DECLARE
    v_status text; v_reason text; v_lot jsonb; v_open bigint; v_reverted boolean := false;
BEGIN
    IF btrim(coalesce(p_reason, '')) = '' THEN
        RAISE EXCEPTION 'retraction_needs_reason' USING ERRCODE = 'P0001';
    END IF;
    SELECT status, reason INTO v_status, v_reason FROM public.delivery_challans
     WHERE id = p_challan_id AND firm_id = p_firm_id AND client_id = p_client_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'challan_not_found' USING ERRCODE = 'P0002'; END IF;
    IF v_status NOT IN ('issued', 'received_back') THEN
        RAISE EXCEPTION 'challan_not_issued' USING ERRCODE = 'P0001', DETAIL = format('status is %s', coalesce(v_status, 'null'));
    END IF;
    UPDATE public.delivery_challan_returns
       SET retracted_at = now(), retracted_by = p_by, retraction_reason = btrim(p_reason)
     WHERE id = p_lot_id AND challan_id = p_challan_id AND firm_id = p_firm_id AND client_id = p_client_id AND retracted_at IS NULL
    RETURNING to_jsonb(delivery_challan_returns) INTO v_lot;
    IF v_lot IS NULL THEN RAISE EXCEPTION 'lot_not_found' USING ERRCODE = 'P0002'; END IF;

    IF v_status = 'received_back' THEN
        SELECT count(*) INTO v_open FROM public.delivery_challan_lines l
         WHERE l.challan_id = p_challan_id
           AND l.quantity > (SELECT coalesce(sum(r.quantity_returned), 0) FROM public.delivery_challan_returns r
                              WHERE r.challan_line_id = l.id AND r.retracted_at IS NULL);
        -- A challan marked back with no lot at all was marked by the whole-challan door and is left as it is.
        IF v_open > 0 AND EXISTS (SELECT 1 FROM public.delivery_challan_returns WHERE challan_id = p_challan_id) THEN
            UPDATE public.delivery_challans SET status = 'issued', received_back_on = NULL, updated_at = now()
             WHERE id = p_challan_id AND firm_id = p_firm_id AND client_id = p_client_id AND status = 'received_back';
            v_reverted := true;
        END IF;
    END IF;
    RETURN jsonb_build_object('lot', v_lot, 'challan_back_to_issued', v_reverted);
END $$;

REVOKE ALL ON FUNCTION public.record_challan_lot_atomic(uuid, uuid, uuid, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retract_challan_lot_atomic(uuid, uuid, uuid, uuid, text, uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.delivery_challan_returns_retraction_is_final() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.delivery_challans_with_lots_are_not_cancelled() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_challan_lot_atomic(uuid, uuid, uuid, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.retract_challan_lot_atomic(uuid, uuid, uuid, uuid, text, uuid) TO service_role;

COMMIT;
