-- Migration 766: the firm Reports page's P&L Statement nets credit and debit notes (ledger POST-A-502).
--
-- WHAT WAS WRONG
-- public.report_party_totals (migration 745) added the taxable value of the counted sales invoices and purchase
-- bills and nothing else, which is what the browser's own arithmetic had always done. The CGST Act section 34 notes
-- that change a supply's value were in it nowhere, so a month with a sales credit note showed more revenue than the
-- books hold, and a month with a purchase return showed more expense. The ledger posts all four (phase2_journal_service):
--   a sales credit note        Dr Sales Returns, taxable value     -> REDUCES revenue
--   a sales debit note         Cr Sales Revenue, taxable value     -> INCREASES revenue
--   a purchase debit note      Cr Purchases, taxable value         -> REDUCES expense   (a purchase return)
--   a purchase credit note     Dr Purchases, taxable value         -> INCREASES expense
-- and this function now reads them the same way, so the screen's net profit and the ledger's agree on a month with notes.
--
-- WHAT THIS DOES
-- Replaces the function, same name and arguments, derived from migration 745 (the only migration that defined it).
-- A note counts when it is issued (or applied: a credit note's CHECK allows that third word), is not deleted, belongs to
-- a client of the firm named in the list when one is given, and is dated inside the window when one is given, by its own
-- date: the same rule as the invoices and bills. Each note is added to, or taken from, the line of the party it names, so
-- a customer's line is invoices less credit notes plus debit notes, and a line can be negative where a credit note falls
-- in a window its invoice does not. The answer gains three keys and loses none: revenue_notes_paise and
-- expense_notes_paise (the signed effect of the notes on each side, so a screen can say how much of its figure is notes)
-- and note_documents (how many notes were counted). A line's `documents` counts the notes behind it. `sales_documents`
-- and `purchase_documents` still count invoices and bills only, which is what the feed lists.
-- domain/reporting/party_totals.py is the Python twin, and tests/test_report_party_totals_parity_pg.py holds the two identical.
--
-- WHO MAY CALL IT
-- Unchanged: SECURITY INVOKER, EXECUTE granted to the service role alone (re-stated below because CREATE OR REPLACE keeps
-- the grants but this file states them where it matters).
--
-- Function only. No table is created, altered or written. Reversible: 766_..._rollback.sql restores migration 745's body.
-- An API deployed before this migration is applied still answers through the old body (invoices and bills only) and the
-- screen shows no sentence about notes, because the keys are absent; it never shows an unknown as a value.


CREATE OR REPLACE FUNCTION public.report_party_totals(
    p_firm       uuid,
    p_client_ids uuid[] DEFAULT NULL,
    p_from       date DEFAULT NULL,
    p_to         date DEFAULT NULL
) RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public, pg_catalog
AS $fn$
WITH sales_rows AS (
    SELECT i.customer_id AS party_id, COALESCE(i.taxable_amount_paise, 0)::bigint AS amount, false AS is_note
      FROM public.client_sales_invoices i
     WHERE i.firm_id = p_firm
       AND i.deleted_at IS NULL
       AND i.status IN ('issued', 'partially_paid', 'paid')
       AND (p_client_ids IS NULL OR i.client_id = ANY (p_client_ids))
       AND (p_from IS NULL OR i.invoice_date >= p_from)
       AND (p_to IS NULL OR i.invoice_date <= p_to)
    UNION ALL
    -- a sales credit note reduces revenue (Dr Sales Returns)
    SELECT n.customer_id, -COALESCE(n.taxable_amount_paise, 0)::bigint, true
      FROM public.credit_notes n
     WHERE n.firm_id = p_firm
       AND n.deleted_at IS NULL
       AND n.status IN ('issued', 'applied')
       AND (p_client_ids IS NULL OR n.client_id = ANY (p_client_ids))
       AND (p_from IS NULL OR n.credit_note_date >= p_from)
       AND (p_to IS NULL OR n.credit_note_date <= p_to)
    UNION ALL
    -- a sales debit note increases revenue (Cr Sales Revenue)
    SELECT n.customer_id, COALESCE(n.taxable_amount_paise, 0)::bigint, true
      FROM public.sales_debit_notes n
     WHERE n.firm_id = p_firm
       AND n.deleted_at IS NULL
       AND n.status IN ('issued', 'applied')
       AND (p_client_ids IS NULL OR n.client_id = ANY (p_client_ids))
       AND (p_from IS NULL OR n.debit_note_date >= p_from)
       AND (p_to IS NULL OR n.debit_note_date <= p_to)
), bills_rows AS (
    SELECT b.vendor_id AS party_id, COALESCE(b.taxable_amount_paise, 0)::bigint AS amount, false AS is_note
      FROM public.purchase_bills b
     WHERE b.firm_id = p_firm
       AND b.deleted_at IS NULL
       AND b.status IN ('received', 'partially_paid', 'paid')
       AND (p_client_ids IS NULL OR b.client_id = ANY (p_client_ids))
       AND (p_from IS NULL OR b.bill_date >= p_from)
       AND (p_to IS NULL OR b.bill_date <= p_to)
    UNION ALL
    -- a purchase debit note reduces expense (Cr Purchases: a purchase return)
    SELECT n.vendor_id, -COALESCE(n.taxable_amount_paise, 0)::bigint, true
      FROM public.debit_notes n
     WHERE n.firm_id = p_firm
       AND n.deleted_at IS NULL
       AND n.status IN ('issued', 'applied')
       AND (p_client_ids IS NULL OR n.client_id = ANY (p_client_ids))
       AND (p_from IS NULL OR n.debit_note_date >= p_from)
       AND (p_to IS NULL OR n.debit_note_date <= p_to)
    UNION ALL
    -- a purchase credit note increases expense (Dr Purchases)
    SELECT n.vendor_id, COALESCE(n.taxable_amount_paise, 0)::bigint, true
      FROM public.purchase_credit_notes n
     WHERE n.firm_id = p_firm
       AND n.deleted_at IS NULL
       AND n.status IN ('issued', 'applied')
       AND (p_client_ids IS NULL OR n.client_id = ANY (p_client_ids))
       AND (p_from IS NULL OR n.credit_note_date >= p_from)
       AND (p_to IS NULL OR n.credit_note_date <= p_to)
), sales AS (
    SELECT party_id, SUM(amount)::bigint AS total, COUNT(*)::bigint AS n
      FROM sales_rows GROUP BY party_id
), bills AS (
    SELECT party_id, SUM(amount)::bigint AS total, COUNT(*)::bigint AS n
      FROM bills_rows GROUP BY party_id
)
SELECT jsonb_build_object(
    'revenue', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
                   'party_id', s.party_id,
                   'party_name', NULLIF(c.name, ''),
                   'total_paise', s.total,
                   'documents', s.n)
               ORDER BY (s.party_id IS NULL), s.total DESC, s.party_id)
          FROM sales s
          LEFT JOIN public.customers c ON c.id = s.party_id AND c.firm_id = p_firm), '[]'::jsonb),
    'expenses', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
                   'party_id', b.party_id,
                   'party_name', NULLIF(v.name, ''),
                   'total_paise', b.total,
                   'documents', b.n)
               ORDER BY (b.party_id IS NULL), b.total DESC, b.party_id)
          FROM bills b
          LEFT JOIN public.vendors v ON v.id = b.party_id AND v.firm_id = p_firm), '[]'::jsonb),
    'revenue_total_paise', (SELECT COALESCE(SUM(total), 0)::bigint FROM sales),
    'expense_total_paise', (SELECT COALESCE(SUM(total), 0)::bigint FROM bills),
    'net_paise', (SELECT COALESCE(SUM(total), 0)::bigint FROM sales) - (SELECT COALESCE(SUM(total), 0)::bigint FROM bills),
    'sales_documents', (SELECT COUNT(*)::bigint FROM sales_rows WHERE NOT is_note),
    'purchase_documents', (SELECT COUNT(*)::bigint FROM bills_rows WHERE NOT is_note),
    'revenue_notes_paise', (SELECT COALESCE(SUM(amount), 0)::bigint FROM sales_rows WHERE is_note),
    'expense_notes_paise', (SELECT COALESCE(SUM(amount), 0)::bigint FROM bills_rows WHERE is_note),
    'note_documents', (SELECT COUNT(*)::bigint FROM sales_rows WHERE is_note)
                    + (SELECT COUNT(*)::bigint FROM bills_rows WHERE is_note)
);
$fn$;

COMMENT ON FUNCTION public.report_party_totals(uuid, uuid[], date, date) IS
    'The firm Reports page''s P&L Statement: taxable value of the counted sales invoices and purchase bills by party, '
    'net of the issued credit and debit notes (a sales credit note and a purchase debit note reduce, a sales debit note '
    'and a purchase credit note increase, as the ledger posts them), with both totals. domain/reporting/party_totals.py '
    'is its Python twin; tests/test_report_party_totals_parity_pg.py pins them. Called by the API''s privileged client '
    'only. Migrations 745 and 766.';

REVOKE ALL ON FUNCTION public.report_party_totals(uuid, uuid[], date, date) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.report_party_totals(uuid, uuid[], date, date) TO service_role;
