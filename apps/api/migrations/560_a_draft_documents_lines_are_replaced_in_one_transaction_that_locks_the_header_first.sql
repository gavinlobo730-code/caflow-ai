-- Migration 560: a draft document's lines are replaced in ONE transaction that takes the header's lock first (ledger POST-A-332).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- The API replaced the lines of a draft invoice, bill or note as a DELETE of the old lines and then an INSERT of the new ones, two
-- requests (the notes inserted one line per request), and updated the header after both. A second session that issued the document
-- between the two requests left an ISSUED document with no lines: the insert was refused by migration 539's draft rule (42501), the
-- saver saw only a generic failure, and the document's PDF and any rate-wise or HSN build from its lines came out empty. Before 539
-- the insert would have succeeded and left an issued document whose lines differ from its journal, so the race is older; 539 changed
-- the outcome from edited lines to lost lines. The window is the Singapore to Mumbai round trips between the requests, tens of
-- milliseconds.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- `public.replace_draft_document_lines(document, id, firm, lines)` takes the HEADER row FOR UPDATE first (a function that wrote the
-- lines first and the header after was measured to deadlock against a concurrent one: one deadlock in a two-transaction run, none with
-- the header first), refuses in words if the document is not found for the firm or is no longer a draft, then deletes the old lines and
-- inserts the new ones, all in the one transaction the call is. Issuing a document updates its header, so an issue that wins the race
-- makes this call answer 'document_not_draft' and changes nothing, and one that comes after waits for this call to commit and sees
-- the new lines.
--
-- It is SECURITY INVOKER on purpose: the caller's own privileges, the accounting write tier of migration 539 and the draft rule of its
-- trigger still judge every line written (the privileged client is not judged, as everywhere). EXECUTE is revoked from PUBLIC and given
-- to the two roles the API uses. The six documents are named in a CASE and not taken from the caller, so the function cannot be pointed
-- at another table; the lines are inserted with the columns the caller names (the union of the keys of the elements, a column no
-- element names takes its default, the same thing a PostgREST bulk insert does) and with the document's own id as their foreign key,
-- whatever an element says, so a line cannot be moved to another document through this call.
--
-- DEPLOY ORDER: the API falls back to the old two-step replacement while this function is not yet in the database (PGRST202 or
-- "function ... does not exist"), the precedent of the receipt and fee-billing services, so either side can ship first. The fallback
-- is deleted once this is on production.
--
-- Idempotent. Reversible: 559_..._rollback.sql drops the function.

CREATE OR REPLACE FUNCTION public.replace_draft_document_lines(
    p_document     text,
    p_document_id  uuid,
    p_firm_id      uuid,
    p_lines        jsonb
) RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
DECLARE
    v_header text;
    v_lines  text;
    v_fk     text;
    v_status text;
    v_found  bigint;
    v_keys   text;
BEGIN
    CASE p_document
        WHEN 'sales_invoice'        THEN v_header := 'client_sales_invoices';  v_lines := 'client_sales_invoice_lines';  v_fk := 'sales_invoice_id';
        WHEN 'purchase_bill'        THEN v_header := 'purchase_bills';         v_lines := 'purchase_bill_lines';         v_fk := 'bill_id';
        WHEN 'credit_note'          THEN v_header := 'credit_notes';           v_lines := 'credit_note_lines';           v_fk := 'credit_note_id';
        WHEN 'debit_note'           THEN v_header := 'debit_notes';            v_lines := 'debit_note_lines';            v_fk := 'debit_note_id';
        WHEN 'sales_debit_note'     THEN v_header := 'sales_debit_notes';      v_lines := 'sales_debit_note_lines';      v_fk := 'debit_note_id';
        WHEN 'purchase_credit_note' THEN v_header := 'purchase_credit_notes';  v_lines := 'purchase_credit_note_lines';  v_fk := 'credit_note_id';
        ELSE
            RAISE EXCEPTION 'replace_draft_document_lines: unknown document kind %', p_document USING ERRCODE = '22023';
    END CASE;

    IF p_lines IS NULL OR jsonb_typeof(p_lines) <> 'array' THEN
        RAISE EXCEPTION 'replace_draft_document_lines: the lines must be a JSON array' USING ERRCODE = '22023';
    END IF;

    -- The header first, locked, judged on its state AFTER any issue that was in flight has committed.
    EXECUTE format('SELECT status FROM public.%I WHERE id = $1 AND firm_id = $2 FOR UPDATE', v_header)
        INTO v_status USING p_document_id, p_firm_id;
    GET DIAGNOSTICS v_found = ROW_COUNT;
    IF v_found = 0 THEN
        RAISE EXCEPTION 'document_not_found' USING ERRCODE = 'P0002';
    END IF;
    IF v_status IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION 'document_not_draft' USING ERRCODE = 'P0001', DETAIL = format('status is %s', coalesce(v_status, 'null'));
    END IF;

    EXECUTE format('DELETE FROM public.%I WHERE %I = $1', v_lines, v_fk) USING p_document_id;

    IF jsonb_array_length(p_lines) > 0 THEN
        -- The document's own id is the foreign key of every line it is given, whatever an element says: a line cannot be moved to
        -- another document through this call. The other columns are the union of the keys the elements name.
        SELECT string_agg(DISTINCT quote_ident(k), ', ') INTO v_keys
          FROM jsonb_array_elements(p_lines) AS e, jsonb_object_keys(e) AS k
         WHERE k <> v_fk;
        EXECUTE format(
            'INSERT INTO public.%1$I (%3$I%2$s) SELECT $2%4$s FROM jsonb_populate_recordset(NULL::public.%1$I, $1)',
            v_lines,
            coalesce(', ' || v_keys, ''),
            v_fk,
            coalesce(', ' || v_keys, '')
        ) USING p_lines, p_document_id;
    END IF;

    RETURN jsonb_array_length(p_lines);
END
$$;

REVOKE ALL ON FUNCTION public.replace_draft_document_lines(text, uuid, uuid, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.replace_draft_document_lines(text, uuid, uuid, jsonb) TO authenticated, service_role;

DO $$
BEGIN
    IF to_regprocedure('public.replace_draft_document_lines(text, uuid, uuid, jsonb)') IS NULL THEN
        RAISE EXCEPTION 'migration 560: the function was not created';
    END IF;
    IF has_function_privilege('anon', 'public.replace_draft_document_lines(text, uuid, uuid, jsonb)', 'EXECUTE')
       OR has_function_privilege('public', 'public.replace_draft_document_lines(text, uuid, uuid, jsonb)', 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 560: the function is executable by PUBLIC or anon';
    END IF;
    IF (SELECT prosecdef FROM pg_proc WHERE oid = 'public.replace_draft_document_lines(text, uuid, uuid, jsonb)'::regprocedure) THEN
        RAISE EXCEPTION 'migration 560: the function must be SECURITY INVOKER';
    END IF;
END $$;
