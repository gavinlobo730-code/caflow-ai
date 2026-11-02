-- Migration 576: a credit or debit note line recorded through the numbering function keeps its unit and its catalogue item
-- (POST-A-370; the same defect as the receipt's, migrations 574 and 575).
--
-- ====================================================================================================================================
-- WHAT WAS WRONG
-- ====================================================================================================================================
-- The four note kinds (sales credit note, sales debit note, purchase credit note, purchase debit note) are recorded through
-- `numbered_document_atomic`, whose body is `numbered_document_atomic__unguarded` (migration 167, renamed behind a caller check by 486).
-- The HEADER is inserted from the keys the caller sends (`jsonb_populate_record`), so a new header column is stored. The LINES are
-- inserted with a FIXED column list written before the note routers began sending `unit` (every router sends `ln.get("unit") or "NOS"`)
-- and `service_catalogue_id`, and all four line tables carry both columns, so every note line's unit and catalogue item were dropped
-- without an error. Read-only on production on 2-11-2026: 6 note lines (3 credit, 2 debit, 1 purchase credit), none with a unit and none
-- with a catalogue item.
-- A note line without a unit reaches the GSTR-1 HSN summary (Table 12) as the fallback code OTH (`domain/gst/gstr1_builder`: the unit
-- is normalised to a UQC and falls back to OTH). Table 12 is keyed by HSN and carries the unit of the first line seen, so a note netted
-- against an invoice line of the same HSN keeps the invoice's unit and the quantity nets correctly, but the return then carries a false
-- "unit not recorded" gap; a note that is the only line for its HSN in the period is reported as OTH. And the catalogue link is gone: it is
-- what the catalogue's delete guard (an item used by an issued document cannot be deleted) and the stock path of an issued credit or
-- debit note read.
--
-- ====================================================================================================================================
-- WHAT THIS DOES
-- ====================================================================================================================================
-- Re-defines `public.numbered_document_atomic__unguarded` with the body production holds (checked: md5 ebae3374c33ddfc6e67ccceeadbc1948,
-- 1,376 characters, equal to the text the migrations build; SECURITY DEFINER, search path public, pg_catalog; privileges owner and
-- service_role only) unchanged except that the lines INSERT also stores `unit` and `service_catalogue_id` (each NULL when absent or blank).
-- CREATE OR REPLACE keeps the owner and the privileges; the wrapper `numbered_document_atomic` (migration 486) is not touched.
-- Existing note lines are NOT changed by this file: their unit and catalogue item were never stored, and the originating line cannot be
-- told from a note line alone, so the six production lines stay as they are (an issued note cannot be edited, so a note's unit reads as
-- the fallback OTH in Table 12 where it is the only line for its HSN).
--
-- WHAT THIS NEWLY MAKES LIVE, SAID PLAINLY: issuing a sales credit note or a purchase debit note whose line names a GOODS item restocks
-- or destocks that item and posts the Inventory journal (`domain/inventory_service.apply_credit_note_to_inventory` and
-- `apply_debit_note_to_inventory`, which return at once when no line carries a catalogue item). That is what migration 189 added the
-- column for, the editor tells the person so, and the path was already reachable for a note whose draft had been edited (the edit path
-- stores both columns); it was dormant for a note created and issued unedited. A note that corrects a price or a discount rather than
-- returning goods restocks too when it names a goods item (the note models require the pick): that is the stock path's own rule, not this
-- file's, and it is its own item (POST-A-371).
-- ALSO NOT DONE: the function stores a catalogue id with no database check that the item belongs to the note's client (the API refuses a
-- foreign one first, and the stock path reads under the firm and the client), and two of the four line tables (sales_debit_note_lines
-- and purchase_credit_note_lines, migration 210) carry no foreign key on the column, so an item deleted while a draft names it leaves the
-- id on those two (the other two set it to NULL).
-- Rollback: 576_..._rollback.sql restores the previous text. Notes recorded while this stood keep what they stored.
--
-- Nothing here transmits anything to a portal.

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

COMMIT;
