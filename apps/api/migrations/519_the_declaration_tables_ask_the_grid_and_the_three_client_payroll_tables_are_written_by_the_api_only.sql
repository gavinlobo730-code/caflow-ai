-- Migration 519: the tax-declaration tables ask the per-person grid for staff writes, and the three client-level payroll tables are
-- written by the API and by nobody signed in.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- PART 1 — THE DECLARATION TABLES (ledger POST-A-219, part 1)
-- ═══════════════════════════════════════════════════════════════════════════
-- Migrations 485 and 490 put the payroll READ tier, and 485 the WRITE tier, on the other payroll tables through
-- `my_permission('payroll', ..., 'Manager')`, the function `rbac()` resolves through, so a Partner's per-person block on the Team
-- screen (migration 403/415) is honoured by the database as well as by the route. `payroll_it_declarations` and
-- `payroll_it_declaration_items` were left on the ROLE: their restrictive write policies (296, 297) ask `my_role_at_least('Manager')`
-- and, for a delete, `my_role_at_least('Partner')`, so a Manager whom a Partner had blocked from payroll:write could still write an
-- employee's declaration directly over the database. They are the one pair of payroll tables a signed-in session may still write
-- (Rule 26C makes Form 12BB the employee's own statement, and the employee has no staff principal to go through the API with), which
-- is why migration 499 could not simply revoke the write.
--
-- WHAT THIS DOES: each of the six restrictive write policies keeps its shape and its EMPLOYEE arm exactly, and only the STAFF arm
-- changes: `my_role_at_least('Manager')` becomes `my_permission('payroll', 'write', 'Manager')` and the delete's
-- `my_role_at_least('Partner')` becomes `my_permission('payroll', 'finalize', 'Partner')`. THE MINIMUM ROLE IS UNCHANGED for every
-- policy, so with an empty `user_permissions` (production holds none) this reproduces today's behaviour exactly; the grid only
-- narrows (a denial) or widens (a grant) for the person it names. The employee's own unverified declaration is still writable by the
-- employee, whatever the grid says about any staff member.
--
-- WHY A DELETE ASKS `finalize` AND NOT `write` (an independent review of this migration, 18-10-2026): the grid has no `delete` action
-- for payroll, and a grid row that GRANTS an action wins over the minimum role (migration 415). Asking `write` for a delete would let a
-- Partner who granted an Executive payroll:write, so that they could key monthly inputs, hand them DELETE on every declaration and,
-- by cascade, its items over PostgREST, which was Partner-only before this migration and which no API route does. `finalize` is the
-- payroll action that is Partner-only by default, so a delete stays a Partner's unless a Partner deliberately grants that.
--
-- TRUNCATE is also revoked from the signed-in roles on the two declaration tables (migrations 499 and 515 did so for the others):
-- PostgREST does not expose it, so nothing could reach it, and the privilege is free to remove.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- PART 2 — THE THREE CLIENT-LEVEL PAYROLL TABLES (ledger POST-A-219, part 3)
-- ═══════════════════════════════════════════════════════════════════════════
-- `client_payroll_settings` (a Partner's on/off switch for payroll, and the day attendance is due), `client_statutory_identity` (the
-- TAN, EPF establishment code, ESIC employer code and LIN the statements print) and `client_pt_registrations` (professional-tax
-- registrations) were not audited by 485 or 490. Read on 18-10-2026:
--   * they are READ by the payroll router (with the privileged client), by the TDS router and the Form 3CD and payslip services (the
--     statement's TAN is needed by whoever holds `tds:compute`, an Executive, so a payroll read tier would be WRONG for it);
--   * they are WRITTEN only by the payroll router, with the privileged client (`routers/payroll._db` is the service client), and by
--     no screen in `apps/web` (the only mentions are in comments);
--   * and yet each carried a firm-only read rule and, for writes, only `my_role_at_least('Manager')`: a Manager the grid had blocked
--     from payroll:write could change the client's TAN, an establishment code or a professional-tax registration directly, and
--     `client_payroll_settings` held column-level INSERT and UPDATE for `authenticated` (migration 332 took the three enablement
--     columns out of reach, on purpose, and left the rest).
--
-- DECISION (Claude's, under the three tests): reads stay as they are (identifiers the statements print and the TDS tier needs, no
-- amount in them, firm-scoped), and the signed-in WRITE is taken away from all three, because nothing signed-in uses it and the
-- API is where the grid, the audit log and the timeline already run. REVOKE INSERT, UPDATE, DELETE and TRUNCATE from `authenticated`,
-- `anon` and PUBLIC; the table-level revoke removes the column-level grants as well, and the closing check asks the EFFECTIVE privilege
-- (table level, column level, or reaching a role through PUBLIC). `service_role` is untouched; the restrictive row policies stay as
-- the second lock.
--
-- NOT DONE HERE, AND SAID SO
--   * The read tier of these three tables (above). The 4th item of the ledger line, EXPLAIN on a large firm for the per-row function
--     call the payroll policies make, cannot be done from here: there is no large firm in this environment. It stays open.
--
-- DEPLOY ORDER: nothing signed-in writes these three tables, so no screen or API path is cut off; the migration job runs after the
-- tests while Render rebuilds. For Part 1 nothing changes for anybody the grid has not been used on.
--
-- Idempotent. Reversible: 519_..._rollback.sql restores the policies as they were and the grants production held on 18-10-2026.

-- ── PART 1 ────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF to_regclass('public.payroll_it_declarations') IS NULL OR to_regclass('public.payroll_it_declaration_items') IS NULL THEN
        RAISE NOTICE 'migration 519: the declaration tables do not exist here; part 1 skipped';
        RETURN;
    END IF;

    DROP POLICY IF EXISTS "payroll_it_declarations_role_insert" ON public.payroll_it_declarations;
    CREATE POLICY "payroll_it_declarations_role_insert" ON public.payroll_it_declarations
      AS RESTRICTIVE FOR INSERT
      WITH CHECK (
        public.my_permission('payroll', 'write', 'Manager')
        OR (employee_id IN (SELECT public.my_employee_ids())
            AND proofs_verified IS FALSE)
      );

    DROP POLICY IF EXISTS "payroll_it_declarations_role_update" ON public.payroll_it_declarations;
    CREATE POLICY "payroll_it_declarations_role_update" ON public.payroll_it_declarations
      AS RESTRICTIVE FOR UPDATE
      USING (
        public.my_permission('payroll', 'write', 'Manager')
        OR (employee_id IN (SELECT public.my_employee_ids())
            AND proofs_verified IS FALSE)
      )
      WITH CHECK (
        public.my_permission('payroll', 'write', 'Manager')
        OR (employee_id IN (SELECT public.my_employee_ids())
            AND proofs_verified IS FALSE)
      );

    DROP POLICY IF EXISTS "payroll_it_declarations_role_delete" ON public.payroll_it_declarations;
    CREATE POLICY "payroll_it_declarations_role_delete" ON public.payroll_it_declarations
      AS RESTRICTIVE FOR DELETE
      USING (public.my_permission('payroll', 'finalize', 'Partner'));

    DROP POLICY IF EXISTS "payroll_it_declaration_items_role_insert" ON public.payroll_it_declaration_items;
    CREATE POLICY "payroll_it_declaration_items_role_insert" ON public.payroll_it_declaration_items
      AS RESTRICTIVE FOR INSERT
      WITH CHECK (
        public.my_permission('payroll', 'write', 'Manager')
        OR declaration_id IN (SELECT public.my_it_declaration_ids())
      );

    DROP POLICY IF EXISTS "payroll_it_declaration_items_role_update" ON public.payroll_it_declaration_items;
    CREATE POLICY "payroll_it_declaration_items_role_update" ON public.payroll_it_declaration_items
      AS RESTRICTIVE FOR UPDATE
      USING (
        public.my_permission('payroll', 'write', 'Manager')
        OR declaration_id IN (SELECT public.my_it_declaration_ids())
      )
      WITH CHECK (
        public.my_permission('payroll', 'write', 'Manager')
        OR declaration_id IN (SELECT public.my_it_declaration_ids())
      );

    DROP POLICY IF EXISTS "payroll_it_declaration_items_role_delete" ON public.payroll_it_declaration_items;
    CREATE POLICY "payroll_it_declaration_items_role_delete" ON public.payroll_it_declaration_items
      AS RESTRICTIVE FOR DELETE
      USING (
        public.my_permission('payroll', 'finalize', 'Partner')
        OR declaration_id IN (SELECT public.my_it_declaration_ids())
      );

    REVOKE TRUNCATE ON public.payroll_it_declarations, public.payroll_it_declaration_items FROM PUBLIC, authenticated, anon;
    IF has_table_privilege('authenticated', 'public.payroll_it_declarations', 'TRUNCATE')
       OR has_table_privilege('anon', 'public.payroll_it_declarations', 'TRUNCATE')
       OR has_table_privilege('authenticated', 'public.payroll_it_declaration_items', 'TRUNCATE')
       OR has_table_privilege('anon', 'public.payroll_it_declaration_items', 'TRUNCATE') THEN
        RAISE EXCEPTION 'migration 519: a signed-in role still holds TRUNCATE on a declaration table';
    END IF;
END $$;

-- ── PART 2 ────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['public.client_payroll_settings', 'public.client_statutory_identity', 'public.client_pt_registrations'] LOOP
        IF to_regclass(t) IS NOT NULL THEN
            EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON %s FROM PUBLIC, authenticated, anon', t);
        END IF;
    END LOOP;
    FOREACH t IN ARRAY ARRAY['public.client_payroll_settings', 'public.client_statutory_identity', 'public.client_pt_registrations'] LOOP
        IF to_regclass(t) IS NULL THEN
            CONTINUE;
        END IF;
        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, t, verb) THEN
                    RAISE EXCEPTION 'migration 519: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, t, 'INSERT') OR has_any_column_privilege(r, t, 'UPDATE') THEN
                RAISE EXCEPTION 'migration 519: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
    END LOOP;
END $$;
