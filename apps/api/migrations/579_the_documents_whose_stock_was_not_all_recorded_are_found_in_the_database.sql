-- Migration 579 — the documents whose stock effect was not all recorded are found in the database (POST-A-092, items 1 and 2).
--
-- WHAT IS WRONG TODAY
--   A sales invoice, purchase bill, credit note or purchase debit note moves stock AFTER it is issued, and the step is fail-soft by
--   design (a refused ledger row or a chart with no Inventory or Cost of Goods Sold account must not un-issue a document that is in
--   the books and the return). The response that issued it says so, once. Nothing found the document afterwards: the nightly check
--   compares from the LEDGER side, so it names stock that moved with no journal and cannot name a goods document with no stock
--   movement at all. On 3-11-2026, read-only on production, 7 of 5,658 issued sales invoices that carry a goods line had NO stock
--   movement, and one sale row had no journal behind it.
--
-- WHAT THIS ADDS
--   public.documents_with_unrecorded_stock(p_firm uuid, p_client uuid) RETURNS jsonb: the client's live documents (issued, received,
--   paid; not draft, not cancelled, not deleted, not an opening balance) of the four kinds that have at least one OWED goods line and
--   either fewer stock-ledger rows than owed lines or a stock row that has a value and no journal behind it. One round trip, an
--   answer the size of the problem and not of the ledger.
--
--   OWED GOODS LINE = a line whose catalogue item is this firm's and this client's own item of kind 'good' with a quantity above nil,
--   and, on a purchase bill, a taxable value above nil. This is a count of lines, the same count the stock step makes, with one known
--   difference: the stock step prices a bill line at its taxable value PLUS the tax nobody can reclaim PLUS its share of the landed
--   charges, so a bill line with a nil taxable value and a non-nil other part is owed there and not counted here. That direction
--   cannot list a document that is whole; it can leave one unlisted.
--
--   A STOCK ROW with a value and no journal is a row the stock step wrote and did not journal. A row of nil value (an oversold
--   sale at no cost basis) owes no journal and is not counted. On production the journal link is stamped on every such row but one,
--   so a row without it is a real finding and not legacy noise.
--
-- WHO MAY CALL IT
--   The server alone, like 577: the route proves the caller's access to the client and then asks with the privileged client. It is
--   SECURITY INVOKER, so it can read nothing the caller of it cannot, and no signed-in role can execute it.
--
-- WHAT IT DOES NOT DO
--   It writes nothing and repairs nothing: the retry is `POST /api/inventory/stock-effects/retry`, which asks the same four functions
--   a first issue asks. It does not look at a cancelled document's reversal rows, and it does not say WHY a document is listed.
--
-- Reversible: 579_..._rollback.sql drops the function.

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

DO $$
DECLARE v_fn regprocedure := 'public.documents_with_unrecorded_stock(uuid, uuid)'::regprocedure;
BEGIN
    IF has_function_privilege('authenticated', v_fn, 'EXECUTE') OR has_function_privilege('anon', v_fn, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 579: % is executable by a signed-in or anonymous role', v_fn; END IF;
    IF NOT has_function_privilege('service_role', v_fn, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 579: % is not executable by the service role', v_fn; END IF;
END
$$;
