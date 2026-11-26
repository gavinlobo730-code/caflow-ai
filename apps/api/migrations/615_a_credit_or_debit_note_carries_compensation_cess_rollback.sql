-- Rollback of migration 615: restore migration 576's text of numbered_document_atomic__unguarded (the lines INSERT without the three cess
-- columns) and drop the eight cess columns 615 added to the four s.34 note tables and their lines (with their checks). A cess recorded on
-- a note while 615 stood is lost with the columns; the API that writes them must be rolled back first.
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
      '  unit, service_catalogue_id'
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
      '  NULLIF(l->>''service_catalogue_id'', '''')::uuid '
      'FROM jsonb_array_elements($2) AS l',
      p_lines_table, p_lines_fk_column
    ) USING v_row.id, p_lines;
  END IF;

  RETURN to_jsonb(v_row);
END
$function$;

ALTER TABLE public.credit_notes           DROP COLUMN IF EXISTS cess_paise;
ALTER TABLE public.sales_debit_notes      DROP COLUMN IF EXISTS cess_paise;
ALTER TABLE public.debit_notes            DROP COLUMN IF EXISTS cess_paise;
ALTER TABLE public.purchase_credit_notes  DROP COLUMN IF EXISTS cess_paise;

ALTER TABLE public.credit_note_lines
  DROP COLUMN IF EXISTS cess_rate_bps, DROP COLUMN IF EXISTS cess_specific_paise_per_unit, DROP COLUMN IF EXISTS cess_paise;
ALTER TABLE public.sales_debit_note_lines
  DROP COLUMN IF EXISTS cess_rate_bps, DROP COLUMN IF EXISTS cess_specific_paise_per_unit, DROP COLUMN IF EXISTS cess_paise;
ALTER TABLE public.debit_note_lines
  DROP COLUMN IF EXISTS cess_rate_bps, DROP COLUMN IF EXISTS cess_specific_paise_per_unit, DROP COLUMN IF EXISTS cess_paise;
ALTER TABLE public.purchase_credit_note_lines
  DROP COLUMN IF EXISTS cess_rate_bps, DROP COLUMN IF EXISTS cess_specific_paise_per_unit, DROP COLUMN IF EXISTS cess_paise;

COMMIT;
