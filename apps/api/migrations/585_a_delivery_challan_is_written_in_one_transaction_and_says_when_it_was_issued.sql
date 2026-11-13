-- Migration 585: a delivery challan is written in ONE transaction, and the moment it was issued is stored (ledger POST-A-419).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- The API wrote a delivery challan as several statements, each its own request and its own transaction:
--   (a) `create_challan` inserted the header and then each line on its own, so a line insert that failed left a draft whose header
--       totals more than the lines it holds;
--   (b) `itc_04_service.record_return` inserted a lot (goods returned from a job worker) and, when every line had come back, stamped
--       the challan "received back" in a second statement, so a cancel between the two left a lot recorded on a challan that was not
--       marked back, and two lots recorded in the same instant could each pass the check that a lot is not more than the line has left;
--   (c) `issue_challan` kept the moment it issued a challan in `updated_at`, which any later amendment overwrites, and in an audit
--       event that is allowed to be lost, so nothing says when the goods left;
--   (d) the correction of a draft's lines was the header's compare-and-set and then one statement per line, so a draft issued in that
--       gap could be left an issued challan whose HSN code had just changed, and a write that failed part-way left the header written
--       and the lines not.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
--  * `delivery_challans.issued_at` (timestamptz, NULL = not recorded). It is NOT backfilled: a challan issued before this has no stored
--    moment, and `updated_at` is not that moment (any amendment moves it), so a guess would be a stored wrong fact. A trigger keeps it
--    honest: a draft has no moment of issue, and once written it is never changed.
--  * `create_delivery_challan_atomic(header, lines)`: the header and every line in one transaction. A challan is made as a draft, so the
--    header may not name an id, a status other than draft, a moment of issue or a day it came back; every line takes the header's own
--    id, firm and client, whatever an element says, so a line cannot be put on another challan or another client through this call.
--  * `record_challan_lot_atomic(firm, client, challan, lot)`: takes the challan's lock FOR UPDATE first, refuses unless it is issued,
--    refuses a lot that is more than its line has left (judged on the lots as they stand AFTER any other lot in flight has committed),
--    inserts the lot and, when every line has now come back, stamps the challan received back on the latest day any lot came back, all
--    in the one transaction. The Python keeps its sentences for the ordinary case and reads these refusals for the race it cannot see.
--  * `correct_draft_challan_lines_atomic(firm, client, challan, header, fixes)`: takes the challan's lock first, refuses unless it is a
--    draft, applies the header's fields and each line's description and HSN code together, and refuses a fix that names a line the
--    challan does not hold or names a column other than the description and the HSN code, which undoes the header's correction too.
--  * a trigger that refuses a status change to cancelled while a lot is recorded against the challan (POST-A-398's rule, which the
--    API asks first and in words; the database asks it again so a lot committed between the API's read and its write cannot leave a
--    cancelled challan with goods returned on it).
--
-- All three are SECURITY INVOKER (the caller's own privileges judge every row written; the challan tables are written by the API's
-- privileged client and by nobody signed in). EXECUTE is revoked from PUBLIC, anon and authenticated (Supabase grants it on a new
-- public function to the signed-in roles by default, and a revoke from PUBLIC alone leaves those two) and given to service_role alone.
-- The create takes no lock, because it makes a new row; the lot and the correction take the challan's.
--
-- DEPLOY ORDER: THIS MIGRATION SHIPS BEFORE THE CODE THAT USES IT. The boot-time schema check builds the columns it expects from the
-- migration files in the image, so the API built from this change expects `issued_at` and answers /health 503 until the migration
-- applies (the drift watch turns it healthy again by itself), as for every migration that adds a column. The code that WRITES
-- `issued_at` and CALLS the functions would fail at run time in that window, which no guard would catch, so it ships in a later change,
-- once the database has them.
--
-- Idempotent. Reversible: 585_..._rollback.sql drops the functions, the trigger and the column, and refuses while a challan holds a
-- moment of issue (it would be lost).

ALTER TABLE public.delivery_challans
  ADD COLUMN IF NOT EXISTS issued_at TIMESTAMPTZ;

COMMENT ON COLUMN public.delivery_challans.issued_at IS
  'The moment the challan was issued, i.e. the moment the goods are recorded as having left on it. NULL is NOT RECORDED: a challan issued '
  'before this column existed has none, and updated_at is not a substitute (any amendment moves it). Written once, by the one door that '
  'issues a challan; a draft has none.';

CREATE OR REPLACE FUNCTION public.delivery_challans_issued_at_is_written_once()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_catalog
AS $$
BEGIN
    IF NEW.issued_at IS NOT NULL AND NEW.status = 'draft' THEN
        RAISE EXCEPTION 'a draft challan has no moment of issue' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.issued_at IS NOT NULL AND NEW.issued_at IS DISTINCT FROM OLD.issued_at THEN
        RAISE EXCEPTION 'the moment a challan was issued is written once and is not changed' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_delivery_challans_issued_at_is_written_once ON public.delivery_challans;
CREATE TRIGGER trg_delivery_challans_issued_at_is_written_once
    BEFORE INSERT OR UPDATE ON public.delivery_challans
    FOR EACH ROW EXECUTE FUNCTION public.delivery_challans_issued_at_is_written_once();

-- ── a challan with a lot recorded on it is not cancelled (POST-A-398), asked again by the database ─────────────────────────────────

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

DROP TRIGGER IF EXISTS trg_delivery_challans_with_lots_are_not_cancelled ON public.delivery_challans;
CREATE TRIGGER trg_delivery_challans_with_lots_are_not_cancelled
    BEFORE UPDATE OF status ON public.delivery_challans
    FOR EACH ROW EXECUTE FUNCTION public.delivery_challans_with_lots_are_not_cancelled();

-- ── (a) the header and its lines, in one transaction ─────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.create_delivery_challan_atomic(p_header jsonb, p_lines jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
DECLARE
    v_keys      text;
    v_line_keys text;
    v_line      jsonb;
    v_id        uuid;
    v_row       jsonb;
BEGIN
    IF p_header IS NULL OR jsonb_typeof(p_header) <> 'object' THEN
        RAISE EXCEPTION 'create_delivery_challan_atomic: the header must be a JSON object' USING ERRCODE = '22023';
    END IF;
    IF p_lines IS NULL OR jsonb_typeof(p_lines) <> 'array' THEN
        RAISE EXCEPTION 'create_delivery_challan_atomic: the lines must be a JSON array' USING ERRCODE = '22023';
    END IF;
    IF NOT (p_header ? 'firm_id' AND p_header ? 'client_id') THEN
        RAISE EXCEPTION 'create_delivery_challan_atomic: the header names no firm or no client' USING ERRCODE = '22023';
    END IF;
    IF p_header ?| ARRAY['id', 'issued_at', 'received_back_on'] THEN
        RAISE EXCEPTION 'create_delivery_challan_atomic: a challan is made as a draft, with no id of its own choosing, no moment of issue and no day it came back'
            USING ERRCODE = '22023';
    END IF;
    IF coalesce(p_header ->> 'status', 'draft') <> 'draft' THEN
        RAISE EXCEPTION 'challan_not_a_draft' USING ERRCODE = 'P0001';
    END IF;

    SELECT string_agg(quote_ident(k), ', ') INTO v_keys FROM jsonb_object_keys(p_header) AS k;
    EXECUTE format(
        'INSERT INTO public.delivery_challans (%1$s) SELECT %1$s FROM jsonb_populate_record(NULL::public.delivery_challans, $1) '
        'RETURNING id, to_jsonb(delivery_challans)', v_keys)
        INTO v_id, v_row USING p_header;

    -- One statement per line, each with ITS OWN keys: a line that does not name a column takes the column's default, as the header does
    -- (a union of every line's keys would give it NULL). The challan's own id, firm and client are on every line, whatever an element says:
    -- a line cannot be put on another challan or another client through this call.
    FOR v_line IN SELECT e FROM jsonb_array_elements(p_lines) WITH ORDINALITY AS t(e, n) ORDER BY n LOOP
        IF jsonb_typeof(v_line) <> 'object' THEN
            RAISE EXCEPTION 'create_delivery_challan_atomic: every line must be a JSON object' USING ERRCODE = '22023';
        END IF;
        SELECT string_agg(quote_ident(k), ', ') INTO v_line_keys
          FROM jsonb_object_keys(v_line) AS k WHERE k NOT IN ('challan_id', 'firm_id', 'client_id');
        EXECUTE format(
            'INSERT INTO public.delivery_challan_lines (challan_id, firm_id, client_id%1$s) '
            'SELECT $2, $3, $4%1$s FROM jsonb_populate_record(NULL::public.delivery_challan_lines, $1)',
            coalesce(', ' || v_line_keys, ''))
            USING v_line, v_id, (p_header ->> 'firm_id')::uuid, (p_header ->> 'client_id')::uuid;
    END LOOP;

    RETURN v_row;
END
$$;

-- ── (b) one lot of goods back from a job worker, and the stamp it may complete ───────────────────────────────────

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

-- ── (d) a draft's corrections, header and lines together ─────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.correct_draft_challan_lines_atomic(
    p_firm_id uuid, p_client_id uuid, p_challan_id uuid, p_header jsonb, p_fixes jsonb)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
DECLARE
    v_status text;
    v_keys   text;
    v_done   integer;
BEGIN
    IF p_header IS NULL OR jsonb_typeof(p_header) <> 'object' THEN
        RAISE EXCEPTION 'correct_draft_challan_lines_atomic: the header patch must be a JSON object' USING ERRCODE = '22023';
    END IF;
    IF p_fixes IS NULL OR jsonb_typeof(p_fixes) <> 'array' THEN
        RAISE EXCEPTION 'correct_draft_challan_lines_atomic: the fixes must be a JSON array' USING ERRCODE = '22023';
    END IF;
    IF p_header ?| ARRAY['id', 'firm_id', 'client_id', 'status', 'issued_at', 'received_back_on'] THEN
        RAISE EXCEPTION 'correct_draft_challan_lines_atomic: a correction of a draft does not name its id, its owner, its status or a day'
            USING ERRCODE = '22023';
    END IF;

    -- A fix names a line and the description and/or the HSN code to give it, nothing else, and each line once.
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_fixes) AS f
                WHERE jsonb_typeof(f) <> 'object' OR NOT (f ? 'id')
                   OR EXISTS (SELECT 1 FROM jsonb_object_keys(f) AS k WHERE k NOT IN ('id', 'description', 'hsn_sac'))) THEN
        RAISE EXCEPTION 'correct_draft_challan_lines_atomic: a correction names a line by id and gives its description and/or its HSN code, nothing else'
            USING ERRCODE = '22023';
    END IF;
    IF (SELECT count(DISTINCT f ->> 'id') FROM jsonb_array_elements(p_fixes) AS f) <> jsonb_array_length(p_fixes) THEN
        RAISE EXCEPTION 'duplicate_fix' USING ERRCODE = 'P0001', DETAIL = 'a line is corrected once in a request';
    END IF;

    SELECT status INTO v_status FROM public.delivery_challans
     WHERE id = p_challan_id AND firm_id = p_firm_id AND client_id = p_client_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'challan_not_found' USING ERRCODE = 'P0002';
    END IF;
    IF v_status IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION 'challan_not_draft' USING ERRCODE = 'P0001', DETAIL = format('status is %s', coalesce(v_status, 'null'));
    END IF;

    SELECT string_agg(quote_ident(k), ', ') INTO v_keys FROM jsonb_object_keys(p_header) AS k;
    IF v_keys IS NOT NULL THEN
        EXECUTE format(
            'UPDATE public.delivery_challans SET (%1$s) = (SELECT %1$s FROM jsonb_populate_record(NULL::public.delivery_challans, $1)) '
            'WHERE id = $2 AND firm_id = $3 AND client_id = $4', v_keys)
            USING p_header, p_challan_id, p_firm_id, p_client_id;
    END IF;

    -- A key that is absent leaves the column as it is; one that is present (null included) writes it.
    UPDATE public.delivery_challan_lines l
       SET description = CASE WHEN f ? 'description' THEN f ->> 'description' ELSE l.description END,
           hsn_sac     = CASE WHEN f ? 'hsn_sac'     THEN f ->> 'hsn_sac'     ELSE l.hsn_sac END
      FROM jsonb_array_elements(p_fixes) AS f
     WHERE l.id = (f ->> 'id')::uuid AND l.challan_id = p_challan_id AND l.firm_id = p_firm_id AND l.client_id = p_client_id;
    GET DIAGNOSTICS v_done = ROW_COUNT;
    IF v_done <> jsonb_array_length(p_fixes) THEN
        RAISE EXCEPTION 'line_not_found' USING ERRCODE = 'P0002',
            DETAIL = format('%s of %s corrections named a line this challan holds', v_done, jsonb_array_length(p_fixes));
    END IF;

    RETURN v_done;
END
$$;

REVOKE ALL ON FUNCTION public.create_delivery_challan_atomic(jsonb, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_challan_lot_atomic(uuid, uuid, uuid, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.correct_draft_challan_lines_atomic(uuid, uuid, uuid, jsonb, jsonb) FROM PUBLIC, anon, authenticated;
-- The two trigger functions are not callable as functions at all (a trigger function takes no arguments and returns trigger), and are
-- closed to the signed-in roles as well so that no grant listing names them.
REVOKE ALL ON FUNCTION public.delivery_challans_issued_at_is_written_once() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.delivery_challans_with_lots_are_not_cancelled() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_delivery_challan_atomic(jsonb, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_challan_lot_atomic(uuid, uuid, uuid, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.correct_draft_challan_lines_atomic(uuid, uuid, uuid, jsonb, jsonb) TO service_role;

DO $$
DECLARE
    f text;
BEGIN
    FOREACH f IN ARRAY ARRAY[
        'public.create_delivery_challan_atomic(jsonb, jsonb)',
        'public.record_challan_lot_atomic(uuid, uuid, uuid, jsonb)',
        'public.correct_draft_challan_lines_atomic(uuid, uuid, uuid, jsonb, jsonb)'
    ] LOOP
        IF to_regprocedure(f) IS NULL THEN
            RAISE EXCEPTION 'migration 585: % was not created', f;
        END IF;
        IF has_function_privilege('anon', f, 'EXECUTE') OR has_function_privilege('public', f, 'EXECUTE')
           OR has_function_privilege('authenticated', f, 'EXECUTE') THEN
            RAISE EXCEPTION 'migration 585: % is executable by PUBLIC, anon or authenticated', f;
        END IF;
        IF (SELECT prosecdef FROM pg_proc WHERE oid = f::regprocedure) THEN
            RAISE EXCEPTION 'migration 585: % must be SECURITY INVOKER', f;
        END IF;
    END LOOP;
END $$;
