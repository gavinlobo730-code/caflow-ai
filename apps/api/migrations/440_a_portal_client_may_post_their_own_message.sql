-- Migration 440: a portal client may post to their own message thread.
--
-- WHAT BROKE
-- Every send from the client portal's Messages tab failed with a raw 500:
-- "The server is not permitted to write this table." — SQLSTATE 42501 out of
-- `services/portal_data_service.post_message`'s INSERT. Reads worked (GET
-- .../messages -> 200, empty list).
--
-- THE SYMPTOM POINTED AT A MISSING GRANT AND THAT IS NOT WHAT IT WAS.
-- core/exceptions.py maps EVERY SQLSTATE 42501 to that exact sentence,
-- whether it comes from a table-level GRANT Postgres checks before RLS, or
-- from an RLS policy's own WITH CHECK failing — and a SELECT blocked by RLS
-- returns zero rows, not an error, which is indistinguishable from "no
-- messages yet". Both observations are consistent with either cause, so this
-- was verified rather than assumed: reproduced end to end on a throwaway
-- database built from every migration in this tree, `SET ROLE authenticated`
-- with a portal contact's own JWT claim. `authenticated` already holds
-- SELECT, INSERT, UPDATE, DELETE on portal_messages exactly as 048, 094 and
-- 194 declare — the GRANT was never the problem. The INSERT failed with:
--
--   ERROR:  new row violates row-level security policy
--           "portal_messages_assignment_scope" for table "portal_messages"
--
-- THE ACTUAL CAUSE
-- `portal_messages_assignment_scope` is a RESTRICTIVE FOR ALL policy —
-- declared in migration 084's one-shot loop (portal_messages already carried
-- a client_id when 084 first ran) and re-created by migration 294 once the
-- guard-drift sweep found production was missing it:
--
--   AS RESTRICTIVE FOR ALL
--   USING (public.can_access_client(client_id::text))
--   WITH CHECK (public.can_access_client(client_id::text))
--
-- `can_access_client` is TRUE for a client_id of NULL, a Partner, or a staff
-- member with a user_client_assignments row — every branch collapses for a
-- portal client, the same way migration 262's header works through for
-- payroll_employees: a portal client has no `users` row, so get_my_role()
-- returns NULL, the EXISTS is false, and NULL OR false OR false is NULL,
-- which RLS treats as deny. A RESTRICTIVE policy ANDs with the OR of every
-- PERMISSIVE one, so this alone overrides `portal_client_messages` (048/094)
-- and `portal_contact_messages` (109) — the two policies that exist
-- specifically to let a portal client read and post their own thread —
-- whatever those say. 294's own header names the risk it was closing
-- ("a non-Partner reads the firm's own internal client records") and never
-- considered that portal_messages, unlike the other seven tables in that
-- sweep, is written by a SECOND kind of principal that structurally fails
-- can_access_client. The bug was latent in 084's declared migration from the
-- day portal_messages existed; production simply never had this policy until
-- 294 restored it, which is what turned a declared bug into a live one.
--
-- THE SHAPE OF THE FIX — 262's, applied to a write path
-- 262 solved the identical shape for payroll_employees/payroll_runs by
-- splitting the FOR ALL restrictive policy into four per-command ones and
-- widening only the SELECT arm with an "or it's the caller's own record"
-- branch, because an employee only ever reads. A portal client also WRITES —
-- posting a message is the whole point of this screen — so both the SELECT
-- and INSERT arms carry the exception here; UPDATE and DELETE keep
-- can_access_client() verbatim, unchanged from today, because nothing in
-- this codebase ever updates or deletes a portal_messages row from the
-- portal side (grep services/portal_data_service.py and routers/portal_data.py
-- — post_message only ever INSERTs) and widening a write nobody uses would be
-- exactly the CLAUDE.md-documented mistake of widening a FOR ALL policy
-- ahead of the feature that needs it.
--
-- THE BARE NAME SURVIVES, ON PURPOSE, NARROWED RATHER THAN DROPPED
-- 262 could afford to DROP `payroll_employees_assignment_scope` outright: no
-- earlier migration's own logic still goes looking for it by that exact
-- name. `portal_messages_assignment_scope` is not so free — migration 294's
-- idempotent restore loop checks existence with
-- `policyname = tablename || '_assignment_scope'` and nothing else, so if
-- that name stops existing on `portal_messages` at all, a FUTURE out-of-band
-- re-run of 294 (which 262's own header already documents as a real
-- scenario: "applied out of band, e.g. through the Supabase dashboard or
-- MCP") recreates the exact FOR ALL policy this migration exists to retire —
-- reopening the bug once, silently, with no error and no later migration
-- able to notice. Proven, not assumed:
-- tests/test_r294_columns_and_guards_pg.py::
-- test_it_is_a_no_op_on_a_database_that_never_had_the_drift re-applies 294's
-- own file directly against a fully-migrated database and failed against
-- this migration's first draft, which dropped the name entirely.
--
-- 294's guard does not care WHICH command the name is scoped to — only that
-- a policy of that name exists on that table — so the bare name is kept
-- alive on the one command that needed no widening anyway (UPDATE), with its
-- predicate byte-for-byte what 294 itself would (re-)create. DELETE is a new
-- name for the same reason SELECT and INSERT are: 294 only ever knew one
-- bare name for this table, so a second unwidened command has to be a second
-- name regardless.
--
-- `public.my_portal_client_ids()` is the exception's helper, SECURITY
-- DEFINER for the same reason `can_access_client()` and 262's
-- `my_employee_ids()` are: it has to read client_portal_users and clients
-- regardless of the CALLER's own RLS, or the check would recurse into the
-- very tables it exists to look past. It checks BOTH the multi-contact link
-- (client_portal_users, migration 109 — the live path; a plain subquery
-- against this table already worked for a portal contact under today's RLS,
-- confirmed the same way) and the legacy single-user link
-- (clients.portal_user_id, migration 048) — for parity with the two existing
-- PERMISSIVE policies, which check both. The legacy link is written here
-- as SECURITY DEFINER specifically because a plain subquery against `clients`
-- does NOT work for a portal client today: `clients_assignment_scope`
-- (migration 084) is its own RESTRICTIVE policy, gated on the very same
-- can_access_client() that fails for a portal principal, so a legacy
-- portal-linked client cannot see their own `clients` row via an ordinary
-- query. That is a real, separate, out-of-scope defect — it would need
-- touching `clients`' own RLS, a much wider blast radius than one table's
-- Messages tab — and is not fixed here; it is left named rather than
-- silently masked, because SECURITY DEFINER on the helper happens to sidestep
-- it FOR THIS ONE PURPOSE without curing the underlying table.
--
-- RE-RUNNABLE, AND ATOMIC, for 262's own two reasons: the migration runner
-- records each file once but a migration can be re-applied out of band
-- through the Supabase dashboard or MCP (a different tracking table), and
-- apply_migrations.py invokes `psql -f` WITHOUT --single-transaction, so a
-- failure between a DROP and its CREATE would leave a RESTRICTIVE policy
-- dropped — which WIDENS access — with nothing to put it back. BEGIN/COMMIT
-- makes that impossible: the file fully applies or does nothing.
--
-- THE GRANT IS RE-ASSERTED TOO, BELT AND SUSPENDERS
-- The investigation above found the RLS policy is what reproduces the
-- symptom on a clean build of every migration in this tree — but this
-- environment cannot inspect production's actual ACL, and `docs/schema-drift.md`
-- already documents grants drifting from what their own migrations declare
-- independently of any RLS question (migration 194's whole premise). Idempotent
-- and harmless either way, so both are re-declared here rather than debated.

BEGIN;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.portal_messages TO authenticated;
GRANT ALL ON public.portal_messages TO service_role;

CREATE OR REPLACE FUNCTION public.my_portal_client_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT client_id FROM public.client_portal_users
   WHERE auth_user_id = auth.uid() AND status = 'active'
  UNION
  SELECT id FROM public.clients
   WHERE portal_user_id = auth.uid()
$$;

REVOKE EXECUTE ON FUNCTION public.my_portal_client_ids() FROM PUBLIC, anon;
GRANT  EXECUTE ON FUNCTION public.my_portal_client_ids() TO authenticated;

-- The BARE NAME is kept alive, narrowed from FOR ALL to FOR UPDATE, with its
-- predicate unchanged — see the header note on why the name itself, not just
-- the rule it carries, has to survive. This is the one command that does not
-- need the portal-client branch.
DROP POLICY IF EXISTS "portal_messages_assignment_scope" ON public.portal_messages;
CREATE POLICY "portal_messages_assignment_scope" ON public.portal_messages
  AS RESTRICTIVE FOR UPDATE
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS "portal_messages_assignment_scope_select" ON public.portal_messages;
CREATE POLICY "portal_messages_assignment_scope_select" ON public.portal_messages
  AS RESTRICTIVE FOR SELECT
  USING (
    public.can_access_client(client_id::text)
    OR client_id IN (SELECT public.my_portal_client_ids())
  );

DROP POLICY IF EXISTS "portal_messages_assignment_scope_insert" ON public.portal_messages;
CREATE POLICY "portal_messages_assignment_scope_insert" ON public.portal_messages
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (
    public.can_access_client(client_id::text)
    OR client_id IN (SELECT public.my_portal_client_ids())
  );

DROP POLICY IF EXISTS "portal_messages_assignment_scope_delete" ON public.portal_messages;
CREATE POLICY "portal_messages_assignment_scope_delete" ON public.portal_messages
  AS RESTRICTIVE FOR DELETE
  USING (public.can_access_client(client_id::text));

COMMIT;
