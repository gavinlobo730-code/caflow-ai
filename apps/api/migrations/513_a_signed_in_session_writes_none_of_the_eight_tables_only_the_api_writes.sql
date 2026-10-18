-- Migration 513: a signed-in session writes none of the eight tables only the API writes.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (ledger POST-A-018, from the 3 September 2026 RLS review)
-- ═══════════════════════════════════════════════════════════════════════════
-- `credit_note_allocations`, `invoice_sequences`, `scheduler_runs`, `task_dependencies`, `task_tags`, `task_templates`,
-- `task_timeline_events` and `user_capacity` were granted write privileges to `authenticated` by migrations 095 and 287 although
-- no file in `apps/web` reads or writes any of them (checked by a scan of `.from(...)`). Read from production on 18-10-2026:
--
--     credit_note_allocations  INSERT UPDATE DELETE TRUNCATE        task_tags         INSERT UPDATE DELETE TRUNCATE
--     user_capacity            INSERT UPDATE DELETE TRUNCATE        task_dependencies INSERT UPDATE DELETE TRUNCATE
--     invoice_sequences        INSERT UPDATE TRUNCATE               task_timeline_events  INSERT TRUNCATE
--     scheduler_runs, task_templates   TRUNCATE only
--
-- (`anon` holds REFERENCES, TRIGGER and TRUNCATE on all eight, a platform default, and no data privilege.) A firm-isolation row
-- policy was the only control. What it allowed, from any signed-in session of any role, with no `rbac()` in the way:
--   * `invoice_sequences`: set the firm's next invoice number backwards or forwards. Rule 46(b) wants a consecutive serial;
--     a number reused is a duplicate tax invoice, a number skipped is a gap the firm must explain;
--   * `credit_note_allocations`: write or delete the application of a credit note to an invoice, which is what a §34 note
--     reduces the invoice's outstanding by;
--   * `user_capacity`, `task_tags`, `task_dependencies`, `task_timeline_events`: rewrite the workload settings, relabel tasks,
--     add a dependency or forge an entry in a task's history.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- The API writes all eight with a privileged client; the three writers that took the caller's own session now do not
-- (`credit_notes` for the allocation, `capacity_repository`, `task_extras_repository`) and name their firm, and
-- `task_dependencies`, which has no firm of its own, is written only after both tasks are shown to be the firm's. This migration
-- then REVOKES INSERT, UPDATE, DELETE and TRUNCATE on the eight from `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE
-- privilege (table, column, through PUBLIC). Reading is untouched, `service_role` is untouched, and the row policies stay as the
-- second lock.
--
-- NOT DONE HERE, AND WHY
--   The ledger line also asked to re-create seven policies `TO authenticated` instead of `TO public`. With the write verbs gone
--   and no SELECT held by `anon`, a policy's role list decides nothing, and rewriting production's policies is the kind of change
--   the production-snapshot guard exists to watch, for no gain in what any role can do.
--
-- DEPLOY ORDER: the new API works either side of this migration. For the minutes the OLD API still runs against the revoked
-- grants, a task tag, dependency or timeline event, a workload capacity edit and the application of a credit note fail with a
-- permission error; nothing is half-written, because each of them is a single statement or is rolled back by its caller.
--
-- Idempotent. Reversible: 513_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    tables text[] := ARRAY[
        'credit_note_allocations', 'invoice_sequences', 'scheduler_runs', 'task_dependencies', 'task_tags',
        'task_templates', 'task_timeline_events', 'user_capacity'
    ];
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY tables LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);
    END LOOP;

    FOREACH t IN ARRAY tables LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 513: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 513: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
    END LOOP;
END $$;
