-- Migration 356: the Bank Reconciliation Statement, computed in the database.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (BANK-04)
-- ═══════════════════════════════════════════════════════════════════════════
-- The product printed a document titled "Bank Reconciliation Statement" whose
-- every row was a STATEMENT line. `domain/banking/reconciliation.tie_out` proves
-- one identity — opening + reconciled deposits − reconciled withdrawals ±
-- adjustments == the statement's closing balance — and
-- services/bank_reconciliation_service classifies statement lines into
-- reconciled / unreconciled / exceptions. Nothing in the module reads
-- journal_entries or journal_lines at all.
--
-- So a cheque issued and entered in the books but not yet presented at the bank
-- had no row anywhere in it, and neither did a deposit banked but not yet
-- credited. Those two ARE the substance of a BRS. Every competitor produces the
-- two-sided statement; Tally's lists "Amounts not reflected in Bank" from the
-- company books with instrument number and date. At year end the auditor's BRS
-- working paper could not be produced from this product at all.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY A SQL FUNCTION
-- ═══════════════════════════════════════════════════════════════════════════
-- CLAUDE.md's reporting rule allows exactly two shapes, and this is the second
-- one, for the same reason cash flow is (migration 277) and the bank register is
-- (353): the logic is per-row and cannot be pre-bucketed. Deciding whether a
-- book entry has been seen by the bank is an anti-join against the statement
-- lines of one account within one date window; a monthly per-account total has
-- thrown away exactly the information the question needs.
--
-- The rows are also potentially many. On an account nobody has ever reconciled,
-- EVERY book entry is an unpresented item — proportional to transaction volume,
-- which is what the rule forbids putting on the wire. So the four totals are
-- aggregated here over everything and are always exact, and the item LISTS are
-- capped at p_list_cap with `count` and `listed` saying what was dropped. A
-- truncated list that claimed to be complete would be worse than a slow one.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE ARITHMETIC, AND WHY IT IS ONE RULE AND NOT FOUR
-- ═══════════════════════════════════════════════════════════════════════════
--     bank balance = book balance
--                    + Σ (credit − debit) over BOOK entries the bank has not seen
--                    + Σ (credit − debit) over BANK lines the books have not seen
--
-- A book line's credit is money OUT of the account; a bank line's credit is
-- money IN. That is not an inconsistency to normalise away — it is what makes
-- the one expression produce "add the unpresented cheque" and "deduct the bank
-- charge". The four buckets are that sum, split for display.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THE DATE DECIDES WHAT "THE BANK HAS SEEN"
-- ═══════════════════════════════════════════════════════════════════════════
-- A statement line records posted_journal_id when the bank module posts it, so
-- the entries the bank has seen are the ones some statement line points at — but
-- only a line DATED ON OR BEFORE p_as_of. A cheque entered 28 March and
-- presented 5 April is linked permanently once April is imported; at 31 March it
-- must still be unpresented, because on 31 March the bank had not paid it.
-- Without the date test every historical BRS would change the moment the next
-- month was imported, and the working paper would stop agreeing with itself.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- SECURITY INVOKER AND THE PYTHON TWIN
-- ═══════════════════════════════════════════════════════════════════════════
-- Read-only, and RLS covers journal_entries, journal_lines, bank_statements and
-- bank_transactions, so the caller's own policies apply. `domain/banking/brs.py`
-- is the twin that mock mode and local dev run — there is no DATABASE_URL there
-- and no SQL functions — and tests/test_brs_sql_parity_pg.py runs every scenario
-- through both and asserts they are identical, which is the condition CLAUDE.md
-- puts on having two implementations at all.
--
-- p_gl_account is passed IN rather than looked up from bank_accounts: an account
-- with no linked GL account cannot have a BRS, and that refusal belongs in the
-- service where it can be named, not in a function that would have to return a
-- second kind of answer.

CREATE OR REPLACE FUNCTION public.bank_reconciling_items(
    p_firm              uuid,
    p_client            uuid,
    p_bank_account      uuid,
    p_gl_account        uuid,
    p_as_of             date,
    p_statement_balance bigint DEFAULT NULL,
    p_list_cap          int    DEFAULT 500
) RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
WITH bank AS (
    SELECT t.id,
           t.transaction_date,
           COALESCE(t.description, '')        AS particulars,
           t.reference_no,
           COALESCE(t.debit_paise, 0)         AS debit_paise,
           COALESCE(t.credit_paise, 0)        AS credit_paise,
           t.posted_journal_id
      FROM public.bank_transactions t
      JOIN public.bank_statements s ON s.id = t.statement_id
     WHERE t.firm_id = p_firm
       AND s.bank_account_id = p_bank_account
       AND t.transaction_date <= p_as_of
),
seen AS (
    SELECT DISTINCT posted_journal_id AS entry_id
      FROM bank WHERE posted_journal_id IS NOT NULL
),
book AS (
    SELECT jl.id                                   AS line_id,
           je.id                                   AS entry_id,
           je.entry_date,
           -- The line's own narration where it has one, else the entry's. The
           -- twin resolves it the same way; a report showing the entry narration
           -- on one path and the line narration on the other would pass every
           -- total test and still read differently.
           COALESCE(NULLIF(jl.narration, ''), je.narration, '') AS particulars,
           je.reference_no,
           COALESCE(jl.debit_paise, 0)             AS debit_paise,
           COALESCE(jl.credit_paise, 0)            AS credit_paise
      FROM public.journal_lines jl
      JOIN public.journal_entries je ON je.id = jl.journal_entry_id
     WHERE je.firm_id = p_firm
       AND je.client_id = p_client
       AND je.is_posted
       AND je.deleted_at IS NULL
       AND je.entry_date <= p_as_of
       AND jl.account_id = p_gl_account
),
book_balance AS (
    SELECT COALESCE(SUM(debit_paise - credit_paise), 0)::bigint AS v FROM book
),
unseen AS (
    SELECT b.* FROM book b
     WHERE NOT EXISTS (SELECT 1 FROM seen s WHERE s.entry_id = b.entry_id)
),
-- The four buckets are one query with a label, not four near-identical ones:
-- a copy-paste of an ordering or a cap is a copy-paste that drifts.
items AS (
    SELECT 'unpresented_cheques' AS bucket, line_id::text AS id, entry_date AS d,
           reference_no, particulars, credit_paise AS amount_paise, 'book' AS source
      FROM unseen WHERE credit_paise > 0
    UNION ALL
    SELECT 'deposits_in_transit', line_id::text, entry_date,
           reference_no, particulars, debit_paise, 'book'
      FROM unseen WHERE debit_paise > 0
    UNION ALL
    SELECT 'bank_credits_not_in_books', id::text, transaction_date,
           reference_no, particulars, credit_paise, 'bank'
      FROM bank WHERE posted_journal_id IS NULL AND credit_paise > 0
    UNION ALL
    SELECT 'bank_debits_not_in_books', id::text, transaction_date,
           reference_no, particulars, debit_paise, 'bank'
      FROM bank WHERE posted_journal_id IS NULL AND debit_paise > 0
),
-- (date, id) with a code-point tie-break, so the Python twin's plain string
-- compare produces the same page. The rank is what the cap applies to; the
-- totals below ignore it entirely.
ranked AS (
    SELECT i.*, row_number() OVER (PARTITION BY bucket ORDER BY d, id COLLATE "C") AS rn
      FROM items i
),
agg AS (
    SELECT bucket,
           jsonb_build_object(
             'items', COALESCE(jsonb_agg(jsonb_build_object(
                          'id', id,
                          'date', to_char(d, 'YYYY-MM-DD'),
                          'reference_no', reference_no,
                          'particulars', particulars,
                          'amount_paise', amount_paise,
                          'source', source)
                        ORDER BY d, id COLLATE "C")
                        FILTER (WHERE rn <= p_list_cap), '[]'::jsonb),
             'total_paise', COALESCE(SUM(amount_paise), 0)::bigint,
             'count', COUNT(*)::int,
             'listed', (COUNT(*) FILTER (WHERE rn <= p_list_cap))::int
           ) AS j
      FROM ranked GROUP BY bucket
),
-- An empty bucket has no group, and a missing key is not the same answer as an
-- empty one — the caller would read `undefined` where it should read zero.
buckets AS (
    SELECT n.bucket,
           COALESCE(a.j, jsonb_build_object('items', '[]'::jsonb, 'total_paise', 0,
                                            'count', 0, 'listed', 0)) AS j
      FROM (VALUES ('unpresented_cheques'), ('deposits_in_transit'),
                   ('bank_credits_not_in_books'), ('bank_debits_not_in_books')) AS n(bucket)
      LEFT JOIN agg a ON a.bucket = n.bucket
),
computed AS (
    SELECT ((SELECT v FROM book_balance)
            + (SELECT (j->>'total_paise')::bigint FROM buckets WHERE bucket = 'unpresented_cheques')
            - (SELECT (j->>'total_paise')::bigint FROM buckets WHERE bucket = 'deposits_in_transit')
            + (SELECT (j->>'total_paise')::bigint FROM buckets WHERE bucket = 'bank_credits_not_in_books')
            - (SELECT (j->>'total_paise')::bigint FROM buckets WHERE bucket = 'bank_debits_not_in_books')
           )::bigint AS v
)
SELECT jsonb_build_object(
    'as_of', to_char(p_as_of, 'YYYY-MM-DD'),
    'book_balance_paise', (SELECT v FROM book_balance),
    'unpresented_cheques',       (SELECT j FROM buckets WHERE bucket = 'unpresented_cheques'),
    'deposits_in_transit',       (SELECT j FROM buckets WHERE bucket = 'deposits_in_transit'),
    'bank_credits_not_in_books', (SELECT j FROM buckets WHERE bucket = 'bank_credits_not_in_books'),
    'bank_debits_not_in_books',  (SELECT j FROM buckets WHERE bucket = 'bank_debits_not_in_books'),
    'computed_bank_balance_paise', (SELECT v FROM computed),
    'statement_balance_paise', p_statement_balance,
    'difference_paise',
        CASE WHEN p_statement_balance IS NULL THEN NULL
             ELSE p_statement_balance - (SELECT v FROM computed) END,
    'agrees',
        CASE WHEN p_statement_balance IS NULL THEN NULL
             ELSE (p_statement_balance - (SELECT v FROM computed)) = 0 END,
    'gap',
        CASE WHEN p_statement_balance IS NULL THEN
            'The balance the bank states at this date is not known — the '
            'statement carries no running balance and none was typed in — so '
            'this statement reconciles the books to a figure nothing has '
            'confirmed.'
        ELSE NULL END
);
$$;

COMMENT ON FUNCTION public.bank_reconciling_items(uuid, uuid, uuid, uuid, date, bigint, int) IS
    'The two-sided Bank Reconciliation Statement for one bank account as at one '
    'date: book balance, unpresented cheques, deposits in transit, and the bank''s '
    'own entries not yet in the books. Totals are exact over every row; item lists '
    'are capped at p_list_cap with count/listed saying what was dropped. '
    'SECURITY INVOKER — read-only, RLS covers all four tables. Python twin: '
    'domain/banking/brs.py, held identical by tests/test_brs_sql_parity_pg.py.';
