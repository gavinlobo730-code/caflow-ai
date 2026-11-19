-- Migration 745: the firm Reports page's P&L Statement is summed by the database (ledger POST-A-469).
--
-- WHAT WAS WRONG
-- The P&L Statement on /reports read every counted sales invoice and purchase bill in its window through
-- GET /api/reports/transactions and added their taxable value by party IN THE BROWSER, a figure computed outside
-- apps/api. The rows crossing the wire grew with the ledger, which CLAUDE.md's reporting rule forbids for a report.
--
-- WHAT THIS DOES
-- Creates public.report_party_totals(firm, client ids, from, to): the taxable value of each counted document grouped
-- by the party it names (a sales invoice's customer is revenue, a purchase bill's supplier is expense), with both
-- totals and the net, as one jsonb answer. Which documents count is the same as the feed's
-- (services/report_transactions_service.py): not deleted, a sales invoice issued, part-paid or paid, a purchase bill
-- received, part-paid or paid, dated inside the window when one is given, of the clients named when a list is given.
-- domain/reporting/party_totals.py is its Python twin (mock mode, and the minutes the API runs before this
-- migration), and tests/test_report_party_totals_parity_pg.py holds the two identical.
--
-- WHO MAY CALL IT
-- SECURITY INVOKER, and EXECUTE is granted to the service role alone. The API calls it with its privileged client
-- after the route has asked whether the caller may read each client (routers/reports.py), and names the firm; a
-- signed-in session cannot call it, so it needs no `assert_caller_acts_for` of its own.
--
-- New function only. No table is created, altered or written. Reversible: 745_..._rollback.sql drops it.


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
WITH sales AS (
    SELECT i.customer_id AS party_id,
           SUM(COALESCE(i.taxable_amount_paise, 0))::bigint AS total,
           COUNT(*)::bigint AS n
      FROM public.client_sales_invoices i
     WHERE i.firm_id = p_firm
       AND i.deleted_at IS NULL
       AND i.status IN ('issued', 'partially_paid', 'paid')
       AND (p_client_ids IS NULL OR i.client_id = ANY (p_client_ids))
       AND (p_from IS NULL OR i.invoice_date >= p_from)
       AND (p_to IS NULL OR i.invoice_date <= p_to)
     GROUP BY i.customer_id
), bills AS (
    SELECT b.vendor_id AS party_id,
           SUM(COALESCE(b.taxable_amount_paise, 0))::bigint AS total,
           COUNT(*)::bigint AS n
      FROM public.purchase_bills b
     WHERE b.firm_id = p_firm
       AND b.deleted_at IS NULL
       AND b.status IN ('received', 'partially_paid', 'paid')
       AND (p_client_ids IS NULL OR b.client_id = ANY (p_client_ids))
       AND (p_from IS NULL OR b.bill_date >= p_from)
       AND (p_to IS NULL OR b.bill_date <= p_to)
     GROUP BY b.vendor_id
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
    'sales_documents', (SELECT COALESCE(SUM(n), 0)::bigint FROM sales),
    'purchase_documents', (SELECT COALESCE(SUM(n), 0)::bigint FROM bills)
);
$fn$;

COMMENT ON FUNCTION public.report_party_totals(uuid, uuid[], date, date) IS
    'The firm Reports page''s P&L Statement: taxable value of the counted sales invoices and purchase bills by party, '
    'with both totals. domain/reporting/party_totals.py is its Python twin; tests/test_report_party_totals_parity_pg.py '
    'pins them. Called by the API''s privileged client only. Migration 745.';

REVOKE ALL ON FUNCTION public.report_party_totals(uuid, uuid[], date, date) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.report_party_totals(uuid, uuid[], date, date) TO service_role;

