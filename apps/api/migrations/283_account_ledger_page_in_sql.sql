-- ═══════════════════════════════════════════════════════════════════════════
-- 283 — public.account_ledger_page: ONE page of a per-account general ledger,
--       with the running balance computed where the rows already are.
--
-- WHAT WAS WRONG
--     The drill-down fetched EVERY posted entry touching the account and shipped
--     all of them to Singapore, where Python walked them to build the running
--     balance and then serialised the lot back to the browser. Measured on the
--     live database for one client's Trade Receivables:
--
--         rows returned                          5,659
--         Postgres execution time                44 ms
--
--     The database was never the problem. The cost was moving 5,659 rows across
--     two hops and rendering them into a sortable table, to answer a question
--     the reader satisfies with about twenty of them.
--
--     This is CLAUDE.md's reporting rule, and the ledger is the case the rule's
--     two prescribed shapes do NOT cover. A ledger cannot be pre-aggregated:
--     its answer genuinely is one row per transaction, so account_period_balances
--     (right for Trial Balance, P&L, Balance Sheet) cannot serve it. What it can
--     be is PAGED — which needs the running balance to survive paging, and that
--     is what a window function is for.
--
-- HOW THE RUNNING BALANCE SURVIVES PAGING
--     A page cannot compute its own running balance: row 101's balance depends
--     on rows 1..100. So the window runs over the account's WHOLE history in
--     order, and only then is the page sliced out of it. Each row therefore
--     carries the same running_balance_paise it would have had unpaged, and the
--     opening balance, the closing balance and the period totals are all over
--     the FULL window rather than the page — a footer that described only the
--     visible rows would be a different (and wrong) document.
--
-- NOT A SECOND IMPLEMENTATION
--     Same JSON shape as domain/reporting/builders.ledger, which stays as the
--     no-database fallback for mock mode and local dev, and is held identical to
--     this by tests/test_account_ledger_sql_parity_pg.py — every scenario
--     through both, asserted equal. Drift fails CI rather than reaching a CA.
--
--     The port is literal, including the parts that look arbitrary:
--       * order is (entry_date, created_at, id) — deterministic for same-day and
--         backdated entries, matching builders' sort key exactly. NULL
--         created_at sorts as '' in Python, so COALESCE to '' here too.
--       * opening is the cumulative debit − credit STRICTLY BEFORE p_start.
--       * a line after p_end is excluded from the view but is NOT part of
--         opening either — builders `continue`s past it.
--       * is_debit on every row and on the balances is `>= 0`, not `> 0`: a zero
--         balance reads as Dr, which is what builders does.
--       * the txn_* memo fields appear ONLY on genuinely foreign lines
--         (model.JournalLine.is_foreign: a non-INR currency AND a foreign amount
--         present), so an INR-only ledger is byte-for-byte what it was.
--       * has_foreign_lines is emitted only when true, and is computed over the
--         WHOLE window, not the page — otherwise the currency column would
--         appear and vanish as the reader pages.
--
-- SECURITY INVOKER, like 277 and for the same reason: this only reads, and
-- journal_entries, journal_lines and chart_of_accounts all carry RLS. A caller
-- with a user JWT stays inside their own firm; service_role bypasses RLS as it
-- always has. Nothing here needs the owner's rights, so it does not take them.
--
-- No table or column changes. Idempotent, and safe to re-run.
-- ═══════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE OR REPLACE FUNCTION public.account_ledger_page(
    p_firm    uuid,
    p_client  uuid,
    p_account uuid,
    p_start   date,
    p_end     date,
    p_limit   integer DEFAULT 100,
    p_offset  integer DEFAULT 0
) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_limit   integer := LEAST(GREATEST(COALESCE(p_limit, 100), 1), 1000);
    v_offset  integer := GREATEST(COALESCE(p_offset, 0), 0);
    v_account record;
    v_result  jsonb;
BEGIN
    SELECT id, account_code, account_name, account_type
      INTO v_account
      FROM public.chart_of_accounts
     WHERE id = p_account
     LIMIT 1;

    WITH hits AS (
        -- Every posted line for this account, in the ledger's canonical order.
        -- This is the only scan, and it is the one the 44 ms measurement covers.
        SELECT je.id           AS entry_id,
               je.entry_date   AS entry_date,
               je.reference_no AS reference_no,
               je.narration    AS narration,
               jl.debit_paise  AS debit_paise,
               jl.credit_paise AS credit_paise,
               jl.txn_currency AS txn_currency,
               jl.txn_debit        AS txn_debit,
               jl.txn_credit       AS txn_credit,
               jl.exchange_rate    AS exchange_rate,
               ROW_NUMBER() OVER (
                   ORDER BY je.entry_date, COALESCE(je.created_at::text, ''), je.id
               ) AS seq,
               SUM(jl.debit_paise - jl.credit_paise) OVER (
                   ORDER BY je.entry_date, COALESCE(je.created_at::text, ''), je.id
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
               ) AS running_balance_paise
          FROM public.journal_entries je
          JOIN public.journal_lines  jl ON jl.journal_entry_id = je.id
         WHERE je.firm_id   = p_firm
           AND je.client_id = p_client
           AND je.is_posted
           AND je.deleted_at IS NULL
           AND jl.account_id = p_account
    ),
    classified AS (
        SELECT h.*,
               -- builders: strictly before start → opening; after end → dropped;
               -- otherwise in the window.
               CASE
                   WHEN p_start IS NOT NULL AND h.entry_date <  p_start THEN 'before'
                   WHEN p_end   IS NOT NULL AND h.entry_date >  p_end   THEN 'after'
                   ELSE 'in'
               END AS bucket,
               -- model.JournalLine.is_foreign, transcribed.
               (COALESCE(UPPER(TRIM(h.txn_currency)), '') <> ''
                AND UPPER(TRIM(h.txn_currency)) <> 'INR'
                AND (h.txn_debit IS NOT NULL OR h.txn_credit IS NOT NULL)
               ) AS is_foreign
          FROM hits h
    ),
    window_rows AS (
        SELECT * FROM classified WHERE bucket = 'in'
    ),
    -- Over the WHOLE window, never the page.
    totals AS (
        SELECT COALESCE(SUM(debit_paise), 0)  AS total_debit_paise,
               COALESCE(SUM(credit_paise), 0) AS total_credit_paise,
               COUNT(*)                       AS total_lines,
               BOOL_OR(is_foreign)            AS has_foreign
          FROM window_rows
    ),
    opening AS (
        SELECT COALESCE(SUM(debit_paise - credit_paise), 0) AS opening_balance_paise
          FROM classified WHERE bucket = 'before'
    ),
    -- The last row IN the window carries the closing balance. With no rows in
    -- the window the closing balance is the opening one — builders' `running`
    -- starts at `opening` and is never advanced.
    closing AS (
        SELECT COALESCE(
                 (SELECT running_balance_paise FROM window_rows
                   ORDER BY seq DESC LIMIT 1),
                 (SELECT opening_balance_paise FROM opening)
               ) AS closing_balance_paise
    ),
    page AS (
        SELECT * FROM window_rows ORDER BY seq OFFSET v_offset LIMIT v_limit
    ),
    page_json AS (
        SELECT COALESCE(jsonb_agg(
                   jsonb_build_object(
                       'entry_id',              p.entry_id,
                       'entry_date',            to_char(p.entry_date, 'YYYY-MM-DD'),
                       'reference_no',          p.reference_no,
                       'narration',             p.narration,
                       'debit_paise',           p.debit_paise,
                       'credit_paise',          p.credit_paise,
                       'running_balance_paise', p.running_balance_paise,
                       'is_debit',              (p.running_balance_paise >= 0)
                   )
                   -- Foreign memo fields, only on genuinely foreign lines, so an
                   -- INR ledger is unchanged. exchange_rate as an exact string,
                   -- matching builders' str(Decimal).
                   || CASE WHEN p.is_foreign THEN
                        jsonb_build_object(
                            'txn_currency',     UPPER(TRIM(p.txn_currency)),
                            'txn_debit_minor',  COALESCE(p.txn_debit, 0),
                            'txn_credit_minor', COALESCE(p.txn_credit, 0)
                        )
                        || CASE WHEN p.exchange_rate IS NOT NULL
                                THEN jsonb_build_object('exchange_rate', p.exchange_rate::text)
                                ELSE '{}'::jsonb END
                      ELSE '{}'::jsonb END
                   ORDER BY p.seq
               ), '[]'::jsonb) AS lines
          FROM page p
    )
    SELECT jsonb_build_object(
               'account_id',            p_account,
               'account_code',          COALESCE(v_account.account_code, ''),
               'account_name',          COALESCE(v_account.account_name, ''),
               'account_type',          COALESCE(v_account.account_type, ''),
               'start_date',            to_char(p_start, 'YYYY-MM-DD'),
               'end_date',              to_char(p_end, 'YYYY-MM-DD'),
               'opening_balance_paise', o.opening_balance_paise,
               'opening_is_debit',      (o.opening_balance_paise >= 0),
               'closing_balance_paise', c.closing_balance_paise,
               'closing_is_debit',      (c.closing_balance_paise >= 0),
               'total_debit_paise',     t.total_debit_paise,
               'total_credit_paise',    t.total_credit_paise,
               'lines',                 pj.lines,
               -- Paging, which builders has no notion of: it always returned
               -- everything. total_lines is what the pager counts against.
               'total_lines',           t.total_lines,
               'limit',                 v_limit,
               'offset',                v_offset
           )
           || CASE WHEN COALESCE(t.has_foreign, false)
                   THEN jsonb_build_object('has_foreign_lines', true)
                   ELSE '{}'::jsonb END
      INTO v_result
      FROM totals t, opening o, closing c, page_json pj;

    RETURN v_result;
END;
$$;

COMMENT ON FUNCTION public.account_ledger_page(uuid, uuid, uuid, date, date, integer, integer) IS
    'One page of a per-account general ledger, with the running balance computed '
    'over the account''s whole history and only then sliced — so a paged row '
    'carries the same balance it would unpaged. Same JSON shape as '
    'domain/reporting/builders.ledger plus total_lines/limit/offset; that builder '
    'is kept only as the no-database fallback and held identical to this by '
    'tests/test_account_ledger_sql_parity_pg.py. Replaces a 5,659-row fetch with '
    'one page. SECURITY INVOKER — read-only, and RLS covers all three tables. '
    'Migration 283.';

REVOKE EXECUTE ON FUNCTION public.account_ledger_page(uuid, uuid, uuid, date, date, integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.account_ledger_page(uuid, uuid, uuid, date, date, integer, integer) FROM anon;
GRANT EXECUTE ON FUNCTION public.account_ledger_page(uuid, uuid, uuid, date, date, integer, integer)
    TO authenticated, service_role;

COMMIT;
