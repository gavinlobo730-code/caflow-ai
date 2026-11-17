-- Rollback of migration 685: restore migration 615's text of numbered_document_atomic__unguarded (the lines INSERT without the two
-- s.17(5) columns) and drop the ten columns 685 added to the two purchase-note tables and their lines (with their checks). A blocked mark
-- recorded on a note while 685 stood is lost with the columns; the API that writes them must be rolled back first.
BEGIN;

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

DO $$
DECLARE
  t TEXT;
  c TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['debit_notes', 'purchase_credit_notes'] LOOP
    FOREACH c IN ARRAY ARRAY['ineligible_itc_cgst_paise', 'ineligible_itc_sgst_paise', 'ineligible_itc_igst_paise', 'ineligible_itc_cess_paise'] LOOP
      EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT IF EXISTS %I', t, t || '_' || c || '_check');
      EXECUTE format('ALTER TABLE public.%I DROP COLUMN IF EXISTS %I', t, c);
    END LOOP;
  END LOOP;
  FOREACH t IN ARRAY ARRAY['debit_note_lines', 'purchase_credit_note_lines'] LOOP
    EXECUTE format('ALTER TABLE public.%I DROP COLUMN IF EXISTS itc_eligible', t);
    EXECUTE format('ALTER TABLE public.%I DROP COLUMN IF EXISTS blocked_credit_reason', t);
  END LOOP;
END $$;

COMMIT;
