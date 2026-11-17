-- Migration 685: a purchase debit note or purchase credit note line says whether its input credit is blocked (POST-A-459).
--
-- ====================================================================================================================================
-- WHAT WAS WRONG
-- ====================================================================================================================================
-- A purchase bill line carries `itc_eligible` and `blocked_credit_reason` (migration 240), the bill's header carries the blocked tax per
-- head (`ineligible_itc_{cgst,sgst,igst,cess}_paise`), and the bill's journal debits GST Input and the cess credit with the CREDITABLE
-- tax only, putting the CGST Act s.17(5) blocked part on the cost. The two purchase-side s.34 notes carried no such split: a debit note
-- (a return to the supplier) credited GST Input and the cess credit with its WHOLE tax, and a purchase credit note (the supplier's
-- increase) debited them with its whole tax. So a note against a club membership, a motor car or food the client's books had blocked
-- moved the credit ledgers by tax that was never credit, and the GSTR-3B built from the books netted it out of 4(A) without touching
-- 4(B)(1), understating the net credit in 4(C) by the blocked tax on a return and overstating it on an increase. Migration 615 named the
-- gap for the cess and left it.
--
-- ====================================================================================================================================
-- WHAT THIS DOES
-- ====================================================================================================================================
-- 1. `debit_note_lines` and `purchase_credit_note_lines` gain `itc_eligible BOOLEAN NOT NULL DEFAULT true` and `blocked_credit_reason
--    TEXT`, the two columns, names, types and meaning 240 gave `purchase_bill_lines`. CA-set, never inferred. Every existing line reads
--    as eligible, which is how it was posted.
-- 2. `debit_notes` and `purchase_credit_notes` gain `ineligible_itc_{cgst,sgst,igst,cess}_paise BIGINT NOT NULL DEFAULT 0`, each
--    non-negative: the sum of the blocked lines' heads, the bill header's four columns, which the issue check holds to the lines.
-- 3. `public.numbered_document_atomic__unguarded`, the body every note's FIRST save goes through, inserts its lines with a fixed column
--    list. It is re-defined from the text migration 615 left (the last definition, found by number) with the two line columns added for
--    the two purchase-note line tables only (the sales notes' line tables do not have them); for those two, a line that names neither
--    stores `itc_eligible` true and no reason, which is what the column default says. Nothing else changes: SECURITY DEFINER, the search
--    path, the owner and the privileges are kept by CREATE OR REPLACE, and the wrapper `numbered_document_atomic` (migration 486), which
--    asks who is calling, is not touched. A draft's later saves go through `replace_draft_document_lines` (migration 625), which inserts
--    the columns its caller names and needs no change.
--
-- What the API does with them (the same change): a line of either note may be marked not eligible with a reason, the header's four
-- blocked heads are the blocked lines' sums, the journal moves the credit ledgers by the creditable tax only and the blocked tax goes to
-- the cost line, the issue check asks the header's blocked heads against the lines, and GSTR-3B from the books carries the blocked part
-- in 4(B)(1) with the note's sign, as it carries a bill's. The API sends the new keys only when a line IS blocked, so a note with no
-- blocked line is saved exactly as before during the minutes the API runs ahead of this migration.
--
-- Rollback: 685_..._rollback.sql restores 615's text of the function and drops the columns (a blocked mark recorded while this stood is
-- lost with them; the API that writes them must be rolled back first). Idempotent. Nothing here transmits anything to a portal.

BEGIN;

ALTER TABLE public.debit_note_lines
  ADD COLUMN IF NOT EXISTS itc_eligible BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS blocked_credit_reason TEXT;
ALTER TABLE public.purchase_credit_note_lines
  ADD COLUMN IF NOT EXISTS itc_eligible BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS blocked_credit_reason TEXT;

ALTER TABLE public.debit_notes
  ADD COLUMN IF NOT EXISTS ineligible_itc_cgst_paise BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS ineligible_itc_sgst_paise BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS ineligible_itc_igst_paise BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS ineligible_itc_cess_paise BIGINT NOT NULL DEFAULT 0;
ALTER TABLE public.purchase_credit_notes
  ADD COLUMN IF NOT EXISTS ineligible_itc_cgst_paise BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS ineligible_itc_sgst_paise BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS ineligible_itc_igst_paise BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS ineligible_itc_cess_paise BIGINT NOT NULL DEFAULT 0;

DO $$
DECLARE
  t TEXT;
  c TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['debit_notes', 'purchase_credit_notes'] LOOP
    FOREACH c IN ARRAY ARRAY['ineligible_itc_cgst_paise', 'ineligible_itc_sgst_paise', 'ineligible_itc_igst_paise', 'ineligible_itc_cess_paise'] LOOP
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = t || '_' || c || '_check') THEN
        EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I CHECK (%I >= 0)', t, t || '_' || c || '_check', c);
      END IF;
      EXECUTE format($cm$COMMENT ON COLUMN public.%I.%I IS %L$cm$, t, c,
        'CGST Act s.17(5): the part of this note''s tax on lines marked not eligible for input credit (the lines'' sum, held by the '
        'issue check). Posted to the cost, never to the credit ledgers; GSTR-3B 4(B)(1) with the note''s sign. As on purchase_bills '
        '(migration 240). Migration 685.');
    END LOOP;
  END LOOP;
  FOREACH t IN ARRAY ARRAY['debit_note_lines', 'purchase_credit_note_lines'] LOOP
    EXECUTE format($cm$COMMENT ON COLUMN public.%I.itc_eligible IS %L$cm$, t,
      'CGST Act s.17(5): false when the credit on this line is blocked. CA-set only, never inferred, as on purchase_bill_lines '
      '(migration 240). Migration 685.');
    EXECUTE format($cm$COMMENT ON COLUMN public.%I.blocked_credit_reason IS %L$cm$, t,
      'The reason the CA gave when itc_eligible is false, in the words purchase_bill_lines.blocked_credit_reason takes. Migration 685.');
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION public.numbered_document_atomic__unguarded(p_header_table text, p_header jsonb, p_lines_table text, p_lines jsonb, p_lines_fk_column text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_catalog'
AS $function$
DECLARE
  v_keys text;
  v_row  RECORD;
  v_itc_cols text := '';
  v_itc_vals text := '';
BEGIN
  SELECT string_agg(quote_ident(k), ', ') INTO v_keys FROM jsonb_object_keys(p_header) AS k;
  IF v_keys IS NULL THEN
    RAISE EXCEPTION 'numbered_document_atomic: empty header payload';
  END IF;

  EXECUTE format(
    'INSERT INTO public.%1$I (%2$s) '
    'SELECT %2$s FROM jsonb_populate_record(NULL::public.%1$I, $1) '
    'RETURNING *',
    p_header_table, v_keys
  ) INTO v_row USING p_header;

  -- Migration 685: the two purchase-note line tables say whether a line's credit is blocked (CGST Act s.17(5)).
  IF p_lines_table IN ('debit_note_lines', 'purchase_credit_note_lines') THEN
    v_itc_cols := ', itc_eligible, blocked_credit_reason';
    v_itc_vals := ', COALESCE((l->>''itc_eligible'')::boolean, true), NULLIF(l->>''blocked_credit_reason'', '''')';
  END IF;

  IF jsonb_array_length(p_lines) > 0 THEN
    EXECUTE format(
      'INSERT INTO public.%1$I ('
      '  %2$I, description, hsn_sac, quantity, rate_paise, gst_rate_bps, '
      '  taxable_amount_paise, cgst_paise, sgst_paise, igst_paise, line_total_paise, '
      '  unit, service_catalogue_id, '
      '  cess_rate_bps, cess_specific_paise_per_unit, cess_paise%3$s'
      ') SELECT '
      '  $1, l->>''description'', l->>''hsn_sac'', '
      '  COALESCE((l->>''quantity'')::numeric, 1), '
      '  COALESCE((l->>''rate_paise'')::bigint, 0), '
      '  COALESCE((l->>''gst_rate_bps'')::int, 0), '
      '  COALESCE((l->>''taxable_amount_paise'')::bigint, 0), '
      '  COALESCE((l->>''cgst_paise'')::bigint, 0), '
      '  COALESCE((l->>''sgst_paise'')::bigint, 0), '
      '  COALESCE((l->>''igst_paise'')::bigint, 0), '
      '  COALESCE((l->>''line_total_paise'')::bigint, 0), '
      '  NULLIF(l->>''unit'', ''''), '
      '  NULLIF(l->>''service_catalogue_id'', '''')::uuid, '
      '  COALESCE((l->>''cess_rate_bps'')::int, 0), '
      '  COALESCE((l->>''cess_specific_paise_per_unit'')::bigint, 0), '
      '  COALESCE((l->>''cess_paise'')::bigint, 0)%4$s '
      'FROM jsonb_array_elements($2) AS l',
      p_lines_table, p_lines_fk_column, v_itc_cols, v_itc_vals
    ) USING v_row.id, p_lines;
  END IF;

  RETURN to_jsonb(v_row);
END
$function$;

COMMIT;
