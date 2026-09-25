-- Migration 419: who a control account's balance is owed by, or owed to.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING (ACC-13's other half)
-- ═══════════════════════════════════════════════════════════════════════════
-- Drilling into Trade Receivables showed one pooled control account. The
-- per-customer view existed only on the separate Customer Statement screen,
-- which is built from DOCUMENTS rather than from the ledger — so when the two
-- disagreed there was nothing that said WHICH entries were the difference.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY A SQL FUNCTION AND NOT A PYTHON READ
-- ═══════════════════════════════════════════════════════════════════════════
-- CLAUDE.md's reporting rule: what crosses the wire must be proportional to
-- the ANSWER, not to the ledger. The answer here is one row per party — tens
-- to hundreds — and the input is every line ever posted to the account. The
-- measured case is cash-flow: 12,836 entries took 54.34s unaggregated against
-- 2.15s off a pre-aggregated read. This cannot be pre-bucketed by month the
-- way account_period_balances is, because the party comes from a JOIN to the
-- document, so it is the public.cash_flow_report shape (migration 277): a
-- function that aggregates server-side and returns finished rows.
--
-- domain/accounting/party_ledger.py is the identical rule for mock mode and
-- local dev, where there are no SQL functions at all, and
-- tests/test_party_ledger_parity_pg.py runs every scenario through both.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- NO NEW COLUMN. THE PARTY IS ALREADY ON THE DOCUMENT.
-- ═══════════════════════════════════════════════════════════════════════════
-- journal_entries.source_type / source_id have named the document on all
-- twenty-six posting paths since ACC-22, and all eight mapped tables carry
-- customer_id or vendor_id NOT NULL. Migration 418 DID add a column for a cost
-- centre, and the two are not inconsistent: a cost centre is a fact no
-- document holds, a party is a fact every document already holds.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE UNATTRIBUTED ROWS ARE THE ANSWER, NOT A GAP IN IT
-- ═══════════════════════════════════════════════════════════════════════════
-- manual, Opening, TrialBalance, year_end_adjustment and a directly-posted
-- bank_transaction name no party — and together they are exactly the
-- difference between this control account and the sum of the party
-- sub-ledgers. So they are returned, one row per SOURCE KIND so "manual" and
-- "Opening" are told apart, and `Σ attributed + Σ unattributed` equals the
-- account's own balance BY CONSTRUCTION.
--
-- ⚠️ THE JOINS TO `customers` AND `vendors` ARE LEFT JOINS ON PURPOSE.
-- debit_notes.vendor_id (migration 145) and purchase_credit_notes.vendor_id
-- (210, which says so in its own comment) carry NO foreign key, so an inner
-- join would silently drop a deleted party's balance out of a total that must
-- foot. A party row with no master reads as '(unnamed)' and keeps its money.

BEGIN;

CREATE OR REPLACE FUNCTION public.party_ledger_as_at(
    p_firm    uuid,
    p_client  uuid,
    p_account uuid,
    p_as_of   date
) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path TO 'public', 'pg_catalog'
AS $function$
DECLARE
  v_rows jsonb;
  v_att  bigint;
  v_un   bigint;
BEGIN
  WITH lines AS (
      SELECT je.source_type,
             je.source_id,
             jl.debit_paise,
             jl.credit_paise
      FROM public.journal_lines jl
      JOIN public.journal_entries je ON je.id = jl.journal_entry_id
      WHERE je.firm_id    = p_firm
        AND je.client_id  = p_client
        AND jl.account_id = p_account
        AND je.is_posted
        AND je.deleted_at IS NULL
        AND je.entry_date <= p_as_of
  ),
  resolved AS (
      SELECT l.debit_paise,
             l.credit_paise,
             l.source_type,
             CASE l.source_type
                 WHEN 'sales_invoice'    THEN (SELECT customer_id FROM public.client_sales_invoices WHERE id = l.source_id)
                 WHEN 'credit_note'      THEN (SELECT customer_id FROM public.credit_notes          WHERE id = l.source_id)
                 WHEN 'sales_debit_note' THEN (SELECT customer_id FROM public.sales_debit_notes     WHERE id = l.source_id)
                 WHEN 'receipt'          THEN (SELECT customer_id FROM public.receipts              WHERE id = l.source_id)
             END AS customer_id,
             CASE l.source_type
                 WHEN 'purchase_bill'        THEN (SELECT vendor_id FROM public.purchase_bills        WHERE id = l.source_id)
                 WHEN 'debit_note'           THEN (SELECT vendor_id FROM public.debit_notes           WHERE id = l.source_id)
                 WHEN 'purchase_credit_note' THEN (SELECT vendor_id FROM public.purchase_credit_notes WHERE id = l.source_id)
                 WHEN 'purchase_payment'     THEN (SELECT vendor_id FROM public.purchase_payments     WHERE id = l.source_id)
             END AS vendor_id
      FROM lines l
  ),
  grouped AS (
      -- Customers.
      SELECT r.customer_id                          AS party_id,
             COALESCE(c.name, '(unnamed)')          AS party_name,
             'customer'::text                       AS party_kind,
             NULL::text                             AS unattributed_source,
             SUM(r.debit_paise)::bigint             AS debit_paise,
             SUM(r.credit_paise)::bigint            AS credit_paise
      FROM resolved r LEFT JOIN public.customers c ON c.id = r.customer_id
      WHERE r.customer_id IS NOT NULL
      GROUP BY r.customer_id, c.name

      UNION ALL
      -- Vendors.
      SELECT r.vendor_id, COALESCE(v.name, '(unnamed)'), 'vendor', NULL::text,
             SUM(r.debit_paise)::bigint, SUM(r.credit_paise)::bigint
      FROM resolved r LEFT JOIN public.vendors v ON v.id = r.vendor_id
      WHERE r.vendor_id IS NOT NULL
      GROUP BY r.vendor_id, v.name

      UNION ALL
      -- Everything the map could not attribute, grouped by the source it DID
      -- carry. Never dropped: these rows are what makes the parts sum to the
      -- account, and each source kind is its own row because the five reasons
      -- are not interchangeable.
      SELECT NULL::uuid, ''::text, NULL::text,
             COALESCE(r.source_type, ''),
             SUM(r.debit_paise)::bigint, SUM(r.credit_paise)::bigint
      FROM resolved r
      WHERE r.customer_id IS NULL AND r.vendor_id IS NULL
      GROUP BY COALESCE(r.source_type, '')
  )
  SELECT
      COALESCE(jsonb_agg(to_jsonb(g) ORDER BY
          (g.party_id IS NULL),                       -- parties first
          abs(g.debit_paise - g.credit_paise) DESC,   -- then by size
          g.party_name, g.unattributed_source), '[]'::jsonb),
      COALESCE(SUM(g.debit_paise - g.credit_paise) FILTER (WHERE g.party_id IS NOT NULL), 0),
      COALESCE(SUM(g.debit_paise - g.credit_paise) FILTER (WHERE g.party_id IS NULL), 0)
  INTO v_rows, v_att, v_un
  FROM grouped g;

  RETURN jsonb_build_object(
      'as_of',              to_char(p_as_of, 'YYYY-MM-DD'),
      'account_id',         p_account,
      'rows',               v_rows,
      'attributed_paise',   v_att,
      'unattributed_paise', v_un
  );
END;
$function$;

COMMENT ON FUNCTION public.party_ledger_as_at(uuid, uuid, uuid, date) IS
  'Who a control account is owed by or owed to, as at a date (ACC-13). One row '
  'per party plus one per unattributable source kind; the two together equal '
  'the account''s own balance by construction. Python twin: '
  'domain/accounting/party_ledger.py, pinned by test_party_ledger_parity_pg.';

REVOKE EXECUTE ON FUNCTION public.party_ledger_as_at(uuid, uuid, uuid, date) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.party_ledger_as_at(uuid, uuid, uuid, date) FROM anon;
GRANT  EXECUTE ON FUNCTION public.party_ledger_as_at(uuid, uuid, uuid, date)
  TO authenticated, service_role;

COMMIT;
