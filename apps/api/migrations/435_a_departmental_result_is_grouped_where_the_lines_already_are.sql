-- Migration 435: the cost-centre allocation report is a GROUP BY in the
-- database, not every Income/Expense line of the FY paged into Python.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (apex-accounting-reports-13)
-- ═══════════════════════════════════════════════════════════════════════════
-- `services/cost_centre_service.allocation`'s own docstring promises the read
-- is bounded to "only lines that CARRY a centre" — and the query it runs has
-- no `cost_centre_id` filter at all, so it keyset-pages every posted
-- Income/Expense journal LINE of the financial year and sums them in Python,
-- even for a client who has never defined a single cost centre. That is
-- exactly the read-proportional-to-the-ledger CLAUDE.md's reporting-
-- performance section forbids — the departmental result is a few dozen rows
-- (one per centre per account), not the size of the ledger.
--
-- A SEPARATE, REAL correctness bug rode along with it: the query filtered
-- `chart_of_accounts.account_type IN ('Income', 'Expense')`, but this schema's
-- CHECK constraint (migration 003) only ever allows
-- `'Asset' | 'Liability' | 'Equity' | 'Revenue' | 'Expense'` — 'Income' has
-- never been a legal value in a real chart of accounts. So no revenue line
-- EVER reached the departmental result; every cost centre's income was
-- silently zero.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE FIX
-- ═══════════════════════════════════════════════════════════════════════════
-- `public.cost_centre_allocation` groups by (cost_centre_id, account_id) in
-- SQL and returns the finished rows as a jsonb array — the same shape
-- `public.cash_flow_report` (277, 279) and `public.schedule_iii_ageing` (303,
-- 305) already answer a report in: aggregate where the rows already are,
-- return a small finished answer, never a per-line payload proportional to
-- the ledger. A NULL cost_centre_id groups on its own by construction, which
-- is exactly the "(no cost centre)" bucket `domain/accounting/cost_centre.
-- allocate` already builds — the SQL changes nothing about what a cost
-- centre's own domain logic decides, only where the summing happens.
--
-- `account_type IN ('Revenue', 'Expense')` — the corrected filter — matches
-- `domain/reporting/model.INCOME_TYPES | EXPENSE_TYPES`, which
-- `services/cost_centre_service.py` now reads from directly rather than
-- restating, so the two cannot drift a second time.
--
-- The RLS restatement (SECURITY DEFINER bypasses RLS entirely) is transcribed
-- unchanged from `cash_flow_report` (279) and `schedule_iii_ageing` (305) —
-- the caller-firm check, the assignment-scope check, and the Partner-only
-- gate on the firm's own internal client — so all three functions keep one
-- definition of "an authorised caller" between them.
--
-- No table or column changes. Idempotent, and safe to re-run.
-- Its Python mock-mode twin needs no change: `services/cost_centre_service.
-- allocation` already returns `rule.allocate([], centres)` when `db is None`,
-- because there has never been an in-memory journal_lines fixture for this
-- report to aggregate over — so this function has nothing to keep in parity
-- with in mock mode, unlike cash_flow_report and schedule_iii_ageing, which
-- both have a real Python re-implementation for exactly that reason.

BEGIN;

CREATE OR REPLACE FUNCTION public.cost_centre_allocation(
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
    -- Restates the RLS that SECURITY DEFINER bypasses. Transcribed from
    -- post_journal_atomic (271) via cash_flow_report (279) and
    -- schedule_iii_ageing (305), so none of the four can drift in what they
    -- consider an authorised caller.
    IF auth.uid() IS NOT NULL THEN
        v_my_firm := public.get_my_firm_id();

        IF v_my_firm IS NULL THEN
            RAISE EXCEPTION 'cost_centre_allocation: caller has no user record in this database'
                USING ERRCODE = '42501';
        END IF;

        IF p_firm IS DISTINCT FROM v_my_firm THEN
            RAISE EXCEPTION 'cost_centre_allocation: firm % is not the caller''s firm', p_firm
                USING ERRCODE = '42501';
        END IF;

        IF NOT public.can_access_client(p_client::text) THEN
            RAISE EXCEPTION 'cost_centre_allocation: client % is not assigned to the caller', p_client
                USING ERRCODE = '42501';
        END IF;

        v_internal := public.my_internal_client_id();
        IF v_internal IS NOT NULL
           AND p_client = v_internal
           AND COALESCE(public.get_my_role(), '') <> 'Partner' THEN
            RAISE EXCEPTION 'cost_centre_allocation: only a Partner may read the firm''s internal client'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    -- ONE pass over journal_lines, grouped where the rows already are. This is
    -- the whole fix: the old Python path fetched every one of these lines
    -- individually and summed them after the Singapore-to-Mumbai round trip.
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'cost_centre_id', g.cost_centre_id,
               'account_id',     g.account_id,
               'account_name',   g.account_name,
               'account_type',   g.account_type,
               'debit_paise',    g.debit_paise,
               'credit_paise',   g.credit_paise
           )), '[]'::jsonb)
      INTO v_out
      FROM (
          SELECT jl.cost_centre_id,
                 jl.account_id,
                 coa.account_name,
                 coa.account_type,
                 SUM(jl.debit_paise)::bigint  AS debit_paise,
                 SUM(jl.credit_paise)::bigint AS credit_paise
            FROM public.journal_lines jl
            JOIN public.journal_entries je   ON je.id = jl.journal_entry_id
            JOIN public.chart_of_accounts coa ON coa.id = jl.account_id
           WHERE je.firm_id = p_firm
             AND je.client_id = p_client
             AND je.is_posted
             AND je.deleted_at IS NULL
             AND je.entry_date >= p_start
             AND je.entry_date <= p_end
             -- The corrected filter (was 'Income', which this schema's CHECK
             -- constraint has never permitted — migration 003).
             AND coa.account_type IN ('Revenue', 'Expense')
           GROUP BY jl.cost_centre_id, jl.account_id, coa.account_name, coa.account_type
      ) g;

    RETURN v_out;
END;
$fn$;

REVOKE ALL ON FUNCTION public.cost_centre_allocation(uuid, uuid, date, date) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.cost_centre_allocation(uuid, uuid, date, date) FROM anon;
GRANT EXECUTE ON FUNCTION public.cost_centre_allocation(uuid, uuid, date, date) TO authenticated;
GRANT EXECUTE ON FUNCTION public.cost_centre_allocation(uuid, uuid, date, date) TO service_role;

COMMIT;
