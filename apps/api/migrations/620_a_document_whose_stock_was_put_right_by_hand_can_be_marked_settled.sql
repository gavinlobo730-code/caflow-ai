-- Migration 620: a document whose stock effect the CA already put right by hand can be marked settled, and the finder stops listing it (POST-A-092).
--
-- ====================================================================================================================================
-- WHAT WAS WRONG
-- ====================================================================================================================================
-- `public.documents_with_unrecorded_stock` (migrations 579 and 581) lists the issued documents that owe a stock movement and have none, or
-- whose valued movement has no journal, and the client's Inventory tab offers "Complete the stock" beside each. What the list shows is
-- what the stock ROWS show. A CA who had already put such a document right by hand (a stock adjustment, a count correction, a journal)
-- still saw it listed for ever, and "Complete the stock" would then move the goods a second time: the button asks first and warns, and
-- that is all the product could do, because nothing recorded that the document was dealt with. A list that never empties teaches a CA to
-- stop reading it.
--
-- ====================================================================================================================================
-- WHAT THIS DOES
-- ====================================================================================================================================
--   * `public.stock_effect_settlements`: one row per document the CA has marked as settled by hand. A document is named by its kind (the
--     four that move stock) and its id; the row keeps the reference and the date the document had when it was marked (so the list of marks
--     reads without joining four tables), the reason the CA typed (required, 1 to 500 characters: the mark is a statement about the
--     books and says why), and who marked it and when (the person's internal id and their name as it was). A document has at most one
--     mark. The mark moves no stock and posts no journal: it only stops the list offering to.
--   * `public.documents_with_unrecorded_stock` is replaced with migration 581's body (the last definition, found by number) and one more
--     condition: a document with a mark is not found. `total` therefore does not count it either. Privileges are the ones 579 gave and
--     the file asserts them again: executable by the service role and by no signed-in or anonymous role.
--   * The table is written and read by the API's privileged client only, after the route has proved the caller's access to the client
--     and asked the accounting permission: every privilege is revoked from PUBLIC, anon and authenticated, the firm isolation, the
--     assignment scope and the internal practice's Partner-only rule are still declared (as on 592), and the two firm checks of 565 and
--     566 guard the writes. Nothing signed in reads or writes it.
--
-- It writes no row. Nothing here transmits anything to a portal. A mark can be taken back by the API (the document is listed again).
-- Reversible: 620_..._rollback.sql puts 581's function back and drops the table, which loses the marks.

BEGIN;

SELECT set_config('lock_timeout', '15s', true);

CREATE TABLE IF NOT EXISTS public.stock_effect_settlements (
  id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id          UUID        NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id        UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  document_kind    TEXT        NOT NULL,
  document_id      UUID        NOT NULL,
  reference        TEXT,
  document_date    DATE,
  reason           TEXT        NOT NULL,
  settled_by       UUID        REFERENCES public.users(id) ON DELETE SET NULL,
  settled_by_name  TEXT,
  settled_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT stock_effect_settlements_one_per_document UNIQUE (client_id, document_kind, document_id),
  CONSTRAINT stock_effect_settlements_kind
    CHECK (document_kind IN ('sales_invoice', 'purchase_bill', 'credit_note', 'debit_note')),
  CONSTRAINT stock_effect_settlements_reason CHECK (char_length(btrim(reason)) BETWEEN 1 AND 500),
  CONSTRAINT stock_effect_settlements_lines
    CHECK (char_length(coalesce(reference, '')) <= 200 AND char_length(coalesce(settled_by_name, '')) <= 200)
);

COMMENT ON TABLE public.stock_effect_settlements IS
  'POST-A-092, migration 620. A document whose stock effect the CA put right by hand and marked settled, with the reason they typed. '
  'The finder documents_with_unrecorded_stock does not list a marked document. Moves no stock and posts no journal. Written and read by the API only.';

CREATE INDEX IF NOT EXISTS idx_stock_effect_settlements_client
  ON public.stock_effect_settlements (firm_id, client_id, settled_at DESC);

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['stock_effect_settlements'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);

        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_firm_isolation', t);
        EXECUTE format('CREATE POLICY %I ON public.%I FOR ALL TO authenticated '
                       'USING (firm_id = (SELECT public.get_my_firm_id())) '
                       'WITH CHECK (firm_id = (SELECT public.get_my_firm_id()))', t || '_firm_isolation', t);

        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_assignment_scope', t);
        EXECUTE format('CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR ALL '
                       'USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = ''Partner''::text '
                       '       OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false)) '
                       'WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = ''Partner''::text '
                       '       OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))',
                       t || '_assignment_scope', t);

        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_internal_partner_only', t);
        EXECUTE format('CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR ALL '
                       'USING ((SELECT public.get_my_role()) = ''Partner''::text '
                       '       OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text) '
                       'WITH CHECK ((SELECT public.get_my_role()) = ''Partner''::text '
                       '       OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)',
                       t || '_internal_partner_only', t);

        -- Nobody signed in reads or writes it: the API's privileged client does both, after it has asked who is calling.
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC, anon, authenticated', t);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO service_role', t);

        PERFORM public.guard_client_firm('public.' || t);
        PERFORM public.guard_member_firm('public.' || t);
    END LOOP;
END $$;

-- The finder, as migration 581 last defined it, with one more condition (a marked document is not found).
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
     WHERE (COALESCE(m.moved_lines, 0) < o.owed_lines OR COALESCE(m.unjournalled_rows, 0) > 0)
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
        RAISE EXCEPTION 'migration 620: % is executable by a signed-in or anonymous role', v_fn; END IF;
    IF NOT has_function_privilege('service_role', v_fn, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 620: % is not executable by the service role', v_fn; END IF;
    IF has_table_privilege('authenticated', 'public.stock_effect_settlements', 'SELECT, INSERT, UPDATE, DELETE')
       OR has_table_privilege('anon', 'public.stock_effect_settlements', 'SELECT, INSERT, UPDATE, DELETE') THEN
        RAISE EXCEPTION 'migration 620: public.stock_effect_settlements is reachable by a signed-in or anonymous role'; END IF;
END
$$;

COMMIT;
