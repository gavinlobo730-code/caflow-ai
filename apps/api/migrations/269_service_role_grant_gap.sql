-- Migration 269: finish what migration 041 never applied — service_role's grants.
--
-- WHAT BROKE, AND HOW IT WAS FOUND
-- The 06:00 IST sweep finally recorded a run on 2026-08-17 (the startup catch-up
-- from task #155 fired after deploy). Five of its job/firm pairs failed with
-- SQLSTATE 42501, permission denied:
--
--     recurring_generation   -> task_recurring_configs
--     invoice_overdue        -> fee_invoices
--     compliance_generation  -> fee_engagements
--
-- Background jobs run under get_service_supabase(), i.e. the service_role
-- Postgres role. On those tables service_role held only REFERENCES/TRIGGER/
-- TRUNCATE — the ACL noise a table has when nobody ever granted it anything —
-- while `authenticated` had full DML. The jobs had never once run to completion.
--
-- WHY THE GAP EXISTS (it is an accident, not a policy)
-- No migration anywhere REVOKEs from service_role; grep the tree. The grants
-- were simply never made:
--
--   * 039_grant_service_role_permissions.sql enumerates ~25 tables by hand and
--     was applied. Every table it names (tasks, journal_lines, bank_transactions)
--     has service_role DML in production today.
--   * 041_grant_all_tables_to_authenticated.sql extends the same list to the
--     rest of the schema "TO authenticated, service_role" — but its header says
--     "Run in Supabase SQL Editor", and it evidently never was. Every table that
--     appears only in 041 (fee_invoices, fee_engagements) has authenticated DML
--     and no service_role grant at all. That split is the fingerprint: 039 ran,
--     041 did not.
--   * Every table created after 041 by a migration that granted only to
--     `authenticated` inherited the same hole. 86 tables were in that state.
--
-- WHAT THIS DOES NOT TOUCH
-- Migration 096 grants service_role SELECT and deliberately nothing more on
-- receipts, receipt_allocations, credit_notes, purchase_bills and
-- purchase_payments, because "the reporting engine never writes to these
-- tables". That is a considered least-privilege decision, not an oversight, and
-- a blanket grant would silently undo it. Step 2 skips those five, leaving them
-- exactly as 096 set them. If a job ever genuinely needs to write one, that
-- deserves its own migration saying which job and why — not a side effect of
-- this one.
--
-- Idempotent, and safe to re-run.

-- ── 1. The schema itself ─────────────────────────────────────────────────────
GRANT USAGE ON SCHEMA public TO service_role;

-- ── 2. Every table, which is what 041 intended — minus 096's five ────────────
--     Granting the whole schema and then revoking the five back would be
--     shorter, but scripts/db/apply_migrations.py runs `psql -f` WITHOUT
--     --single-transaction, so each statement commits on its own: between the
--     GRANT and the REVOKE the reporting tables would really be writable, not
--     just notionally. Deciding per table means that window never exists.
--
--     Views and materialised views get SELECT only. Postgres accepts a DML
--     grant on either (checked on 16 — it does not error), but the privilege
--     would be inert: a matview cannot be inserted into at all, and a view only
--     where it is auto-updatable. Granting it would mean writing a permission
--     nothing can exercise, so this stays at what is actually used: reads.
DO $$
DECLARE
    obj         record;
    read_only   CONSTANT text[] := ARRAY[
        'receipts', 'receipt_allocations', 'credit_notes',
        'purchase_bills', 'purchase_payments'
    ];
BEGIN
    FOR obj IN
        SELECT c.relname, c.relkind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p', 'v', 'm')   -- table, partitioned, view, matview
    LOOP
        IF obj.relkind IN ('v', 'm') OR obj.relname = ANY (read_only) THEN
            EXECUTE format('GRANT SELECT ON public.%I TO service_role', obj.relname);
        ELSE
            EXECUTE format(
                'GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO service_role',
                obj.relname
            );
        END IF;
    END LOOP;
END $$;

-- ── 3. Sequences, so INSERT on a serial-keyed table can actually allocate ────
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;

-- ── 4. The pattern, not just the 86 instances ───────────────────────────────
--     Steps 2-3 fix the tables that exist today. Without this step the next
--     migration that creates a table and grants only `authenticated` reopens
--     the same hole, which is exactly how 86 of them accumulated.
--
--     Caveat worth knowing: default privileges attach to the role that CREATES
--     the object, and this sets them for the role running this migration. That
--     is the same role the migration runner uses to create tables, so new
--     tables are covered. A table created by some other role still needs its
--     own grant — the invariant test in tests/test_r269_service_role_grants_pg.py
--     is what catches that, rather than trusting this to be airtight.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO service_role;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO service_role;
