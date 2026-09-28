-- Rollback for 434. Restores migration 279's cash_flow_report exactly (no
-- Opening-entry exclusion, no opening_fold) — the body is transcribed from
-- 279 unchanged.
BEGIN;

CREATE OR REPLACE FUNCTION public.cash_flow_report(
    p_firm   uuid,
    p_client uuid,
    p_start  date,
    p_end    date
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    v_my_firm  uuid;
    v_internal uuid;
    v_out      jsonb;
BEGIN
    IF auth.uid() IS NOT NULL THEN
        v_my_firm := public.get_my_firm_id();

        IF v_my_firm IS NULL THEN
            RAISE EXCEPTION 'cash_flow_report: caller has no user record in this database'
                USING ERRCODE = '42501';
        END IF;

        IF p_firm IS DISTINCT FROM v_my_firm THEN
            RAISE EXCEPTION 'cash_flow_report: firm % is not the caller''s firm', p_firm
                USING ERRCODE = '42501';
        END IF;

        IF NOT public.can_access_client(p_client::text) THEN
            RAISE EXCEPTION 'cash_flow_report: client % is not assigned to the caller', p_client
                USING ERRCODE = '42501';
        END IF;

        v_internal := public.my_internal_client_id();
        IF v_internal IS NOT NULL
           AND p_client = v_internal
           AND COALESCE(public.get_my_role(), '') <> 'Partner' THEN
            RAISE EXCEPTION 'cash_flow_report: only a Partner may read the firm''s internal client'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    SELECT (
    WITH acct AS (
        SELECT c.id,
               COALESCE(c.account_code, '') AS code,
               COALESCE(c.account_name, '') AS name,
               COALESCE(c.account_type, '') AS type,
               c.account_subtype            AS subtype,
               c.system_account_key         AS system_key
          FROM public.chart_of_accounts c
         WHERE c.firm_id = p_firm
           AND (c.client_id = p_client OR c.client_id IS NULL)
    ),
    keyed_bank AS (SELECT 1 FROM acct WHERE system_key = 'bank' LIMIT 1),
    cls AS (
        SELECT a.*,
               (a.type IN ('Revenue', 'Income')) AS is_income,
               (a.type = 'Expense')              AS is_expense,
               (a.system_key = 'bank'
                OR (NOT EXISTS (SELECT 1 FROM keyed_bank)
                    AND a.type = 'Asset'
                    AND lower(a.name || ' ' || COALESCE(a.subtype, '')) ~ 'bank|cash')
               ) AS is_bank,
               CASE
                 WHEN a.system_key IN ('ar', 'ap', 'gst_input', 'gst_output', 'gst_cgst',
                                       'gst_sgst', 'gst_igst', 'tds_payable', 'tds_receivable',
                                       'advance_customer', 'advance_vendor')
                   THEN 'operating'
                 WHEN a.type = 'Asset' THEN
                   CASE WHEN lower(COALESCE(a.subtype, '')) ~ 'fixed|investment|non-current|non current'
                        THEN 'investing' ELSE 'operating' END
                 WHEN a.type = 'Equity' THEN 'financing'
                 WHEN a.type = 'Liability' THEN
                   CASE WHEN lower(COALESCE(a.subtype, '')) ~ 'loan|borrow|long-term|long term|non-current|non current'
                        THEN 'financing' ELSE 'operating' END
                 ELSE 'operating'
               END AS activity
          FROM acct a
    ),
    ln AS (
        SELECT je.id                             AS entry_id,
               jl.account_id,
               COALESCE(jl.debit_paise, 0)       AS debit_paise,
               COALESCE(jl.credit_paise, 0)      AS credit_paise,
               COALESCE(c.is_bank, false)        AS is_bank,
               COALESCE(c.activity, 'operating') AS activity,
               COALESCE(c.is_income, false)      AS is_income,
               COALESCE(c.is_expense, false)     AS is_expense,
               c.type                            AS acct_type,
               c.subtype                         AS acct_subtype,
               (jl.id IS NOT NULL)               AS is_line
          FROM public.journal_entries je
          LEFT JOIN public.journal_lines jl ON jl.journal_entry_id = je.id
          LEFT JOIN cls c ON c.id = jl.account_id
         WHERE je.firm_id = p_firm
           AND je.client_id = p_client
           AND je.is_posted
           AND je.deleted_at IS NULL
           AND je.entry_date BETWEEN p_start AND p_end
    ),
    ent AS (
        SELECT l.entry_id,
               COALESCE(SUM(CASE WHEN l.is_bank THEN l.debit_paise - l.credit_paise END), 0) AS cash,
               COALESCE(bool_or(l.is_line AND NOT l.is_bank AND l.activity = 'investing'), false) AS has_investing,
               COALESCE(bool_or(l.is_line AND NOT l.is_bank AND l.activity = 'financing'), false) AS has_financing,
               COALESCE(bool_or(l.is_line AND NOT l.is_bank AND l.acct_type = 'Equity'), false)   AS has_equity
          FROM ln l
         GROUP BY l.entry_id
    ),
    ent2 AS (
        SELECT e.*,
               CASE WHEN e.cash = 0      THEN NULL
                    WHEN e.has_investing THEN 'investing'
                    WHEN e.has_financing THEN 'financing'
                    ELSE 'operating' END AS activity
          FROM ent e
    ),
    totals AS (
        SELECT COALESCE(SUM(cash), 0)                                          AS total_cash,
               COALESCE(SUM(cash) FILTER (WHERE activity = 'operating'), 0)    AS operating_cash,
               COALESCE(SUM(cash) FILTER (WHERE activity = 'investing'), 0)    AS investing_cash,
               COALESCE(SUM(cash) FILTER (WHERE activity = 'financing'), 0)    AS financing_cash,
               COUNT(*) FILTER (WHERE cash = 0)                                AS non_cash_count
          FROM ent2
    ),
    nonop AS (
        SELECT COALESCE(SUM(l.credit_paise - l.debit_paise), 0) AS non_operating_pl
          FROM ln l JOIN ent2 e ON e.entry_id = l.entry_id
         WHERE l.is_line AND NOT l.is_bank
           AND e.activity IN ('investing', 'financing')
           AND (l.is_income OR l.is_expense)
    ),
    recon AS (
        SELECT COALESCE(SUM(CASE WHEN l.is_income OR l.is_expense
                                 THEN l.credit_paise - l.debit_paise ELSE 0 END), 0) AS net_profit,
               COALESCE(SUM(CASE WHEN l.is_expense
                                  AND lower(btrim(COALESCE(l.acct_subtype, ''))) = 'depreciation'
                                 THEN l.debit_paise - l.credit_paise ELSE 0 END), 0) AS depreciation,
               COALESCE(SUM(CASE WHEN NOT (l.is_income OR l.is_expense) AND l.activity = 'operating'
                                 THEN l.credit_paise - l.debit_paise ELSE 0 END), 0) AS working_capital
          FROM ln l JOIN ent2 e ON e.entry_id = l.entry_id
         WHERE l.is_line AND NOT l.is_bank
           AND NOT (e.cash = 0 AND e.has_equity)
    ),
    bal AS (
        SELECT COALESCE(SUM(jl.debit_paise - jl.credit_paise)
                        FILTER (WHERE je.entry_date < p_start), 0) AS opening_cash,
               COALESCE(SUM(jl.debit_paise - jl.credit_paise)
                        FILTER (WHERE je.entry_date <= p_end), 0)  AS closing_cash
          FROM public.journal_entries je
          JOIN public.journal_lines jl ON jl.journal_entry_id = je.id
          JOIN cls c ON c.id = jl.account_id AND c.is_bank
         WHERE je.firm_id = p_firm AND je.client_id = p_client
           AND je.is_posted AND je.deleted_at IS NULL
           AND je.entry_date <= p_end
    ),
    attr AS (
        SELECT DISTINCT ON (l.entry_id) l.entry_id, l.account_id, e.activity, e.cash
          FROM ln l JOIN ent2 e ON e.entry_id = l.entry_id
         WHERE l.is_line AND NOT l.is_bank
           AND e.activity IN ('investing', 'financing')
           AND (l.activity = e.activity
                OR NOT EXISTS (SELECT 1 FROM ln l2
                                WHERE l2.entry_id = l.entry_id AND l2.is_line AND NOT l2.is_bank
                                  AND l2.activity = e.activity))
         ORDER BY l.entry_id, (l.debit_paise + l.credit_paise) DESC, l.account_id DESC
    ),
    sect AS (
        SELECT t.activity, a.code,
               jsonb_build_object(
                 'account_id', t.account_id, 'account_code', a.code,
                 'account_name', a.name, 'account_type', a.type,
                 'account_subtype', a.subtype, 'amount_paise', t.amount
               ) AS row
          FROM (SELECT activity, account_id, SUM(cash) AS amount
                  FROM attr GROUP BY activity, account_id) t
          JOIN cls a ON a.id = t.account_id
         WHERE t.amount <> 0
    ),
    inv AS (SELECT COALESCE(jsonb_agg(row ORDER BY code COLLATE "C"), '[]'::jsonb) AS lines
              FROM sect WHERE activity = 'investing'),
    fin AS (SELECT COALESCE(jsonb_agg(row ORDER BY code COLLATE "C"), '[]'::jsonb) AS lines
              FROM sect WHERE activity = 'financing'),
    op_lines AS (
        SELECT jsonb_agg(x.row ORDER BY x.ord) AS lines FROM (
            SELECT 1 AS ord, jsonb_build_object(
                     'account_id', '__net_profit__', 'account_code', '',
                     'account_name', 'Net profit for the period', 'account_type', '',
                     'account_subtype', NULL, 'amount_paise', r.net_profit) AS row
              FROM recon r
            UNION ALL
            SELECT 2, jsonb_build_object(
                     'account_id', '__noncash__', 'account_code', '',
                     'account_name', 'Add back: depreciation & non-operating items',
                     'account_type', '', 'account_subtype', NULL,
                     'amount_paise', r.depreciation - n.non_operating_pl)
              FROM recon r, nonop n WHERE (r.depreciation - n.non_operating_pl) <> 0
            UNION ALL
            SELECT 3, jsonb_build_object(
                     'account_id', '__wc__', 'account_code', '',
                     'account_name', 'Changes in working capital', 'account_type', '',
                     'account_subtype', NULL, 'amount_paise', r.working_capital)
              FROM recon r WHERE r.working_capital <> 0
        ) x
    ),
    calc AS (
        SELECT t.*, n.non_operating_pl, r.net_profit, r.depreciation, r.working_capital,
               b.opening_cash, b.closing_cash,
               ((r.net_profit - n.non_operating_pl) + r.depreciation + r.working_capital)
                 = t.operating_cash                                          AS op_reconciles,
               t.operating_cash + t.investing_cash + t.financing_cash        AS net_change
          FROM totals t, nonop n, recon r, bal b
    )
    SELECT jsonb_build_object(
        'start_date', to_char(p_start, 'YYYY-MM-DD'),
        'end_date',   to_char(p_end,   'YYYY-MM-DD'),
        'operating',  jsonb_build_object('label', 'Cash from Operating Activities',
                                         'lines', o.lines, 'total_paise', c.operating_cash),
        'investing',  jsonb_build_object('label', 'Cash from Investing Activities',
                                         'lines', i.lines, 'total_paise', c.investing_cash),
        'financing',  jsonb_build_object('label', 'Cash from Financing Activities',
                                         'lines', f.lines, 'total_paise', c.financing_cash),
        'net_change_paise',   c.net_change,
        'opening_cash_paise', c.opening_cash,
        'closing_cash_paise', c.closing_cash,
        'reconciles', (c.net_change = c.total_cash)
                  AND ((c.closing_cash - c.opening_cash) = c.net_change)
                  AND c.op_reconciles,
        'non_cash_excluded_count', c.non_cash_count,
        'operating_reconciliation', jsonb_build_object(
            'net_profit_paise',             c.net_profit,
            'non_operating_adjust_paise',   -c.non_operating_pl,
            'depreciation_addback_paise',   c.depreciation,
            'working_capital_change_paise', c.working_capital,
            'net_cash_operating_paise',     c.operating_cash,
            'ties_out',                     c.op_reconciles
        )
    )
      FROM calc c, op_lines o, inv i, fin f
    ) INTO v_out;

    RETURN v_out;
END
$fn$;

COMMENT ON FUNCTION public.cash_flow_report(uuid, uuid, date, date) IS
    'AS-3 cash flow statement (indirect), computed in the database. SECURITY '
    'DEFINER with journal_entries/journal_lines RLS restated in the body — as '
    'INVOKER (migration 277) the per-row policy cascade over journal_lines hit '
    'the statement timeout and the report fell back to Python. Returns the same '
    'JSON shape as domain/reporting/builders.cash_flow, held identical to it by '
    'tests/test_cash_flow_sql_parity_pg.py. Migrations 277, 279.';

REVOKE EXECUTE ON FUNCTION public.cash_flow_report(uuid, uuid, date, date) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.cash_flow_report(uuid, uuid, date, date) FROM anon;
GRANT EXECUTE ON FUNCTION public.cash_flow_report(uuid, uuid, date, date)
    TO authenticated, service_role;

COMMIT;
