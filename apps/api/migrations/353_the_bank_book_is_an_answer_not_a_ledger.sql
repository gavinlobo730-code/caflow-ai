-- Migration 353: the Bank Book's answer, computed in the database.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- CLAUDE.md states the rule: "No report may fetch rows proportional to
-- transaction volume. What crosses the wire must be proportional to the size of
-- the ANSWER, not the size of the ledger." The Bank Book broke it in both
-- directions at once.
--
--   * services/bank_register_service._txns PAGED EVERY TRANSACTION on the
--     account across the wire. apps/api runs on Render in Singapore and
--     Postgres is in Mumbai, so on a 12,836-line account that is thirteen
--     cross-region round trips to produce a 200-row page.
--
--   * The running balance, the summary and the divergence were then computed in
--     Python over all of them.
--
--   * And one step was quadratic. `min(filtered, key=all_lines.index)` calls
--     list.index once per candidate, each a linear scan:
--
--         earliest = min(filtered, key=all_lines.index)
--         idx = all_lines.index(earliest)
--
--     Measured on 12,836 rows in this repository's own harness: 22.8 seconds of
--     CPU inside one request, against 0.069s to build the whole register and
--     0.004s to filter it. The audit's production measurement was 29.2s. It is
--     also, on inspection, entirely unnecessary — `filtered` is built by a list
--     comprehension over `all_lines`, so it is already in that order and
--     `filtered[0]` is the same row. That is fixed in the Python twin too, in
--     the same commit, because mock mode and local dev run it.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY A SQL FUNCTION AND NOT A PRE-AGGREGATED TABLE
-- ═══════════════════════════════════════════════════════════════════════════
-- CLAUDE.md offers exactly two shapes, and a register is the second one for the
-- same reason cash flow is: the logic is per-row and cannot be pre-bucketed. A
-- running balance is an ordered scan whose every value depends on the row
-- before it, and the filter, the sort and the page all move with the request.
-- `public.cash_flow_report` (migration 277) and `public.schedule_iii_ageing`
-- (303) are the worked examples and this follows them: one call, finished rows,
-- and a Python twin kept only because mock mode has no DATABASE_URL — pinned by
-- tests/test_bank_register_sql_parity_pg.py, exactly as
-- tests/test_cash_flow_sql_parity_pg.py pins that one.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- FOUR THINGS THE TWO SIDES MUST AGREE ON, AND HOW
-- ═══════════════════════════════════════════════════════════════════════════
-- 1. THE REGISTER ORDER IS (date, created_at, id) AND THE DISPLAY ORDER IS NOT.
--    domain/banking/register.sort_key uses all three so the order is total —
--    anything less lets same-date rows reorder between requests and every
--    balance below them changes with it. But the service's _sort, which decides
--    what the screen shows, sorts on (date, id) and DROPS created_at. The two
--    are different on purpose and the function reproduces both.
--
-- 2. PYTHON COMPARES STRINGS BY CODE POINT AND A DATABASE COLLATION DOES NOT.
--    Sorting by description under en_US.UTF-8 ignores case and punctuation in
--    ways `str.lower() <` does not, so every text sort key here is COLLATE "C".
--
-- 3. A ROW DATED BEFORE THE OPENING BALANCE IS ALREADY INSIDE IT.
--    bank_accounts.opening_balance_paise is a balance AS AT
--    opening_balance_date. Adding an earlier row to the running total
--    double-counts it, silently, by exactly its own amount. Those rows are
--    excluded from the accumulation, kept in the list, and counted separately.
--
-- 4. THE SEARCH HAYSTACK IS JOINED WITH A LITERAL SPACE PER FIELD.
--    The Python twin does " ".join(str(x or "") for x in (...)), so a NULL
--    becomes '' and two spaces survive. concat_ws SKIPS a null and collapses
--    them, so a needle containing a double space would match in SQL and not in
--    Python. Written out with || and COALESCE for that reason.
--
-- SECURITY INVOKER, not DEFINER: this only reads, and all four tables carry
-- RLS. Running as the invoker keeps a caller with a user JWT inside their own
-- firm; service_role bypasses RLS as it always has, which is why every CTE
-- also filters on p_firm explicitly. Nothing here needs the owner's rights, so
-- it does not take them.
--
-- The CLIENT check stays in Python. The service resolves the account row first
-- for the 404-vs-422 distinction ("Bank account not found for this firm"
-- against "Bank account does not belong to this client"), which is one indexed
-- row and a message a function cannot carry back as an HTTP status.
--
-- No table or column changes. Idempotent, and safe to re-run.

BEGIN;

CREATE OR REPLACE FUNCTION public.bank_register(
    p_firm       uuid,
    p_account    uuid,
    p_date_from  date    DEFAULT NULL,
    p_date_to    date    DEFAULT NULL,
    p_status     text    DEFAULT 'all',
    p_q          text    DEFAULT NULL,
    p_sort       text    DEFAULT 'date',
    p_desc       boolean DEFAULT false,
    p_limit      integer DEFAULT 200,
    p_offset     integer DEFAULT 0
) RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
WITH acct AS (
    SELECT COALESCE(b.opening_balance_paise, 0)::bigint AS opening_paise,
           b.opening_balance_date                       AS opening_date
      FROM public.bank_accounts b
     WHERE b.id = p_account AND b.firm_id = p_firm
),
txn AS (
    SELECT t.id, t.transaction_date, t.created_at, t.description, t.reference_no,
           COALESCE(t.debit_paise, 0)::bigint  AS debit_paise,
           COALESCE(t.credit_paise, 0)::bigint AS credit_paise,
           t.balance_paise                     AS stated_paise,
           t.category, t.match_status, t.posted_journal_id, t.reconciliation_id,
           COALESCE(t.needs_review, false)     AS needs_review
      FROM public.bank_transactions t
      JOIN public.bank_statements s ON s.id = t.statement_id
     WHERE t.firm_id = p_firm
       AND s.firm_id = p_firm
       AND s.bank_account_id = p_account
),
ordered AS (
    -- domain/banking/register.sort_key: (date, created_at, id). All three, so
    -- the order is total; anything less leaves same-date rows free to reorder
    -- between requests and every balance below them changes with it.
    SELECT t.*,
           ((SELECT a.opening_date FROM acct a) IS NOT NULL
            AND t.transaction_date < (SELECT a.opening_date FROM acct a)) AS precedes_opening,
           row_number() OVER (ORDER BY t.transaction_date, t.created_at, t.id) AS seq
      FROM txn t
),
running AS (
    SELECT o.*,
           (SELECT a.opening_paise FROM acct a)
             + SUM(CASE WHEN o.precedes_opening THEN 0
                        ELSE o.credit_paise - o.debit_paise END)
               OVER (ORDER BY o.seq ROWS UNBOUNDED PRECEDING) AS balance_paise
      FROM ordered o
),
lined AS (
    SELECT r.seq,
           r.id::text                    AS transaction_id,
           r.transaction_date,
           COALESCE(r.description, '')   AS description,
           r.reference_no,
           r.debit_paise, r.credit_paise,
           (r.credit_paise - r.debit_paise) AS amount_paise,
           r.balance_paise,
           CASE WHEN r.reconciliation_id IS NULL THEN ''
                WHEN rc.status = 'completed' THEN 'R'
                ELSE 'C' END             AS cleared,
           r.category, r.match_status,
           r.posted_journal_id::text     AS posted_journal_id,
           r.reconciliation_id::text     AS reconciliation_id,
           r.stated_paise                AS statement_balance_paise,
           CASE WHEN r.stated_paise IS NOT NULL AND NOT r.precedes_opening
                THEN r.stated_paise - r.balance_paise END AS balance_delta_paise,
           r.precedes_opening,
           r.needs_review
      FROM running r
      LEFT JOIN public.bank_reconciliations rc
             ON rc.id = r.reconciliation_id AND rc.firm_id = p_firm
),
filtered AS (
    SELECT l.* FROM lined l
     WHERE (p_date_from IS NULL OR l.transaction_date >= p_date_from)
       AND (p_date_to   IS NULL OR l.transaction_date <= p_date_to)
       AND (p_status = 'all'
         OR (p_status = 'uncleared'    AND l.cleared = '')
         OR (p_status = 'pending'      AND l.cleared = 'C')
         OR (p_status = 'reconciled'   AND l.cleared = 'R')
         OR (p_status = 'unposted'     AND l.posted_journal_id IS NULL)
         OR (p_status = 'needs_review' AND l.needs_review))
       -- The haystack is joined with a literal space per field and NULLs become
       -- '', exactly as the Python twin does it. concat_ws would SKIP a null and
       -- collapse two spaces into one, so a needle containing a double space
       -- would match here and not there.
       AND (p_q IS NULL OR btrim(p_q) = ''
            OR position(lower(btrim(p_q)) in
                        lower(COALESCE(l.description,'') || ' ' ||
                              COALESCE(l.reference_no,'') || ' ' ||
                              COALESCE(l.category,''))) > 0)
),
paged AS (
    SELECT f.* FROM filtered f
     ORDER BY
       -- The DISPLAY order, which is NOT the register order: the default sorts
       -- on (date, id) and drops created_at, because that is what the Python
       -- twin's _sort does. Each key appears twice, once per direction, with
       -- the unused copy NULL for every row so it ties and has no effect —
       -- ASC/DESC cannot be chosen by a parameter inside one expression.
       -- COLLATE "C" on the text keys because Python compares strings by code
       -- point and a database collation does not.
       CASE WHEN NOT p_desc THEN
         CASE p_sort WHEN 'amount'  THEN f.amount_paise
                     WHEN 'balance' THEN f.balance_paise END END ASC,
       CASE WHEN p_desc THEN
         CASE p_sort WHEN 'amount'  THEN f.amount_paise
                     WHEN 'balance' THEN f.balance_paise END END DESC,
       CASE WHEN NOT p_desc THEN
         CASE p_sort WHEN 'description' THEN lower(f.description)
                     WHEN 'cleared' THEN CASE f.cleared WHEN '' THEN '0'
                                                        WHEN 'C' THEN '1'
                                                        ELSE '2' END END END COLLATE "C" ASC,
       CASE WHEN p_desc THEN
         CASE p_sort WHEN 'description' THEN lower(f.description)
                     WHEN 'cleared' THEN CASE f.cleared WHEN '' THEN '0'
                                                        WHEN 'C' THEN '1'
                                                        ELSE '2' END END END COLLATE "C" DESC,
       CASE WHEN NOT p_desc THEN f.transaction_date END ASC,
       CASE WHEN p_desc     THEN f.transaction_date END DESC,
       CASE WHEN NOT p_desc THEN f.transaction_id END COLLATE "C" ASC,
       CASE WHEN p_desc     THEN f.transaction_id END COLLATE "C" DESC
     LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 200), 1000))
    OFFSET GREATEST(0, COALESCE(p_offset, 0))
)
SELECT jsonb_build_object(
  'lines', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'transaction_id', p.transaction_id,
        'transaction_date', to_char(p.transaction_date, 'YYYY-MM-DD'),
        'description', p.description,
        'reference_no', p.reference_no,
        'debit_paise', p.debit_paise,
        'credit_paise', p.credit_paise,
        'amount_paise', p.amount_paise,
        'balance_paise', p.balance_paise,
        'cleared', p.cleared,
        'category', p.category,
        'match_status', p.match_status,
        'posted_journal_id', p.posted_journal_id,
        'reconciliation_id', p.reconciliation_id,
        'statement_balance_paise', p.statement_balance_paise,
        'balance_delta_paise', p.balance_delta_paise,
        'precedes_opening', p.precedes_opening)) FROM paged p), '[]'::jsonb),
  'summary', (SELECT jsonb_build_object(
        'opening_balance_paise', (SELECT a.opening_paise FROM acct a),
        'deposits_paise',    COALESCE(SUM(l.credit_paise) FILTER (WHERE NOT l.precedes_opening), 0),
        'withdrawals_paise', COALESCE(SUM(l.debit_paise)  FILTER (WHERE NOT l.precedes_opening), 0),
        'closing_balance_paise', COALESCE(
            (SELECT x.balance_paise FROM lined x ORDER BY x.seq DESC LIMIT 1),
            (SELECT a.opening_paise FROM acct a)),
        'line_count', COUNT(*),
        'uncleared_count',  COUNT(*) FILTER (WHERE l.cleared = ''),
        'pending_count',    COUNT(*) FILTER (WHERE l.cleared = 'C'),
        'reconciled_count', COUNT(*) FILTER (WHERE l.cleared = 'R'),
        'unposted_count',   COUNT(*) FILTER (WHERE l.posted_journal_id IS NULL),
        'precedes_opening_count', COUNT(*) FILTER (WHERE l.precedes_opening))
      FROM lined l),
  -- Only the FIRST divergence is diagnostic: once a line is missing every
  -- balance below it is wrong by the same amount, so listing them all reports
  -- one fault a hundred times and buries where it started.
  'divergence', (SELECT jsonb_build_object(
        'index', (d.seq - 1)::int,
        'transaction_id', d.transaction_id,
        'transaction_date', to_char(d.transaction_date, 'YYYY-MM-DD'),
        'description', d.description,
        'computed_balance_paise', d.balance_paise,
        'statement_balance_paise', d.statement_balance_paise,
        'delta_paise', d.balance_delta_paise)
      FROM lined d
     WHERE d.balance_delta_paise IS NOT NULL AND d.balance_delta_paise <> 0
     ORDER BY d.seq LIMIT 1),
  -- The balance immediately BEFORE the first row of this view, in REGISTER
  -- order. Without it a filtered register does not add up on screen: the first
  -- visible balance would look like it came from nowhere.
  'view_opening_balance_paise', COALESCE(
     (SELECT prev.balance_paise FROM lined prev
       WHERE prev.seq = (SELECT MIN(f.seq) FROM filtered f) - 1),
     (SELECT a.opening_paise FROM acct a)),
  'filtered_count', (SELECT COUNT(*) FROM filtered),
  'total_count',    (SELECT COUNT(*) FROM lined)
);
$$;

COMMENT ON FUNCTION public.bank_register(uuid, uuid, date, date, text, text, text, boolean, integer, integer) IS
  'The Bank Book for one account: a page of register lines with the running '
  'balance, plus the summary, the first divergence from the bank''s own '
  'balance column and the counts — all over the whole account, in one call. '
  'Replaces paging every transaction to Python (CLAUDE.md, Reporting '
  'performance). SECURITY INVOKER — read-only, and RLS covers all four tables. '
  'domain/banking/register.py is the mock-mode twin; the two are pinned by '
  'tests/test_bank_register_sql_parity_pg.py. Migration 353.';

GRANT EXECUTE ON FUNCTION public.bank_register(uuid, uuid, date, date, text, text, text, boolean, integer, integer)
  TO authenticated, service_role;

COMMIT;
