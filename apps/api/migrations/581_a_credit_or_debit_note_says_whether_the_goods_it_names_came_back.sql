-- Migration 581: a credit note or a purchase debit note says whether the goods it names physically came back (POST-A-371).
--
-- ====================================================================================================================================
-- WHAT WAS WRONG
-- ====================================================================================================================================
-- `domain/inventory_service.apply_credit_note_to_inventory` (a sales credit note, on issue) and `apply_debit_note_to_inventory` (a
-- purchase debit note) treat EVERY goods line that names a catalogue item as goods physically returned: a credit note restocks at the
-- original sale's unit cost and posts Dr Inventory / Cr Cost of goods sold, a debit note destocks and posts Dr Expense / Cr Inventory.
-- The note models make the catalogue pick mandatory on every line, and the editor's own placeholder offers "Goods returned / rate
-- correction / excess billed", so a rate-correction or excess-billed note on a goods item had no way to avoid moving stock and cost: phantom
-- units in Inventory and a wrong cost of goods sold, with the GST side (a section 34 note adjusts the tax either way) correct. The reason
-- is free text, so nothing the software could read said which kind of note it was.
--
-- Read-only on production on 4-11-2026: 2 credit notes and 2 debit notes in all, none naming any catalogue item, so no existing document
-- is affected by what follows.
--
-- ====================================================================================================================================
-- WHAT THIS DOES
-- ====================================================================================================================================
--   * `credit_notes.goods_returned` and `debit_notes.goods_returned`: BOOLEAN, nullable, no default, no backfill. TRUE = the goods came
--     back (or went back to the supplier) and stock moves; FALSE = a price or discount correction, stock does not move; NULL = not
--     stated, which is every note written before this file. The API REFUSES to issue a note that names goods and has not stated it, so a
--     note's stock effect is never assumed; an already-issued note with NULL moved stock under the old rule and is still counted as
--     owing it (below), because that is what was done.
--   * `public.documents_with_unrecorded_stock` (migration 579) is replaced with the same body and one more condition on the two note kinds,
--     `goods_returned IS NOT FALSE`: a note that says no goods came back owes no stock, so the client's Inventory tab must not list it
--     as a document whose stock was not recorded (and offer to move goods that never moved). NULL is still listed, as before.
--     Privileges are the ones 579 gave and the file asserts them again: executable by the service role and by no signed-in or
--     anonymous role.
--
-- It writes no row and moves no figure. Nothing here transmits anything to a portal.
-- Reversible: 581_..._rollback.sql puts 579's function back and drops the two columns.

BEGIN;

ALTER TABLE public.credit_notes ADD COLUMN IF NOT EXISTS goods_returned BOOLEAN;
ALTER TABLE public.debit_notes ADD COLUMN IF NOT EXISTS goods_returned BOOLEAN;

COMMENT ON COLUMN public.credit_notes.goods_returned IS
    'TRUE: the goods on this credit note physically came back and stock moves when it is issued. FALSE: a price or discount correction; stock does not move. NULL: not stated (a note written before migration 581); issuing a note that names goods requires it. POST-A-371.';
COMMENT ON COLUMN public.debit_notes.goods_returned IS
    'TRUE: the goods on this debit note physically went back to the supplier and stock moves when it is issued. FALSE: a price or rate correction; stock does not move. NULL: not stated (a note written before migration 581); issuing a note that names goods requires it. POST-A-371.';

CREATE OR REPLACE FUNCTION public.documents_with_unrecorded_stock(p_firm uuid, p_client uuid)
RETURNS jsonb
LANGUAGE sql
STABLE
SET search_path = public, pg_catalog
AS $fn$
WITH docs AS (
    SELECT 'sales_invoice'::text AS kind, d.id, d.invoice_no::text AS reference, d.invoice_date AS document_date
      FROM public.client_sales_invoices d
     WHERE d.firm_id = p_firm AND d.client_id = p_client AND d.deleted_at IS NULL
       AND d.status NOT IN ('draft', 'cancelled') AND COALESCE(d.is_opening, false) = false
    UNION ALL
    SELECT 'purchase_bill', d.id, COALESCE(d.bill_no, d.our_reference)::text, d.bill_date
      FROM public.purchase_bills d
     WHERE d.firm_id = p_firm AND d.client_id = p_client AND d.deleted_at IS NULL
       AND d.status NOT IN ('draft', 'cancelled') AND COALESCE(d.is_opening, false) = false
    UNION ALL
    SELECT 'credit_note', d.id, d.credit_note_no::text, d.credit_note_date
      FROM public.credit_notes d
     WHERE d.firm_id = p_firm AND d.client_id = p_client AND d.deleted_at IS NULL
       AND d.status NOT IN ('draft', 'cancelled')
       AND d.goods_returned IS NOT FALSE
    UNION ALL
    SELECT 'debit_note', d.id, d.debit_note_no::text, d.debit_note_date
      FROM public.debit_notes d
     WHERE d.firm_id = p_firm AND d.client_id = p_client AND d.deleted_at IS NULL
       AND d.status NOT IN ('draft', 'cancelled')
       AND d.goods_returned IS NOT FALSE
),
goods AS (
    SELECT c.id FROM public.service_catalogue c
     WHERE c.firm_id = p_firm AND c.client_id = p_client AND c.kind = 'good'
),
owed AS (
    SELECT 'sales_invoice'::text AS kind, l.sales_invoice_id AS doc_id, COUNT(*)::int AS owed_lines
      FROM public.client_sales_invoice_lines l
      JOIN docs d ON d.kind = 'sales_invoice' AND d.id = l.sales_invoice_id
      JOIN goods g ON g.id = l.service_catalogue_id
     WHERE COALESCE(l.quantity, 0) > 0
     GROUP BY l.sales_invoice_id
    UNION ALL
    SELECT 'purchase_bill', l.bill_id, COUNT(*)::int
      FROM public.purchase_bill_lines l
      JOIN docs d ON d.kind = 'purchase_bill' AND d.id = l.bill_id
      JOIN goods g ON g.id = l.service_catalogue_id
     WHERE COALESCE(l.quantity, 0) > 0 AND COALESCE(l.taxable_amount_paise, 0) > 0
     GROUP BY l.bill_id
    UNION ALL
    SELECT 'credit_note', l.credit_note_id, COUNT(*)::int
      FROM public.credit_note_lines l
      JOIN docs d ON d.kind = 'credit_note' AND d.id = l.credit_note_id
      JOIN goods g ON g.id = l.service_catalogue_id
     WHERE COALESCE(l.quantity, 0) > 0
     GROUP BY l.credit_note_id
    UNION ALL
    SELECT 'debit_note', l.debit_note_id, COUNT(*)::int
      FROM public.debit_note_lines l
      JOIN docs d ON d.kind = 'debit_note' AND d.id = l.debit_note_id
      JOIN goods g ON g.id = l.service_catalogue_id
     WHERE COALESCE(l.quantity, 0) > 0
     GROUP BY l.debit_note_id
),
moved AS (
    SELECT s.source_type AS kind, s.source_id AS doc_id,
           COUNT(*)::int AS moved_lines,
           (COUNT(*) FILTER (WHERE s.journal_entry_id IS NULL AND s.value_delta_paise <> 0))::int AS unjournalled_rows
      FROM public.inventory_stock_ledger s
     WHERE s.firm_id = p_firm AND s.client_id = p_client
       AND (s.source_type, s.movement_type) IN (('sales_invoice', 'sale'), ('purchase_bill', 'purchase'),
                                                 ('credit_note', 'sale_return'), ('debit_note', 'purchase_return'))
     GROUP BY s.source_type, s.source_id
),
found AS (
    SELECT d.kind, d.id AS document_id, d.reference, d.document_date,
           o.owed_lines, COALESCE(m.moved_lines, 0) AS moved_lines, COALESCE(m.unjournalled_rows, 0) AS unjournalled_rows
      FROM docs d
      JOIN owed o ON o.kind = d.kind AND o.doc_id = d.id
      LEFT JOIN moved m ON m.kind = d.kind AND m.doc_id = d.id
     WHERE COALESCE(m.moved_lines, 0) < o.owed_lines OR COALESCE(m.unjournalled_rows, 0) > 0
)
SELECT jsonb_build_object(
    'total', (SELECT COUNT(*) FROM found),
    'documents', COALESCE((
        SELECT jsonb_agg(to_jsonb(f) ORDER BY f.document_date DESC NULLS LAST, f.reference, f.document_id)
          FROM (SELECT * FROM found ORDER BY document_date DESC NULLS LAST, reference, document_id LIMIT 200) f
    ), '[]'::jsonb)
);
$fn$;

REVOKE ALL ON FUNCTION public.documents_with_unrecorded_stock(uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.documents_with_unrecorded_stock(uuid, uuid) TO service_role;

DO $$
DECLARE v_fn regprocedure := 'public.documents_with_unrecorded_stock(uuid, uuid)'::regprocedure;
BEGIN
    IF has_function_privilege('authenticated', v_fn, 'EXECUTE') OR has_function_privilege('anon', v_fn, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 581: % is executable by a signed-in or anonymous role', v_fn; END IF;
    IF NOT has_function_privilege('service_role', v_fn, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 581: % is not executable by the service role', v_fn; END IF;
END
$$;

COMMIT;
