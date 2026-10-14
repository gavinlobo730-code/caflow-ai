-- Migration 484 — only a Partner reads the audit log, and a staff member sees only the portal contacts of the
-- clients they can reach (security_privacy-34 and the production-policy question of POST-B-010; ledger
-- POST-B-010 and the row-scoping half of POST-B-027).
--
-- THE HOLES
--
--   1. `audit_log` on PRODUCTION carries two SELECT policies: `audit_log_partner_read` (firm AND role = Partner,
--      migration 082's intent) and `audit_log_own_firm` (firm only). Policies are permissive, so they OR, and the
--      second one makes the first meaningless: every member of the firm, a Reviewer and an unassigned Executive
--      included, can read the whole firm's edit log over PostgREST — who changed what, with the old and new
--      values of every audited table, payroll and bank rows among them. A database built from the migrations in
--      this repository has only the first, so no test saw it: the policy exists in production only. A read-only
--      look at production's `pg_policies` on 14-10-2026 listed both. The API already gives the log to a Partner
--      alone (`GET /api/audit` takes `accounting:approve`, Partner only; the route's docstring says so).
--
--   2. `client_portal_users` (the client's portal contacts, with their e-mail and a live invite_token) has a
--      firm-wide SELECT policy for staff, so every member of the firm read every client's contacts and tokens.
--      The table was left out of migration 084's assignment scope on purpose, for the portal principal's sake: a
--      portal contact has no `users` row, so `can_access_client()` denies them their own record. That reason
--      covers the contact reading THEIR OWN row; it never covered staff reading every client's rows.
--
-- WHAT THIS DOES
--   * drops `audit_log_own_firm` (idempotent: DROP POLICY IF EXISTS), leaving `audit_log_partner_read`, and fails
--     the migration if that policy is not there, because a log nobody but the service role can read is not what
--     this change means to leave;
--   * adds one RESTRICTIVE SELECT policy on `client_portal_users`:
--         auth_user_id = auth.uid()  OR  can_access_client(client_id)
--     so the portal contact still reads their own row (`client_portal_users_self` admits it and this does not
--     refuse it), and staff read a client's contacts exactly when they can reach the client: a Partner all of the
--     firm's, a Manager or Executive the clients they are assigned to, a Reviewer the same, an unassigned
--     Executive none, a suspended member none (468 makes `can_access_client` false for them).
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * `invite_token` is still readable by the staff who can reach the client. Hiding the column from the browser
--     (a column privilege or a view) needs every `select *` on the table to be named first, because a column
--     revoke turns each of them into a permission error; the only browser reader lists its columns explicitly
--     (app/clients/[id]/portal/page.tsx) but the API's readers under a caller's JWT have not been surveyed. The
--     ledger line POST-B-027 keeps that half.
--   * `audit_log` writes (the table is append-only by trigger and written by the service role), its INSERT
--     policy and its grants.
--   * Only the SELECT command is touched on `client_portal_users`: `authenticated` holds no other privilege on it.
--
-- Idempotent. Reversible: 484_..._rollback.sql restores the production policy (which RE-OPENS the audit log to
-- the whole firm) and drops the portal-contact policy.

-- ── audit_log ────────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "audit_log_own_firm" ON public.audit_log;

-- ── client_portal_users ──────────────────────────────────────────────────────
DROP POLICY IF EXISTS "client_portal_users_staff_in_reach" ON public.client_portal_users;
CREATE POLICY "client_portal_users_staff_in_reach" ON public.client_portal_users
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (
    auth_user_id = (SELECT auth.uid())
    OR public.can_access_client(client_id::text)
  );

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_policies
              WHERE schemaname = 'public' AND tablename = 'audit_log'
                AND policyname = 'audit_log_own_firm') THEN
    RAISE EXCEPTION 'migration 484: audit_log_own_firm is still there';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies
                  WHERE schemaname = 'public' AND tablename = 'audit_log'
                    AND policyname = 'audit_log_partner_read' AND cmd = 'SELECT') THEN
    RAISE EXCEPTION 'migration 484: audit_log_partner_read is missing, so nobody but the service role could read the log';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies
                  WHERE schemaname = 'public' AND tablename = 'client_portal_users'
                    AND policyname = 'client_portal_users_staff_in_reach'
                    AND permissive = 'RESTRICTIVE' AND cmd = 'SELECT') THEN
    RAISE EXCEPTION 'migration 484: client_portal_users_staff_in_reach is missing';
  END IF;
END $$;
