-- Migration 558: `hsn_master` and `tds_section_limits` are closed to the signed-in role in a database built from the migrations,
-- as they already are in production (ledger POST-A-355).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- Production holds no INSERT, UPDATE or DELETE for `authenticated` or `anon` on these two reference tables (read from production on
-- 28-10-2026), and nothing in this repository says so: the revoke was applied by a statement no migration carries. A database built
-- from the migrations (a staging copy, a disaster recovery) therefore let a signed-in member write the HSN master and the retired TDS
-- rate master that production does not. `tests/test_the_tables_the_signed_in_role_cannot_write_are_closed_in_the_migration_built_database_pg.py`
-- found it while it was holding the list of tables the signed-in role cannot write against the migrations (POST-A-354) and kept the two
-- names on a shrink-only exception list until this migration.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- Revokes INSERT, UPDATE, DELETE and TRUNCATE on both tables from `authenticated`, `anon` and PUBLIC, then checks the EFFECTIVE privilege
-- (table level, column level, through PUBLIC) and that `service_role` kept its write. Reading is untouched. Nothing writes either table
-- from a signed-in session or from the API at all (no code in the repository writes them; the migrations that seeded them did), and
-- `tests/test_the_dead_tds_rate_master_has_no_readers.py` holds the second table unread.
--
-- ON PRODUCTION this changes one thing: both signed-in roles hold TRUNCATE on both tables there (a platform default that PostgREST does
-- not expose), and that goes. INSERT, UPDATE and DELETE were already absent, so the statements for them are no-ops.
--
-- Idempotent. Reversible: 558_..._rollback.sql gives TRUNCATE back, which is what production held; it does not give the write verbs
-- back, because production never had them and a rebuilt database holding them was the defect.

DO $$
DECLARE
    tables text[] := ARRAY['hsn_master', 'tds_section_limits'];
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
                    RAISE EXCEPTION 'migration 558: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 558: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE') THEN
            RAISE EXCEPTION 'migration 558: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
