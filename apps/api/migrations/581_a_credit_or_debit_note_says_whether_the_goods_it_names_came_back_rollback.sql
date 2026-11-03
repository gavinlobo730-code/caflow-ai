-- Rollback of migration 581: put migration 579's finder back and take the two goods_returned columns away (POST-A-371).
-- A note's stated choice is lost with its column; nothing else is touched.
BEGIN;

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
    UNION ALL
    SELECT 'debit_note', d.id, d.debit_note_no::text, d.debit_note_date
      FROM public.debit_notes d
     WHERE d.firm_id = p_firm AND d.client_id = p_client AND d.deleted_at IS NULL
       AND d.status NOT IN ('draft', 'cancelled')
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

ALTER TABLE public.credit_notes DROP COLUMN IF EXISTS goods_returned;
ALTER TABLE public.debit_notes DROP COLUMN IF EXISTS goods_returned;

COMMIT;
