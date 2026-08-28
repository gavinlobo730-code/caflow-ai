-- PracticeSync — Migration 287: give `authenticated` the grants migration 285 forgot
--
-- WHAT BROKE
--   "Compute from Books" on the GSTR-3B screen returned 500 for every client
--   and every period from the moment migration 285 was applied to production
--   (2026-08-27 01:01 IST). The Render logs show the whole read sequence
--   succeeding — client_sales_invoices, customers, credit_notes,
--   sales_debit_notes, purchase_bills, debit_notes, purchase_credit_notes all
--   200 — and then one line:
--
--     GET | 403 | /rest/v1/itc_reversal_register?select=*&firm_id=eq...
--
--   403 from PostgREST on a SELECT is SQLSTATE 42501, permission denied. Not
--   RLS: an RLS refusal returns an empty array with 200. The grant was simply
--   never made. services/itc_register_service.for_period() is called
--   unconditionally by gstr3b_from_books, the exception is not swallowed, so
--   the whole return computation 500s.
--
-- WHY 285 MISSED IT, AND WHY CI COULD NOT SEE IT
--   Migration 269 set ALTER DEFAULT PRIVILEGES ... TO service_role, so every
--   table created since inherits service_role DML automatically. It did NOT do
--   the same for `authenticated`, and deliberately should not: `authenticated`
--   is the browser's role through PostgREST, and several tables in this schema
--   are SELECT-only for it on purpose. So a new table's `authenticated` grant
--   has to be written by hand, every time. 285 did not write it, and
--   production confirms the result — on itc_reversal_register `authenticated`
--   holds only REFERENCES/TRIGGER/TRUNCATE, the ACL noise a table has when
--   nobody granted it anything, while service_role holds full DML.
--
--   With USE_USER_JWT on, the API *is* `authenticated` as far as Postgres is
--   concerned. The migration-apply CI job runs as a superuser and never
--   assumes that role, so every test passed. tests/test_itc_reversal_register_
--   grants_pg.py is the guard that would have caught it, and it asserts the
--   SHAPE — every table service_role can read, `authenticated` can read too —
--   not just this one table, because the next migration to forget a grant is
--   the failure this is really about.
--
-- ALSO CORRECTED HERE: the isolation policy
--   285 wrote firm isolation as an inline subquery over public.users. That
--   happens to work — users_own_row_select lets the caller read their own row —
--   but it is not the shape every table since migration 154 uses, and it omits
--   the assignment scope entirely. This table holds client-scoped GST figures;
--   a staff member unassigned from a client has no business reading their ITC
--   reversals. Replaced with the pair migration 273 uses on
--   related_party_loans: PERMISSIVE firm isolation via get_my_firm_id(), plus
--   a RESTRICTIVE assignment scope that ANDs with it.
--
--   Tightening a live policy is normally something to be careful about. Here
--   it is free: the table has zero rows in production, so nothing can be
--   hidden by it.
--
-- No column changes, no data changes. Grants and policies only.

GRANT SELECT, INSERT, UPDATE, DELETE ON public.itc_reversal_register TO authenticated;
GRANT ALL                            ON public.itc_reversal_register TO service_role;

-- ── Firm isolation, the house shape ─────────────────────────────────────────
DROP POLICY IF EXISTS "firm_staff_manage_itc_reversal_register"
    ON public.itc_reversal_register;

DROP POLICY IF EXISTS itc_reversal_register_isolation
    ON public.itc_reversal_register;
CREATE POLICY itc_reversal_register_isolation ON public.itc_reversal_register
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());

-- ── Assignment scope, RESTRICTIVE so it narrows rather than widens ──────────
DROP POLICY IF EXISTS itc_reversal_register_assignment_scope
    ON public.itc_reversal_register;
CREATE POLICY itc_reversal_register_assignment_scope ON public.itc_reversal_register
    AS RESTRICTIVE
    FOR ALL TO authenticated
    USING (public.can_access_client(client_id::text))
    WITH CHECK (public.can_access_client(client_id::text));

-- ── Nine more the migration tree never granted ──────────────────────────────
--   The invariant in tests/test_itc_reversal_register_grants_pg.py, applied to
--   a database built from these migrations alone, named ten tables that
--   `authenticated` cannot read — not one. Production only has the one, because
--   the other nine were granted out of band at some point and the migration
--   that should have done it never existed.
--
--   That gap is only invisible while production is the only database anybody
--   builds. A fresh environment — a staging project, a restored branch, a
--   contributor's local stack — comes up from the migrations and 403s on all
--   nine, and the failure looks like broken code rather than a missing grant.
--
--   These are copied from what production actually holds today, privilege for
--   privilege, so applying this changes nothing there and makes every other
--   database match it. Two deliberately keep less than full DML:
--
--     invoice_sequences   — no DELETE. Dropping a sequence row would let the
--                           next invoice reuse a number already issued.
--     task_timeline_events — INSERT only. It is an append-only activity log;
--                           UPDATE or DELETE would rewrite history.
GRANT SELECT, INSERT, UPDATE, DELETE ON public.ai_context_windows      TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.ai_recommendations      TO authenticated;
GRANT SELECT, INSERT, UPDATE         ON public.invoice_sequences       TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.task_dependencies       TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.task_recurring_configs  TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.task_tags               TO authenticated;
GRANT SELECT, INSERT                 ON public.task_timeline_events    TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.time_entries            TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_capacity           TO authenticated;
