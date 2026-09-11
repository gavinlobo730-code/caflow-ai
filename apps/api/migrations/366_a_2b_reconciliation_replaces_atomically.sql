-- Migration 366: replacing a period's GSTR-2B reconciliation is ONE transaction.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE PROBLEM
-- ═══════════════════════════════════════════════════════════════════════════
-- services/gst_2b_reconciliation_service.reconcile_2b replaces a period by
-- DELETE-then-INSERT over PostgREST, which is four separate statements and
-- therefore four separate transactions:
--
--     DELETE gstr2a_records        WHERE (firm, client, period)   -- commits
--     INSERT gstr2a_records        in pages of 500                -- may fail
--     DELETE gstr2b_reconciliations WHERE (firm, client, period)  -- commits
--     INSERT gstr2b_reconciliations one header row                -- may fail
--
-- Anything that interrupts the middle leaves the period with its previous
-- reconciliation DELETED and nothing in its place. WHICH WAY THAT GOES WRONG
-- DEPENDS ON WHERE IT FAILS, and both directions are reachable:
--
--   * Fails during the DOCUMENT insert (statement 2). The documents are gone
--     and the PREVIOUS HEADER SURVIVES, because it is deleted later. So
--     was_reconciled() is TRUE over zero documents, and Rule 36(4) caps the
--     month's ITC AT NIL. The CA is told the client may claim no input credit
--     at all. Measured, not reasoned: a period holding (1 document, 1 header)
--     came back (0 documents, 1 header) after one failed insert.
--
--   * Fails during the HEADER insert (statement 4). The new documents are in
--     and the header is gone, so the period reads back as NEVER RECONCILED —
--     have_2b false, no cap, and the return claims credit §16(2)(aa) may
--     withhold.
--
-- A re-upload fixes either, and the screen shows the state — but nothing tells
-- the CA to look, and the first one is a wrong figure on a filed return.
--
-- The original defect here was sharper and is already fixed: migration 341 put
-- document_type into uq_gstr2a_records_document, so a credit note and a debit
-- note sharing a number no longer collide. That removed the RELIABLE trigger.
-- It did not make the sequence atomic, and a dropped connection to Mumbai from
-- Singapore is not a hypothetical — every statement here is a cross-region
-- round trip.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE SHAPE, AND WHY IT IS THIS ONE
-- ═══════════════════════════════════════════════════════════════════════════
-- public.replace_bank_transaction_splits (migration 256) is the precedent: a
-- SECURITY DEFINER plpgsql function taking the new rows as JSONB, deleting and
-- re-inserting inside its own transaction. A function invoked as a single
-- statement either commits entirely or leaves the table exactly as it was.
--
-- Documents and header go in ONE call, because they are one fact. Splitting
-- them would reintroduce the window this closes.
--
-- THE HEADER IS WRITTEN EVEN WHEN THERE ARE NO DOCUMENTS. That is the whole
-- point of migration 341: a 2B on file in which nobody filed anything is a
-- reconciliation that happened and must cap ITC at nil, and it is not the same
-- fact as no 2B at all.
--
-- FIRM SCOPE IS ENFORCED IN THE FUNCTION, not assumed from the caller. It is
-- SECURITY DEFINER, so it runs with the definer's rights and RLS does not
-- protect it — every statement filters on p_firm_id, and the rows built from
-- JSONB have their firm_id and client_id taken from the PARAMETERS rather than
-- from the payload, so a payload naming another firm cannot write there.
--
-- MOCK MODE DOES NOT HAVE THIS. There is no DATABASE_URL in the mock suite and
-- the in-memory source has no SQL functions, so the service keeps its
-- statement-by-statement path for that case and calls the RPC when `.rpc` is
-- available — the same shape as cash_flow_report, schedule_iii_ageing and
-- stock_position_as_at. The Python path is NOT a second implementation of a
-- rule: it writes the same rows in the same order, and only the atomicity
-- differs, which is exactly what mock mode cannot have.

CREATE OR REPLACE FUNCTION public.replace_gstr2b_reconciliation(
    p_firm_id   UUID,
    p_client_id UUID,
    p_period    TEXT,
    p_documents JSONB,   -- [] is legitimate: a 2B in which nobody filed anything
    p_header    JSONB    -- exactly one object
)
RETURNS TABLE (document_count INTEGER)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
DECLARE
    v_docs INTEGER := 0;
BEGIN
    IF p_firm_id IS NULL OR p_client_id IS NULL
       OR p_period IS NULL OR btrim(p_period) = '' THEN
        RAISE EXCEPTION 'firm, client and period are all required.'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_header IS NULL OR jsonb_typeof(p_header) <> 'object' THEN
        RAISE EXCEPTION 'A reconciliation must carry exactly one header row.'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_documents IS NULL OR jsonb_typeof(p_documents) <> 'array' THEN
        RAISE EXCEPTION 'Documents must be a JSON array (possibly empty).'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    DELETE FROM public.gstr2a_records
     WHERE firm_id = p_firm_id AND client_id = p_client_id
       AND return_period = p_period;

    DELETE FROM public.gstr2b_reconciliations
     WHERE firm_id = p_firm_id AND client_id = p_client_id
       AND return_period = p_period;

    -- firm_id, client_id and return_period come from the PARAMETERS, never from
    -- the payload: this function is SECURITY DEFINER, so a document object
    -- naming another firm would otherwise write across the tenant boundary.
    INSERT INTO public.gstr2a_records (
        firm_id, client_id, return_period, section, document_type,
        supplier_gstin, supplier_name, supplier_trade_name,
        invoice_number, invoice_date,
        taxable_value_paise, igst_paise, cgst_paise, sgst_paise, cess_paise,
        invoice_value_paise,
        itc_available, itc_unavailable_reason_code, itc_unavailable_reason,
        supplier_filed_on, is_amendment, amends_document_number,
        source, purchase_bill_id, match_status, match_difference_paise,
        reconciled_at, updated_at)
    SELECT
        p_firm_id, p_client_id, p_period,
        -- section and document_type are NOT NULL with defaults of their own.
        COALESCE(d->>'section', 'b2b'), COALESCE(d->>'document_type', 'invoice'),
        d->>'supplier_gstin', d->>'supplier_name', d->>'supplier_trade_name',
        d->>'invoice_number', NULLIF(d->>'invoice_date', '')::DATE,
        COALESCE((d->>'taxable_value_paise')::BIGINT, 0),
        COALESCE((d->>'igst_paise')::BIGINT, 0),
        COALESCE((d->>'cgst_paise')::BIGINT, 0),
        COALESCE((d->>'sgst_paise')::BIGINT, 0),
        COALESCE((d->>'cess_paise')::BIGINT, 0),
        COALESCE((d->>'invoice_value_paise')::BIGINT, 0),
        -- itc_available is TEXT, not BOOLEAN. It carries the portal's own
        -- `itcavl` flag — 'Y', 'N', or '' where 2B did not say — and
        -- domain/gst/gstr2b.py types it `str` for the same reason: "no answer"
        -- is a third state, and a boolean cannot hold it. Casting it to
        -- BOOLEAN here would have turned every '' into an error and every
        -- 'N' into a failed cast.
        COALESCE(d->>'itc_available', ''),
        -- These three are NOT NULL DEFAULT '' (migration 340). A key absent
        -- from the payload yields SQL NULL from ->>, which the column refuses,
        -- so each coalesces to the column's own default rather than relying on
        -- the caller always sending it.
        COALESCE(d->>'itc_unavailable_reason_code', ''),
        COALESCE(d->>'itc_unavailable_reason', ''),
        NULLIF(d->>'supplier_filed_on', '')::DATE,
        COALESCE((d->>'is_amendment')::BOOLEAN, FALSE),
        COALESCE(d->>'amends_document_number', ''),
        COALESCE(d->>'source', 'upload'),
        NULLIF(d->>'purchase_bill_id', '')::UUID,
        COALESCE(d->>'match_status', 'unmatched'),
        COALESCE((d->>'match_difference_paise')::BIGINT, 0),
        COALESCE(NULLIF(d->>'reconciled_at', '')::TIMESTAMPTZ, now()),
        COALESCE(NULLIF(d->>'updated_at', '')::TIMESTAMPTZ, now())
      FROM jsonb_array_elements(p_documents) d;

    GET DIAGNOSTICS v_docs = ROW_COUNT;

    INSERT INTO public.gstr2b_reconciliations (
        firm_id, client_id, return_period, gstin, file_return_period,
        generated_on, sections_seen, document_count, book_bill_count,
        parsed_ok, problems, reconciled_at, updated_at)
    VALUES (
        p_firm_id, p_client_id, p_period,
        p_header->>'gstin', p_header->>'file_return_period',
        p_header->>'generated_on',
        COALESCE(ARRAY(SELECT jsonb_array_elements_text(
            COALESCE(p_header->'sections_seen', '[]'::JSONB))), ARRAY[]::TEXT[]),
        COALESCE((p_header->>'document_count')::INTEGER, v_docs),
        COALESCE((p_header->>'book_bill_count')::INTEGER, 0),
        COALESCE((p_header->>'parsed_ok')::BOOLEAN, TRUE),
        COALESCE(ARRAY(SELECT jsonb_array_elements_text(
            COALESCE(p_header->'problems', '[]'::JSONB))), ARRAY[]::TEXT[]),
        now(), now());

    document_count := v_docs;
    RETURN NEXT;
END;
$$;

COMMENT ON FUNCTION public.replace_gstr2b_reconciliation(UUID, UUID, TEXT, JSONB, JSONB) IS
  'Replaces one period''s GSTR-2B reconciliation — documents and header — in a '
  'single transaction. The delete-then-insert it replaces could leave a period '
  'with its previous reconciliation destroyed and nothing written, which reads '
  'back as never reconciled and therefore does NOT cap ITC under Rule 36(4).';

REVOKE ALL ON FUNCTION public.replace_gstr2b_reconciliation(UUID, UUID, TEXT, JSONB, JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.replace_gstr2b_reconciliation(UUID, UUID, TEXT, JSONB, JSONB)
  TO authenticated, service_role;
