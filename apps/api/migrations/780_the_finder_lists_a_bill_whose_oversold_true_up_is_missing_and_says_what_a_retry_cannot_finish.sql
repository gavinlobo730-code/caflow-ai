-- Migration 780: the finder also lists a purchase bill whose oversold true-up entry is missing, and says which listed documents a retry cannot finish (POST-A-092).
--
-- WHAT WAS WRONG
--   `public.documents_with_unrecorded_stock` (579, 581, 620) lists the issued documents that owe a stock movement and have none, or whose VALUED
--   movement has no journal. Two shapes stayed outside it or inside it with no way forward:
--     1. A purchase bill received while the item was already oversold: the cost of the units that covered the earlier sales is moved to Cost of Goods
--        Sold by a separate entry (reference ending -COGSTRUEUP). If that entry failed, the stock rows have NIL value and nothing owes a journal
--        by the finder's rule, so the bill was never listed and the books stayed wrong with no sign of it.
--     2. A bill with freight, insurance or duty recorded against it whose stock rows have no journal: listed, but a retry refuses it (the split of
--        each charge over the goods is not kept on the row, so rebuilding it would be a guess about a ledger figure), and the screen only said so
--        after the press.
--
-- WHAT THIS DOES
--   The function is replaced with migration 620's body (the last definition, found by number) and three additions:
--     * a bill with a purchase row that covered an earlier oversold sale (a row of NIL value, or one written while the item's quantity was below
--       nil) for an item whose bill line has a cost, and no standing -COGSTRUEUP entry for the bill, is found;
--     * every found document carries `hand_fix`: 'landed_charges' (a bill with recorded charges and unjournalled rows), 'oversold_trueup' (the
--       shape in 1), or null (a retry can finish it). The sentence that says what to do is the API's, not the database's.
--   It rebuilds no ledger figure and posts nothing. The AMOUNT of a true-up is not kept on the rows, so for a bill that only partly covered an
--   earlier sale the finder says that one is owed and the screen tells the CA to work out the covered part; it cannot say how much.
--   Privileges are the ones 579 gave, asserted again at the end: the service role and nobody signed in or anonymous.
--
-- Reversible: 780_..._rollback.sql puts 620's function back.

BEGIN;

SELECT set_config('lock_timeout', '15s', true);

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
           (COUNT(*) FILTER (WHERE s.journal_entry_id IS NULL AND s.value_delta_paise <> 0))::int AS unjournalled_rows,
           -- a purchase row, for an item whose bill line has a cost, that covered units sold while the item was oversold: either its value is NIL
           -- (the whole cost went to cover them) or the quantity before it was below nil (a part did: running quantity less the quantity it added,
           -- the rule `stock_resume.was_short_when_recorded` uses). What records the covered cost is a separate entry (reference ending
           -- -COGSTRUEUP), not the row
           (COUNT(*) FILTER (WHERE s.movement_type = 'purchase'
                              AND (s.value_delta_paise = 0 OR s.running_qty_units - s.quantity_delta < 0)
                              AND EXISTS (SELECT 1 FROM public.purchase_bill_lines l
                                           WHERE l.bill_id = s.source_id AND l.service_catalogue_id = s.service_catalogue_id
                                             AND COALESCE(l.quantity, 0) > 0 AND COALESCE(l.taxable_amount_paise, 0) > 0)))::int AS nil_cost_rows
      FROM public.inventory_stock_ledger s
     WHERE s.firm_id = p_firm AND s.client_id = p_client
       AND (s.source_type, s.movement_type) IN (('sales_invoice', 'sale'), ('purchase_bill', 'purchase'),
                                                 ('credit_note', 'sale_return'), ('debit_note', 'purchase_return'))
     GROUP BY s.source_type, s.source_id
),
trueup AS (
    -- a bill's oversold true-up entry that stands: not reversed, not deleted
    SELECT DISTINCT j.source_id AS doc_id
      FROM public.journal_entries j
     WHERE j.firm_id = p_firm AND j.client_id = p_client AND j.source_type = 'purchase_bill'
       AND j.reference_no LIKE '%-COGSTRUEUP' AND COALESCE(j.is_reversed, false) = false AND j.deleted_at IS NULL
),
landed AS (
    -- a bill with freight, insurance, duty or another charge recorded against it (migration 396)
    SELECT DISTINCT c.bill_id AS doc_id FROM public.purchase_bill_landed_costs c WHERE c.firm_id = p_firm AND c.client_id = p_client
),
found AS (
    SELECT d.kind, d.id AS document_id, d.reference, d.document_date,
           o.owed_lines, COALESCE(m.moved_lines, 0) AS moved_lines, COALESCE(m.unjournalled_rows, 0) AS unjournalled_rows,
           -- which listed documents a retry CANNOT finish, and why (migration 780): the CA puts these right by hand
           CASE
             WHEN d.kind = 'purchase_bill' AND COALESCE(m.unjournalled_rows, 0) > 0
                  AND EXISTS (SELECT 1 FROM landed ld WHERE ld.doc_id = d.id) THEN 'landed_charges'
             WHEN d.kind = 'purchase_bill' AND COALESCE(m.nil_cost_rows, 0) > 0
                  AND NOT EXISTS (SELECT 1 FROM trueup t WHERE t.doc_id = d.id) THEN 'oversold_trueup'
           END AS hand_fix
      FROM docs d
      JOIN owed o ON o.kind = d.kind AND o.doc_id = d.id
      LEFT JOIN moved m ON m.kind = d.kind AND m.doc_id = d.id
     WHERE (COALESCE(m.moved_lines, 0) < o.owed_lines OR COALESCE(m.unjournalled_rows, 0) > 0
            OR (d.kind = 'purchase_bill' AND COALESCE(m.nil_cost_rows, 0) > 0
                AND NOT EXISTS (SELECT 1 FROM trueup t WHERE t.doc_id = d.id)))
       -- a document the CA marked as settled by hand (migration 620) is not listed: the mark is theirs, the list is what the stock rows show
       AND NOT EXISTS (SELECT 1 FROM public.stock_effect_settlements s
                        WHERE s.firm_id = p_firm AND s.client_id = p_client AND s.document_kind = d.kind AND s.document_id = d.id)
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
        RAISE EXCEPTION 'migration 780: % is executable by a signed-in or anonymous role', v_fn; END IF;
    IF NOT has_function_privilege('service_role', v_fn, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 780: % is not executable by the service role', v_fn; END IF;
END
$$;

COMMIT;
