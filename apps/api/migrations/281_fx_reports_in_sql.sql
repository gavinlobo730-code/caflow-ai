-- Migration 281: the two FX reads that cannot be a query filter, moved into SQL.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THESE TWO AND NOT THE OTHERS
-- ═══════════════════════════════════════════════════════════════════════════
-- CLAUDE.md's reporting rule offers a report exactly two shapes: a pre-aggregated
-- table maintained by triggers, or a SQL function that aggregates server-side.
-- Fetching raw rows and computing in Python is not on the list.
--
-- Most of what fx_reporting_service did wrong was neither — it was a filter left
-- in Python that belonged in the query, fixed by migration 280 and by the change
-- that shipped with it. What is left here is the part that genuinely cannot be a
-- filter, because the answer is an AGGREGATE the wire would otherwise carry the
-- inputs for:
--
--   1. _account_foreign_and_base — Σ(txn_debit − txn_credit) and
--      Σ(debit − credit) over one account's posted lines. It fetched EVERY
--      posted journal_entry for the client (12,838 on the live client) to build
--      a set of ids, then EVERY journal_line for the account, and reconciled the
--      two in Python. Once per foreign bank account. This is the cash flow
--      statement's disease verbatim (migration 277) and has the same cure.
--
--   2. _entry_dates — {entry_id: entry_date} for every posted entry, built so an
--      FX adjustment could be reported in its SETTLEMENT period rather than by
--      the audit row's insert timestamp. 12,838 rows to date perhaps a dozen
--      adjustments, and realized_fx and exchange_rate_audit each built it, so a
--      CA opening both paid for it twice.
--
-- The passbook (account_period_balances) cannot serve either. It holds base
-- paise only — no txn_ amounts and no currency split — so the foreign side of a
-- bank balance is not in it, and an adjustment's settlement date is not a
-- monthly per-account total.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- SECURITY DEFINER, WITH THE RLS RESTATED
-- ═══════════════════════════════════════════════════════════════════════════
-- The pattern from migrations 271, 275, 276 and 279 — and 279 is why it is not
-- optional. cash_flow_report shipped as SECURITY INVOKER on the reasoning that a
-- read-only function has no business holding owner rights; under RLS the
-- per-row policy cascade over journal_lines hit the statement timeout and the
-- report came back SLOWER than the Python it replaced. fx_foreign_bank_balances
-- reads the same two tables through the same policies, so it would fail the same
-- way.
--
-- The checks below are transcribed from post_journal_atomic — same predicates,
-- same SQLSTATE, same order — so isolation is exactly what the policies would
-- have enforced, checked once per call instead of once per row.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- PARITY
-- ═══════════════════════════════════════════════════════════════════════════
-- The Python implementations survive: mock mode and local dev have no
-- DATABASE_URL and no SQL functions. Two implementations drift, so they are
-- pinned by tests/test_fx_reports_sql_parity_pg.py, which runs every scenario
-- through both and asserts they are identical — the same arrangement
-- test_cash_flow_sql_parity_pg.py holds cash_flow_report to.
--
-- Two parity details worth naming, both transcribed rather than improved:
--   * every money term is COALESCEd separately, because Python did
--     `int(x or 0) - int(y or 0)` and SQL's NULL arithmetic would otherwise drop
--     the whole line from the sum rather than treat the missing side as zero;
--   * rates are emitted as JSON numbers, not text, because that is what
--     PostgREST returns for a numeric and the caller applies str() to it. This
--     was found BY the parity test rather than reasoned out in advance: the
--     first run disagreed on "84.0" versus "84.0000".
--
-- No table or column changes. Idempotent, and safe to re-run.

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Foreign bank balances
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.fx_foreign_bank_balances(
    p_firm   uuid,
    p_client uuid
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
            RAISE EXCEPTION 'fx_foreign_bank_balances: caller has no user record in this database'
                USING ERRCODE = '42501';
        END IF;

        IF p_firm IS DISTINCT FROM v_my_firm THEN
            RAISE EXCEPTION 'fx_foreign_bank_balances: firm % is not the caller''s firm', p_firm
                USING ERRCODE = '42501';
        END IF;

        IF NOT public.can_access_client(p_client::text) THEN
            RAISE EXCEPTION 'fx_foreign_bank_balances: client % is not assigned to the caller', p_client
                USING ERRCODE = '42501';
        END IF;

        v_internal := public.my_internal_client_id();
        IF v_internal IS NOT NULL
           AND p_client = v_internal
           AND COALESCE(public.get_my_role(), '') <> 'Partner' THEN
            RAISE EXCEPTION 'fx_foreign_bank_balances: only a Partner may read the firm''s internal client'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    SELECT COALESCE(jsonb_agg(r ORDER BY r->>'name', r->>'id'), '[]'::jsonb)
      INTO v_out
      FROM (
        SELECT jsonb_build_object(
                   'id',                    b.id,
                   'name',                  b.bank_name,
                   'account_no',            b.account_no,
                   'currency',              upper(b.currency),
                   'foreign_balance_minor', s.foreign_minor,
                   'base_balance_paise',    s.base_paise
               ) AS r
          FROM public.bank_accounts b
          -- LATERAL, not a LEFT JOIN onto journal_lines: the entry-level filter
          -- (posted, not deleted, this firm and client) has to constrain which
          -- LINES are summed. Hung off a LEFT JOIN it would instead let unposted
          -- lines through with a NULL entry and quietly inflate the balance.
          CROSS JOIN LATERAL (
              SELECT COALESCE(SUM(COALESCE(jl.txn_debit, 0)
                                - COALESCE(jl.txn_credit, 0)), 0)::bigint AS foreign_minor,
                     COALESCE(SUM(COALESCE(jl.debit_paise, 0)
                                - COALESCE(jl.credit_paise, 0)), 0)::bigint AS base_paise
                FROM public.journal_lines jl
                JOIN public.journal_entries je ON je.id = jl.journal_entry_id
               WHERE jl.account_id = b.coa_account_id
                 AND je.firm_id    = p_firm
                 AND je.client_id  = p_client
                 AND je.is_posted
                 AND je.deleted_at IS NULL
                 -- Only lines actually denominated in the account's currency.
                 -- A base-INR revaluation overlay is posted back onto the same
                 -- account stamped txn_currency='INR'; counting it would make the
                 -- reported foreign holding drift from the booked value.
                 AND upper(jl.txn_currency) = upper(b.currency)
          ) s
         WHERE b.firm_id   = p_firm
           AND b.client_id = p_client
           AND upper(b.currency) <> 'INR'
           AND b.coa_account_id IS NOT NULL
           -- An account with nothing booked in it is not an open balance.
           AND NOT (s.foreign_minor = 0 AND s.base_paise = 0)
      ) q;

    RETURN v_out;
END
$fn$;

COMMENT ON FUNCTION public.fx_foreign_bank_balances(uuid, uuid) IS
    'Open FOREIGN bank balances for one client: per account, the sum of its '
    'posted journal lines denominated in that account''s currency, foreign minor '
    'units and base paise. Replaces a per-account Python reconciliation that '
    'fetched every posted entry and every line for the account. SECURITY '
    'DEFINER with the journal_entries/journal_lines RLS restated in the body — '
    'as INVOKER the per-row policy cascade times out (migration 279). Held '
    'identical to _foreign_bank_balances by '
    'tests/test_fx_reports_sql_parity_pg.py. Migration 281.';

REVOKE EXECUTE ON FUNCTION public.fx_foreign_bank_balances(uuid, uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fx_foreign_bank_balances(uuid, uuid) FROM anon;
GRANT EXECUTE ON FUNCTION public.fx_foreign_bank_balances(uuid, uuid)
    TO authenticated, service_role;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. FX adjustments, dated by their settlement period and windowed
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.fx_dated_adjustments(
    p_firm   uuid,
    p_client uuid,
    p_start  date,
    p_end    date,
    p_kind   text DEFAULT NULL
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
            RAISE EXCEPTION 'fx_dated_adjustments: caller has no user record in this database'
                USING ERRCODE = '42501';
        END IF;

        IF p_firm IS DISTINCT FROM v_my_firm THEN
            RAISE EXCEPTION 'fx_dated_adjustments: firm % is not the caller''s firm', p_firm
                USING ERRCODE = '42501';
        END IF;

        IF NOT public.can_access_client(p_client::text) THEN
            RAISE EXCEPTION 'fx_dated_adjustments: client % is not assigned to the caller', p_client
                USING ERRCODE = '42501';
        END IF;

        v_internal := public.my_internal_client_id();
        IF v_internal IS NOT NULL
           AND p_client = v_internal
           AND COALESCE(public.get_my_role(), '') <> 'Partner' THEN
            RAISE EXCEPTION 'fx_dated_adjustments: only a Partner may read the firm''s internal client'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    SELECT COALESCE(jsonb_agg(r ORDER BY r->>'date', r->>'currency', r->>'id'), '[]'::jsonb)
      INTO v_out
      FROM (
        SELECT jsonb_build_object(
                   'id',               a.id,
                   'date',             to_char(d.when_on, 'YYYY-MM-DD'),
                   'kind',             a.kind,
                   'currency',         a.currency,
                   'document_type',    a.document_type,
                   'document_id',      a.document_id,
                   -- Rates as JSON NUMBERS, not text, because that is what
                   -- PostgREST hands the caller for a numeric column and the
                   -- caller renders it with str(). json.loads makes a float of
                   -- it, so a rate stored 84.0000 renders "84.0" — scale is
                   -- already lost on the path this replaces. Emitting ::text
                   -- here would render "84.0000" instead: arguably better, and
                   -- a change in what a CA sees, so not smuggled in as part of
                   -- a performance fix. tests/test_fx_reports_sql_parity_pg.py
                   -- pins the two to the same rendering.
                   'original_rate',    to_jsonb(a.original_rate),
                   'settlement_rate',  to_jsonb(a.settlement_rate),
                   'closing_rate',     to_jsonb(a.closing_rate),
                   'base_delta_paise', a.base_delta_paise,
                   'rate_source',      a.rate_source,
                   'created_by',       a.created_by,
                   'journal_entry_id', a.journal_entry_id
               ) AS r
          FROM public.fx_adjustments a
          -- The adjustment is reported in the period its journal entry was
          -- POSTED to, which is what makes a backdated or multi-year settlement
          -- land in the right year. Only a posted, non-deleted entry of this
          -- firm and client counts — matching the dict the Python built — and
          -- anything else falls back to the audit row's own timestamp.
          --
          -- UTC on the fallback because PostgREST serialises timestamptz in UTC
          -- and the Python took the first ten characters of that string.
          LEFT JOIN public.journal_entries je
                 ON je.id         = a.journal_entry_id
                AND je.firm_id    = p_firm
                AND je.client_id  = p_client
                AND je.is_posted
                AND je.deleted_at IS NULL
          CROSS JOIN LATERAL (
              SELECT COALESCE(je.entry_date, (a.created_at AT TIME ZONE 'UTC')::date) AS when_on
          ) d
         WHERE a.firm_id   = p_firm
           AND a.client_id = p_client
           AND (p_kind  IS NULL OR a.kind = p_kind)
           AND (p_start IS NULL OR d.when_on >= p_start)
           AND (p_end   IS NULL OR d.when_on <= p_end)
      ) q;

    RETURN v_out;
END
$fn$;

COMMENT ON FUNCTION public.fx_dated_adjustments(uuid, uuid, date, date, text) IS
    'FX adjustments for one client in a window, each dated by the SETTLEMENT '
    'period of its journal entry (falling back to the audit row''s timestamp when '
    'no posted entry matches). Replaces a full {entry_id: entry_date} fetch over '
    'every posted entry, which realized_fx and exchange_rate_audit each built '
    'separately. p_kind filters to one kind (realized/unrealized); NULL returns '
    'all. SECURITY DEFINER with RLS restated (migration 279). Held identical to '
    'the Python by tests/test_fx_reports_sql_parity_pg.py. Migration 281.';

REVOKE EXECUTE ON FUNCTION public.fx_dated_adjustments(uuid, uuid, date, date, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fx_dated_adjustments(uuid, uuid, date, date, text) FROM anon;
GRANT EXECUTE ON FUNCTION public.fx_dated_adjustments(uuid, uuid, date, date, text)
    TO authenticated, service_role;

COMMIT;
