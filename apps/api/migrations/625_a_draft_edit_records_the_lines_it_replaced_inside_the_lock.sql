-- Migration 625: a draft's edit records the lines it replaced from inside the transaction that holds the header's lock (POST-A-429).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- `services/draft_document_lines.replace_draft_lines` read a draft's lines, then called `public.replace_draft_document_lines`
-- (migration 560), which takes the header FOR UPDATE and replaces the lines, and then wrote the edit record with the lines it had
-- read. Between the read and the lock another save could replace the lines, so two members saving one draft at the same moment could
-- both record the first one's lines as the ones they replaced, and the lines the first save wrote reached the log only as a new value.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The function's body is migration 560's, the migration that last defined it, unchanged but for two things: the DELETE returns the
-- rows it removes, and the function answers `{"count": n, "replaced": [...]}` instead of the count alone. A return type cannot be
-- changed by CREATE OR REPLACE, so the function is dropped and created again in this one transaction, with 560's grants restated
-- (EXECUTE for `authenticated` and `service_role`, none for PUBLIC or anon) and still SECURITY INVOKER. An API that predates this
-- migration calls the function and does not read its answer, so it is not affected; the API that reads the answer still makes its
-- own read first and uses it only when the answer is the old count, for the minutes between the API reaching production and this
-- migration doing so.
--
-- No row of any table changes. The rollback restores 560's function exactly.

DROP FUNCTION IF EXISTS public.replace_draft_document_lines(text, uuid, uuid, jsonb);

CREATE FUNCTION public.replace_draft_document_lines(
    p_document     text,
    p_document_id  uuid,
    p_firm_id      uuid,
    p_lines        jsonb
) RETURNS jsonb
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
    v_replaced jsonb;
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

    -- The lines this call removes, read by the DELETE itself under the header's lock (POST-A-429): what the edit record says was replaced
    -- is what this transaction replaced, and not what a read made before the lock found.
    EXECUTE format(
        'WITH gone AS (DELETE FROM public.%I WHERE %I = $1 RETURNING *) SELECT coalesce(jsonb_agg(to_jsonb(gone)), ''[]''::jsonb) FROM gone',
        v_lines, v_fk
    ) INTO v_replaced USING p_document_id;

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

    RETURN jsonb_build_object('count', jsonb_array_length(p_lines), 'replaced', v_replaced);
END
$$;

REVOKE ALL ON FUNCTION public.replace_draft_document_lines(text, uuid, uuid, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.replace_draft_document_lines(text, uuid, uuid, jsonb) TO authenticated, service_role;

DO $$
BEGIN
    IF to_regprocedure('public.replace_draft_document_lines(text, uuid, uuid, jsonb)') IS NULL THEN
        RAISE EXCEPTION 'migration 625: the function was not created';
    END IF;
    IF (SELECT prorettype FROM pg_proc WHERE oid = 'public.replace_draft_document_lines(text, uuid, uuid, jsonb)'::regprocedure)
       <> 'jsonb'::regtype THEN
        RAISE EXCEPTION 'migration 625: the function must answer jsonb';
    END IF;
    IF has_function_privilege('anon', 'public.replace_draft_document_lines(text, uuid, uuid, jsonb)', 'EXECUTE')
       OR has_function_privilege('public', 'public.replace_draft_document_lines(text, uuid, uuid, jsonb)', 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 625: the function is executable by PUBLIC or anon';
    END IF;
    IF NOT has_function_privilege('authenticated', 'public.replace_draft_document_lines(text, uuid, uuid, jsonb)', 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 625: authenticated lost EXECUTE';
    END IF;
    IF (SELECT prosecdef FROM pg_proc WHERE oid = 'public.replace_draft_document_lines(text, uuid, uuid, jsonb)'::regprocedure) THEN
        RAISE EXCEPTION 'migration 625: the function must be SECURITY INVOKER';
    END IF;
END $$;
