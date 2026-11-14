-- Migration 586: a member's own time over a range of Indian days is summed by the database (ledger POST-A-156).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- `/time` showed "Total Hours", "Billable Hours" and "Non-Billable" as the sum of the entries it LISTED, a window of at most 500, so
-- the tiles were the latest entries and not any period. `GET /api/time-entries/summary/me` existed and nothing called it: it accepted
-- a `period` it ignored, and `time_tracking_repo.get_summary` fetched every entry the member had ever made and added them up in
-- Python, which CLAUDE.md's reporting rule forbids (the answer is a few numbers, so what crosses the wire must be a few numbers).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
--  * `time_entry_summary(firm, user, from, to)`: over one member's entries that STARTED in [from, to) (the API passes the instants that
--    bound a range of Indian days, `core.ist_clock.ist_day_window`, so the end is exclusive), the finished entries' total minutes,
--    billable minutes and count, the timers still running (counted apart, because a running entry has no duration yet), and the
--    minutes per client, ordered by client with no client last. An entry is finished when it has both `ended_at` and
--    `duration_minutes`, which is what the Python summary always counted.
--  * `domain/time_summary.summarise` is its mock-mode twin and `tests/test_time_entry_summary_parity_pg.py` holds the two identical.
--
-- SECURITY INVOKER, and EXECUTE is revoked from PUBLIC, anon and authenticated and given to service_role alone: the API calls it with
-- its privileged client after asking who the caller is, and names the firm and the member itself, so the function takes no client
-- scope and needs no `assert_caller_acts_for`. No table, column or policy changes; nothing is backfilled.

BEGIN;

CREATE OR REPLACE FUNCTION public.time_entry_summary(
    p_firm uuid,
    p_user uuid,
    p_from timestamptz,
    p_to   timestamptz
) RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = public, pg_catalog
AS $fn$
    WITH w AS (
        SELECT client_id, duration_minutes, is_billable, ended_at
          FROM public.time_entries
         WHERE firm_id = p_firm
           AND user_id = p_user
           AND started_at >= p_from
           AND started_at <  p_to
    ), done AS (
        SELECT client_id, duration_minutes, is_billable
          FROM w
         WHERE ended_at IS NOT NULL AND duration_minutes IS NOT NULL
    ), per_client AS (
        SELECT client_id,
               sum(duration_minutes)                                    AS minutes,
               COALESCE(sum(duration_minutes) FILTER (WHERE is_billable), 0) AS billable_minutes
          FROM done
         GROUP BY client_id
    )
    SELECT jsonb_build_object(
        'total_minutes',    COALESCE((SELECT sum(duration_minutes) FROM done), 0),
        'billable_minutes', COALESCE((SELECT sum(duration_minutes) FROM done WHERE is_billable), 0),
        'entries_count',    (SELECT count(*) FROM done),
        'running',          (SELECT count(*) FROM w WHERE ended_at IS NULL),
        'by_client',        COALESCE((SELECT jsonb_agg(jsonb_build_object(
                                          'client_id', client_id,
                                          'minutes', minutes,
                                          'billable_minutes', billable_minutes)
                                        ORDER BY client_id NULLS LAST)
                                        FROM per_client), '[]'::jsonb)
    );
$fn$;

COMMENT ON FUNCTION public.time_entry_summary(uuid, uuid, timestamptz, timestamptz) IS
  'One member''s finished time in [from, to): total, billable, count, running timers apart, minutes per client. '
  'Mock twin: domain/time_summary.summarise (POST-A-156, migration 586).';

REVOKE ALL ON FUNCTION public.time_entry_summary(uuid, uuid, timestamptz, timestamptz) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.time_entry_summary(uuid, uuid, timestamptz, timestamptz) TO service_role;

COMMIT;
