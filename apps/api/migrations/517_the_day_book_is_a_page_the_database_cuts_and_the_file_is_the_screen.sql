-- Migration 517: the Day Book is a page the database cuts, and the file is the screen (ledger POST-A-091).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- The Day Book screen read `journal_entries` straight over PostgREST in the browser, with every entry's lines EMBEDDED, for the
-- whole period, and discarded the lines after summing a debit column out of them. That is a read proportional to the ledger to
-- answer a list of entries: measured on one client with 12,836 entries and 32,936 lines, the same shape took the Journal tab
-- 1.3 s a page before it was moved to keyset paging. And because the screen was the ONLY reader, there was no server function
-- to hang a PDF or an Excel file on: a second reader inside an export lets the file and the screen disagree, which is the one
-- thing the export design forbids (accounting-16), so the Day Book was the one core book with no printable form. Tally's Day
-- Book is the first thing an auditor asks for.
--
-- WHAT THIS DOES
--   `public.day_book_page(firm, client, start, end, newest_first, limit, offset)` returns ONE PAGE of the posted entries in a
--   window as jsonb, every entry with its debit and credit totals already summed in the database (the lines never cross the
--   wire), and, over the WHOLE window and never the page, the entry count, the debit and credit totals and the list of the
--   documents the entries came from with a count each (the screen's Source filter reads it, so its options are not just
--   whatever the loaded page happened to hold). `domain/reporting/builders.day_book` is the identical rule for mock mode, where
--   there is no database, and `tests/test_day_book_sql_parity_pg.py` runs every scenario through both and asserts they are
--   identical, so the two cannot drift. It is the shape of `account_ledger_page` (migrations 283 and 400): paged, ordered,
--   SECURITY INVOKER, so row security covers every table it reads.
--
-- WHAT A DAY BOOK LISTS, AND WHAT IT DOES NOT
--   A Day Book is "every posting in the period", so it lists POSTED entries only (`is_posted`) and never a deleted one
--   (`deleted_at IS NULL`). The screen used to list an unposted manual draft as well, with a Draft status. A draft is not a
--   posting and has moved nothing in any account, so it is not here and not in the totals; the Journal tab, which is the
--   list of what a person wrote, still shows it and is where it is posted or discarded. A reversed entry and its reversal are
--   both entries, both posted, and both listed.
--
-- THE ORDER
--   Chronological: entry date, then the moment it was recorded, then its id, so two entries on one day and one instant still
--   have one order. `p_newest_first` reverses all three, which is how the screen takes its newest page; the export always asks
--   for the chronological order. The ordering strings are compared as bytes (COLLATE "C"), because the Python twin compares
--   code points and a locale that ignores an underscore would put `sales_invoice` and `sales_credit_note` the other way round.
--   The moment is rendered in UTC before it is compared as text: `timestamptz::text` is written in the SESSION's zone, and in a zone
--   with daylight saving the text of the later of two instants in the repeated autumn hour sorts before the earlier one.
--
-- Read-only: no table or column changes. Idempotent. Reversible: 517_..._rollback.sql drops the function.

BEGIN;

CREATE OR REPLACE FUNCTION public.day_book_page(
    p_firm         uuid,
    p_client       uuid,
    p_start        date,
    p_end          date,
    p_newest_first boolean DEFAULT false,
    p_limit        integer DEFAULT 100,
    p_offset       integer DEFAULT 0
) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_limit   integer := LEAST(GREATEST(COALESCE(p_limit, 100), 1), 1000);
    v_offset  integer := GREATEST(COALESCE(p_offset, 0), 0);
    v_newest  boolean := COALESCE(p_newest_first, false);
    v_result  jsonb;
BEGIN
    WITH window_entries AS (
        -- The only scan: every posted, live entry of the client in the window, with its lines summed here and never shipped.
        SELECT je.id                                      AS entry_id,
               je.entry_date                              AS entry_date,
               je.reference_no                            AS reference_no,
               je.narration                               AS narration,
               je.entry_type                              AS entry_type,
               je.source_type                             AS source_type,
               je.source_id                               AS source_id,
               COALESCE(SUM(jl.debit_paise), 0)::bigint   AS debit_paise,
               COALESCE(SUM(jl.credit_paise), 0)::bigint  AS credit_paise,
               ROW_NUMBER() OVER (
                   ORDER BY je.entry_date,
                            COALESCE((je.created_at AT TIME ZONE 'UTC')::text, '') COLLATE "C",
                            je.id
               ) AS seq
          FROM public.journal_entries je
          LEFT JOIN public.journal_lines jl ON jl.journal_entry_id = je.id
         WHERE je.firm_id   = p_firm
           AND je.client_id = p_client
           AND je.is_posted
           AND je.deleted_at IS NULL
           AND (p_start IS NULL OR je.entry_date >= p_start)
           AND (p_end   IS NULL OR je.entry_date <= p_end)
         GROUP BY je.id
    ),
    -- Over the WHOLE window, never the page.
    totals AS (
        SELECT COALESCE(SUM(debit_paise), 0)::bigint  AS total_debit_paise,
               COALESCE(SUM(credit_paise), 0)::bigint AS total_credit_paise,
               COUNT(*)::bigint                       AS total_entries
          FROM window_entries
    ),
    sources AS (
        SELECT COALESCE(jsonb_agg(
                   jsonb_build_object('source_type', to_jsonb(s.source_type), 'entries', s.entries)
                   ORDER BY (s.source_type IS NULL), s.source_type COLLATE "C"
               ), '[]'::jsonb) AS sources
          FROM (SELECT source_type, COUNT(*)::bigint AS entries
                  FROM window_entries GROUP BY source_type) s
    ),
    page AS (
        SELECT * FROM window_entries
         ORDER BY (CASE WHEN v_newest THEN -seq ELSE seq END)
         OFFSET v_offset LIMIT v_limit
    ),
    page_json AS (
        SELECT COALESCE(jsonb_agg(
                   jsonb_build_object(
                       'entry_id',     p.entry_id,
                       'entry_date',   to_char(p.entry_date, 'YYYY-MM-DD'),
                       'reference_no', to_jsonb(p.reference_no),
                       'narration',    to_jsonb(p.narration),
                       'entry_type',   to_jsonb(p.entry_type),
                       -- Both keys are ALWAYS present and JSON null where the entry carries none, as on the ledger: an
                       -- entry posted before its path stamped a source is a real answer the screen renders as "no document".
                       'source_type',  to_jsonb(p.source_type),
                       'source_id',    to_jsonb(p.source_id),
                       'debit_paise',  p.debit_paise,
                       'credit_paise', p.credit_paise
                   )
                   ORDER BY (CASE WHEN v_newest THEN -p.seq ELSE p.seq END)
               ), '[]'::jsonb) AS entries
          FROM page p
    )
    SELECT jsonb_build_object(
               'start_date',         to_char(p_start, 'YYYY-MM-DD'),
               'end_date',           to_char(p_end, 'YYYY-MM-DD'),
               'entries',            pj.entries,
               'total_entries',      t.total_entries,
               'total_debit_paise',  t.total_debit_paise,
               'total_credit_paise', t.total_credit_paise,
               'sources',            s.sources,
               'newest_first',       v_newest,
               'limit',              v_limit,
               'offset',             v_offset
           )
      INTO v_result
      FROM totals t, sources s, page_json pj;

    RETURN v_result;
END;
$$;

COMMENT ON FUNCTION public.day_book_page(uuid, uuid, date, date, boolean, integer, integer) IS
    'One page of the Day Book: the POSTED, live entries of one client in a window, each with its debit and credit totals summed '
    'in the database, plus the whole window''s entry count, totals and the documents the entries came from. Same JSON shape as '
    'domain/reporting/builders.day_book, which is kept as the no-database twin and held identical to this by '
    'tests/test_day_book_sql_parity_pg.py. SECURITY INVOKER, read-only: row security covers both tables. Migration 517.';

REVOKE EXECUTE ON FUNCTION public.day_book_page(uuid, uuid, date, date, boolean, integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.day_book_page(uuid, uuid, date, date, boolean, integer, integer) FROM anon;
GRANT EXECUTE ON FUNCTION public.day_book_page(uuid, uuid, date, date, boolean, integer, integer)
    TO authenticated, service_role;

COMMIT;
