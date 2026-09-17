-- ═══════════════════════════════════════════════════════════════════════════
-- 400 — a ledger row names the document behind it (ACC-22).
--
-- WHAT WAS WRONG
--     `journal_entries.source_type` / `source_id` have existed since migration
--     104, and since commit 99ac94b5 all twenty-six posting paths fill them in.
--     The per-account ledger did not READ them: neither this function nor its
--     Python twin `domain/reporting/builders.ledger` selected either column, so
--     a CA reading "Trade Receivables 1,18,000 Dr" had the narration, the
--     reference and nothing to open. 99ac94b5's own commit message says so —
--     "This commit is the missing premise; the drill-through itself is a
--     separate change." This is that change's database half.
--
-- WHAT THIS DOES
--     Adds the two columns to the `hits` scan and to each row of the page JSON.
--     Nothing else moves: the window, the ordering, the opening/closing
--     arithmetic, the foreign memo and the paging are byte-for-byte migration
--     283's, and every existing key keeps its value. The two new keys are
--     ALWAYS present and are JSON `null` where the entry carries none — an
--     entry posted before its path stamped a source is a real answer the screen
--     renders as "no document", and an absent key would be indistinguishable
--     from a link the browser failed to build.
--
-- DERIVED FROM 283, WHICH IS STILL THE LAST DEFINER
--     `grep -ln "FUNCTION.*account_ledger_page" migrations/*.sql | sort | tail -1`
--     answers `283_account_ledger_page_in_sql.sql`, and this body is that file's
--     verbatim with the three additions above. CREATE OR REPLACE replaces the
--     WHOLE definition, so anything 283 carried and this dropped would revert
--     silently — which is what CLAUDE.md records migration 384 doing twice.
--
-- THE PYTHON TWIN MOVES IN THE SAME COMMIT.
--     tests/test_account_ledger_sql_parity_pg.py runs every scenario through
--     both and asserts they are identical, so this and builders.ledger cannot
--     drift apart.
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
               je.source_type  AS source_type,
               je.source_id    AS source_id,
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
                       'is_debit',              (p.running_balance_paise >= 0),
                       -- to_jsonb, not the bare value: jsonb_build_object drops
                       -- nothing, but a uuid needs casting and NULL must arrive
                       -- as JSON null rather than as an absent key — builders
                       -- emits both keys unconditionally and the parity test
                       -- compares the dicts.
                       'source_type',           to_jsonb(p.source_type),
                       'source_id',             to_jsonb(p.source_id)
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
    'Migration 283, redefined by 400 to carry source_type/source_id.';

REVOKE EXECUTE ON FUNCTION public.account_ledger_page(uuid, uuid, uuid, date, date, integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.account_ledger_page(uuid, uuid, uuid, date, date, integer, integer) FROM anon;
GRANT EXECUTE ON FUNCTION public.account_ledger_page(uuid, uuid, uuid, date, date, integer, integer)
    TO authenticated, service_role;

COMMIT;
