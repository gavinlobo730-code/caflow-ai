-- Migration 507: a signed-in session writes none of the insight and memory tables.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (ledger POST-A-257, found while building migration 505)
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 095 granted `authenticated` INSERT, UPDATE and DELETE on every AI table. Migration 505 took the write privileges
-- off the seven the copilot uses. Six more carry the same grants (060 and 095 for the profiles, 320 for the history) and are
-- written by repositories that took the caller's own session: `ai_insights` (the insight generator, and the status route
-- `PATCH /api/insights/{id}/status`), and the memory repository's `ai_memory_triggers` (the pipeline, and the acknowledge,
-- resolve and dismiss routes), `client_profiles`, `client_profile_history`, `firm_profiles` and `year_end_reports`
-- (`pattern_anomalies` was granted SELECT alone, so a write to it from a signed-in session already failed and only a job
-- could write it; it is in the list so the check below asserts it). No file in `apps/web` reads or writes any of them (the
-- screens go through the API), so nothing needs the privilege, and what it allowed is the shape of 505: any signed-in member
-- of a firm, whatever the role, could change another member's insight status, mark a trigger resolved, rewrite a client's
-- compliance profile or plant an insight, a trigger or a year-end report directly over PostgREST, without `rbac()`.
--
-- Migration 505's repository change is repeated here for the two repositories: every INSERT and UPDATE is made through the
-- privileged client, names its firm, and addresses a row by firm AND id (an insight's status update used to take the firm as
-- an optional argument, because row security was the second lock; it is required now).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- REVOKE INSERT, UPDATE, DELETE and TRUNCATE from `authenticated`, `anon` and PUBLIC on the seven tables, and check the
-- EFFECTIVE privileges (table, column, and through PUBLIC) before finishing, exactly as 499 and 505 do. Reading,
-- `service_role` and the row policies are untouched. A write from a signed-in session is now "permission denied for table"
-- (SQLSTATE 42501).
--
-- NOT DONE HERE: the `workflow_*` tables, which are the ledger line POST-A-248.

-- THREE OF THE SEVEN DO NOT EXIST ON A DATABASE BUILT FROM SCRATCH. Migration 070 creates `ai_memory_triggers`,
-- `pattern_anomalies` and `year_end_reports`, and it is on the runner's list of migrations that fail on a fresh database and
-- stop part-way (`BASELINE_FAILURES` in scripts/db/apply_migrations.py; 071 and 095 are on it too). Production has all seven,
-- so there the loop touches every table, and on a scratch database it touches the four that exist. A REVOKE on a table that is
-- not there would fail the migration (and with it the required `migration apply` check), so each table is asked for first.
DO $$
DECLARE
    tables text[] := ARRAY[
        'ai_insights', 'ai_memory_triggers', 'client_profiles', 'client_profile_history', 'firm_profiles',
        'year_end_reports', 'pattern_anomalies'
    ];
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY tables LOOP
        CONTINUE WHEN to_regclass(format('public.%I', t)) IS NULL;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);
    END LOOP;

    FOREACH t IN ARRAY tables LOOP
        CONTINUE WHEN to_regclass(format('public.%I', t)) IS NULL;
        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 507: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 507: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
    END LOOP;
END $$;
