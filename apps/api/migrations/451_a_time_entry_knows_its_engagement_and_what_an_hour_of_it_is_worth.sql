-- ============================================================================
-- 451 — a time entry knows its engagement and what an hour of it is worth
--      (practice_management-11)
--
-- WHY
--     Hours were logged and could never become a bill. The timer's body had no
--     engagement and no rate, the Time screen sent only the client, and nothing
--     gave a staff member a billing rate at all: `users.cost_rate_paise` is
--     capture-only and its own comment says "NEVER used in any computation". So
--     `time_entries.billable_rate_paise` was NULL on every timer-started row, and
--     the one place that totalled unbilled work (`billing_service.unbilled_work`)
--     treated a NULL rate as ZERO — a figure that reads as "this work is worth
--     nothing" for what is really "nobody said what it is worth".
--
-- THE TWO RATES THIS ADDS, AND THE ORDER THEY ARE READ IN
--     `users.default_billable_rate_paise`     what an hour of THIS PERSON bills at
--     `fee_engagements.billable_rate_paise`   an OVERRIDE for one engagement
--     An entry's own rate, if somebody typed one, wins; then the engagement's;
--     then the person's; then NOTHING. The resolution is
--     `domain/billing/time_rate.resolve_rate` and the answer is STORED on the
--     entry (`time_entries.billable_rate_paise`, which exists since 073), so a
--     later change to a rate does not silently re-price work already logged —
--     the same reason a posted invoice does not move when a rate card does.
--
--     BOTH ARE NULLABLE WITH NO DEFAULT AND NO BACKFILL. NULL is "nobody has
--     said", which is a different statement from 0 ("this hour bills at nothing"
--     — a retainer's hours, a favour). Defaulting to 0 would make every existing
--     person and engagement look like a decision somebody took, and defaulting
--     to a number would invent one. `cost_rate_paise` is deliberately NOT read:
--     what an hour costs the firm is not what it bills.
--
-- THE UNBILLED-WORK TOTAL IS A SQL FUNCTION, BECAUSE ITS ANSWER IS TWENTY NUMBERS
--     `billing_service.unbilled_work` read every unbilled billable entry with
--     `.select("*")` — proportional to the work, not to the answer, and capped
--     silently at ~1000 rows by PostgREST, so a busy firm's total would have been
--     short by whatever the cap removed with no error. `unbilled_time_summary`
--     aggregates server-side and returns one row per (client, task, priced).
--     `domain/billing/time_rate.fold_unbilled` is its Python twin and the two
--     are pinned to each other by tests/test_451_..._pg.py, the way
--     `stock_position_as_at` is pinned to `domain/reporting/stock_position`.
--
--     "PRICED" IS `COALESCE(billable_rate_paise, hourly_rate_paise) IS NOT NULL`
--     — the legacy `hourly_rate_paise` stays a fallback, as it always was, so no
--     already-priced entry drops out of the total. An entry with NEITHER is
--     reported on its own row with `priced = false` and contributes NOTHING to
--     value: it is listed as "no rate", never counted as zero.
--
--     Value is floored PER ENTRY (minutes x paise / 60), exactly as
--     `billing_service.unbilled_value_paise` always did, so every grouping of the
--     same entries sums to the same total.
--
-- Additive and idempotent. No data is rewritten and no policy is touched.
-- ============================================================================

BEGIN;

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS default_billable_rate_paise bigint;

ALTER TABLE public.fee_engagements
    ADD COLUMN IF NOT EXISTS billable_rate_paise bigint;

DO $$ BEGIN
  IF NOT EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conrelid = 'public.users'::regclass
        AND conname  = 'users_default_billable_rate_paise_check') THEN
    ALTER TABLE public.users
      ADD CONSTRAINT users_default_billable_rate_paise_check
      CHECK (default_billable_rate_paise IS NULL OR default_billable_rate_paise >= 0);
  END IF;
  IF NOT EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conrelid = 'public.fee_engagements'::regclass
        AND conname  = 'fee_engagements_billable_rate_paise_check') THEN
    ALTER TABLE public.fee_engagements
      ADD CONSTRAINT fee_engagements_billable_rate_paise_check
      CHECK (billable_rate_paise IS NULL OR billable_rate_paise >= 0);
  END IF;
END $$;

COMMENT ON COLUMN public.users.default_billable_rate_paise IS
    'What an hour of this person bills at, in paise, or NULL when nobody has said '
    '(NULL is not 0). Read by domain/billing/time_rate.resolve_rate after the '
    'engagement override. NOT cost_rate_paise, which is what the hour costs the firm '
    'and is never used in a computation. Migration 451.';
COMMENT ON COLUMN public.fee_engagements.billable_rate_paise IS
    'An OVERRIDE of the billing rate for time recorded against this engagement, in '
    'paise, or NULL for none. 0 is a stated rate ("this engagement''s hours bill at '
    'nothing"); NULL is not. Migration 451.';

-- ── the unbilled-work total, aggregated where the rows are ───────────────────

CREATE OR REPLACE FUNCTION public.unbilled_time_summary(
    p_firm_id   uuid,
    p_client_id uuid DEFAULT NULL
)
RETURNS TABLE (
    client_id    uuid,
    task_id      uuid,
    priced       boolean,
    minutes      bigint,
    value_paise  bigint,
    entries      bigint
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        te.client_id,
        te.task_id,
        (COALESCE(te.billable_rate_paise, te.hourly_rate_paise) IS NOT NULL)        AS priced,
        SUM(te.duration_minutes)::bigint                                           AS minutes,
        COALESCE(SUM(
            CASE WHEN COALESCE(te.billable_rate_paise, te.hourly_rate_paise) IS NULL
                 THEN 0
                 ELSE (te.duration_minutes::bigint
                       * COALESCE(te.billable_rate_paise, te.hourly_rate_paise)) / 60
            END), 0)::bigint                                                       AS value_paise,
        COUNT(*)::bigint                                                           AS entries
    FROM public.time_entries te
    WHERE te.firm_id = p_firm_id
      AND te.is_billable
      AND te.billed_invoice_id IS NULL
      AND COALESCE(te.duration_minutes, 0) > 0
      AND (p_client_id IS NULL OR te.client_id = p_client_id)
    GROUP BY te.client_id, te.task_id, 3
$$;

COMMENT ON FUNCTION public.unbilled_time_summary(uuid, uuid) IS
    'Unbilled billable time, aggregated: one row per (client, task, priced). An '
    'entry with neither billable_rate_paise nor hourly_rate_paise has priced = false '
    'and adds NOTHING to value_paise. Python twin: domain/billing/time_rate.'
    'fold_unbilled. Migration 451.';

-- A function is executable by PUBLIC unless that is taken away, and `anon` is a
-- member of PUBLIC: 277, 363 and 408 all revoke both before granting, and so does
-- this. It is not SECURITY DEFINER, so a signed-in caller's own RLS still decides
-- which `time_entries` rows the aggregate can see whatever firm id they pass.
REVOKE EXECUTE ON FUNCTION public.unbilled_time_summary(uuid, uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.unbilled_time_summary(uuid, uuid) FROM anon;
GRANT EXECUTE ON FUNCTION public.unbilled_time_summary(uuid, uuid) TO authenticated, service_role;

COMMIT;
