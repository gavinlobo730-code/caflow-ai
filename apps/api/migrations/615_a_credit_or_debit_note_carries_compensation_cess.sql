-- Migration 615: a credit or debit note carries GST compensation cess (POST-A-058).
--
-- ====================================================================================================================================
-- WHAT WAS WRONG
-- ====================================================================================================================================
-- Migration 374 gave the sales invoice and the purchase bill (and their lines) a compensation cess and deliberately did not give the four
-- s.34 note tables one: a sales credit note, a sales debit note, a purchase debit note (the return to a supplier) and a purchase credit
-- note (the supplier's increase). So a note against a cess-bearing invoice or bill adjusted the value and the three GST heads and left
-- the cess where it was: the customer's receivable, the supplier's payable, the cess ledgers, GSTR-1 table 9B and table 12 `csamt`, and
-- GSTR-3B 3.1(a) and 4(A) cess all kept the full charge of a supply the note had reduced or added to. The return named the sales-side
-- case in `cess_gaps` and told the CA to adjust the cess on the portal; the purchase side was not named at all.
--
-- ====================================================================================================================================
-- WHAT THIS DOES
-- ====================================================================================================================================
-- 1. Each of the four note HEADERS gains `cess_paise` and each of the four note LINE tables gains `cess_rate_bps`,
--    `cess_specific_paise_per_unit` and `cess_paise`: the same three line columns, with the same names, types and meaning, that 374 gave
--    the invoice and the bill (two limbs because GST (Compensation to States) Act 2017 s.8(2) levies "on the basis of value, quantity or
--    on such basis"; the amount derived by `domain/gst/compensation_cess.py`, never typed). Every column is NOT NULL DEFAULT 0, so every
--    existing note and line is unchanged and reads as carrying no cess, which is what it carried. Each is non-negative; the rate has no
--    upper bound, for 374's reason (Schedule column (4) carries entries above 100%).
-- 2. `public.numbered_document_atomic__unguarded`, the body every note's FIRST save goes through, inserts its lines with a fixed column
--    list (the header is inserted from the keys it is given and needs nothing). It is re-defined from the text migration 576 left
--    (the last definition, found by number) with the three cess columns added to that list, each 0 when the line does not name it, and
--    nothing else changed: SECURITY DEFINER, the search path, the owner and the privileges are kept by CREATE OR REPLACE, and the
--    wrapper `numbered_document_atomic` (migration 486), which asks who is calling, is not touched. A draft's later saves go through
--    `replace_draft_document_lines` (migration 560), which inserts the columns its caller names and needs no change.
--
-- What the API does with them (the same change): each note's lines take the two limbs, the line's and the note's cess are derived, the
-- total includes the cess, the journal posts it to the cess ledgers 374 seeded (Compensation Cess Payable for a sales note, Compensation
-- Cess Input Credit for a purchase note; never the GST ledgers, Compensation Act s.11(2) proviso), the issue check asks the header's cess
-- against its lines, and the GSTR-1 and GSTR-3B builders, which already read `cess_paise` off every note header and line, now find one.
--
-- NOT DONE HERE: a purchase note carries no s.17(5) blocked-credit split (the bill does, migration 240): a note against a bill whose
-- credit was blocked reverses or adds to the credit ledger for the cess exactly as it already does for the three GST heads. The six
-- note lines on production (read on 2-11-2026 by migration 576) stay as they are, with no cess.
--
-- Rollback: 615_..._rollback.sql restores 576's text of the function and drops the eight new columns (a cess recorded on a note while
-- this stood is lost with them). Idempotent. Nothing here transmits anything to a portal.

BEGIN;

ALTER TABLE public.credit_notes           ADD COLUMN IF NOT EXISTS cess_paise BIGINT NOT NULL DEFAULT 0;
ALTER TABLE public.sales_debit_notes      ADD COLUMN IF NOT EXISTS cess_paise BIGINT NOT NULL DEFAULT 0;
ALTER TABLE public.debit_notes            ADD COLUMN IF NOT EXISTS cess_paise BIGINT NOT NULL DEFAULT 0;
ALTER TABLE public.purchase_credit_notes  ADD COLUMN IF NOT EXISTS cess_paise BIGINT NOT NULL DEFAULT 0;

ALTER TABLE public.credit_note_lines
  ADD COLUMN IF NOT EXISTS cess_rate_bps INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cess_specific_paise_per_unit BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cess_paise BIGINT NOT NULL DEFAULT 0;
ALTER TABLE public.sales_debit_note_lines
  ADD COLUMN IF NOT EXISTS cess_rate_bps INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cess_specific_paise_per_unit BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cess_paise BIGINT NOT NULL DEFAULT 0;
ALTER TABLE public.debit_note_lines
  ADD COLUMN IF NOT EXISTS cess_rate_bps INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cess_specific_paise_per_unit BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cess_paise BIGINT NOT NULL DEFAULT 0;
ALTER TABLE public.purchase_credit_note_lines
  ADD COLUMN IF NOT EXISTS cess_rate_bps INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cess_specific_paise_per_unit BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cess_paise BIGINT NOT NULL DEFAULT 0;

-- Non-negative, named the way 374 named the invoice's and the bill's.
DO $$
DECLARE
  t TEXT;
  c TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['credit_notes', 'sales_debit_notes', 'debit_notes', 'purchase_credit_notes'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = t || '_cess_paise_check') THEN
      EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I CHECK (cess_paise >= 0)', t, t || '_cess_paise_check');
    END IF;
  END LOOP;
  FOREACH t IN ARRAY ARRAY['credit_note_lines', 'sales_debit_note_lines', 'debit_note_lines', 'purchase_credit_note_lines'] LOOP
    FOREACH c IN ARRAY ARRAY['cess_rate_bps', 'cess_specific_paise_per_unit', 'cess_paise'] LOOP
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = t || '_' || c || '_check') THEN
        EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I CHECK (%I >= 0)', t, t || '_' || c || '_check', c);
      END IF;
    END LOOP;
  END LOOP;
END $$;

DO $$
DECLARE
  t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['credit_notes', 'sales_debit_notes', 'debit_notes', 'purchase_credit_notes'] LOOP
    EXECUTE format($c$COMMENT ON COLUMN public.%I.cess_paise IS %L$c$, t,
      'Sum of the note''s lines'' GST compensation cess. Included in total_paise. GSTR-1 csamt on a sales note, GSTR-3B cess on '
      'every note. Posted to the cess ledgers, never the GST ones (Compensation Act s.11(2) proviso). Migration 615.');
  END LOOP;
  FOREACH t IN ARRAY ARRAY['credit_note_lines', 'sales_debit_note_lines', 'debit_note_lines', 'purchase_credit_note_lines'] LOOP
    EXECUTE format($c$COMMENT ON COLUMN public.%I.cess_rate_bps IS %L$c$, t,
      'GST compensation cess, ad valorem limb, in basis points, charged on taxable_amount_paise. See the matching column on '
      'client_sales_invoice_lines (migration 374). Migration 615.');
    EXECUTE format($c$COMMENT ON COLUMN public.%I.cess_specific_paise_per_unit IS %L$c$, t,
      'GST compensation cess, specific limb, in paise per unit of this line''s own UQC. Added to the ad valorem limb. Migration 615.');
    EXECUTE format($c$COMMENT ON COLUMN public.%I.cess_paise IS %L$c$, t,
      'The line''s compensation cess: ad valorem + specific, computed by domain/gst/compensation_cess.py. Derived, never typed. '
      'Migration 615.');
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

  IF jsonb_array_length(p_lines) > 0 THEN
    EXECUTE format(
      'INSERT INTO public.%1$I ('
      '  %2$I, description, hsn_sac, quantity, rate_paise, gst_rate_bps, '
      '  taxable_amount_paise, cgst_paise, sgst_paise, igst_paise, line_total_paise, '
      '  unit, service_catalogue_id, '
      '  cess_rate_bps, cess_specific_paise_per_unit, cess_paise'
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
      '  COALESCE((l->>''cess_paise'')::bigint, 0) '
      'FROM jsonb_array_elements($2) AS l',
      p_lines_table, p_lines_fk_column
    ) USING v_row.id, p_lines;
  END IF;

  RETURN to_jsonb(v_row);
END
$function$;

COMMIT;
