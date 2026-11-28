-- Migration 442: a portal client may read their own fee-scope link row.
--
-- SAME BUG SHAPE AS TWO SIBLING FIXES, FOUND WHILE VERIFYING A THIRD
-- Two sibling fixes (written as migrations 438/440 "portal_messages" and 441
-- "customer_payment_links" on unmerged branches at the time this was written)
-- close the identical defect shape: a RESTRICTIVE `<table>_assignment_scope`
-- policy ANDs `public.can_access_client(client_id)` on top of every PERMISSIVE
-- policy, and `can_access_client()` — like `get_my_firm_id()` and
-- `get_my_role()` — is unconditionally FALSE-or-NULL for a portal-CLIENT
-- principal: `core/portal_auth.get_current_portal_client` issues a real
-- Supabase JWT with NO `public.users` row, so every one of those helpers
-- resolves to NULL and RLS treats `NULL OR FALSE OR FALSE` as deny. This
-- migration closes the same shape on `client_firm_customer_links`, found by
-- pattern-searching every table `services/portal_data_service.py` reads.
--
-- `client_firm_customer_links` (migration 073, Guardrail G3
-- "Firm-as-Internal-Client") maps a practice client's own external
-- `client_id` to `internal_customer_id` — the customer row, in the FIRM's own
-- internal-client books, that represents that practice client for fee
-- billing. `services/portal_data_service.resolve_fee_scope(firm_id,
-- client_id, db)` is the FIRST thing called by six portal surfaces —
-- `list_invoices`, `dues`, `invoice_in_scope`, `reminder_history`,
-- `statement` and `statement_pdf` — every one of which does exactly one
-- SELECT against this table: `.eq("firm_id", firm_id).eq("client_id",
-- client_id)`, where `client_id` is `portal["client_id"]`, the PORTAL
-- CLIENT'S OWN external client id (confirmed by reading
-- `core/portal_auth.get_current_portal_client` and every one of
-- `routers/portal_data.py`'s six call sites: each passes
-- `portal["client_id"]` straight through with no other transformation).
-- Under `USE_USER_JWT=true` (unconditionally on in production per
-- render.yaml), `resolve_fee_scope`'s `db` is `core.supabase_client.
-- get_supabase()` — the per-user-JWT client, genuinely RLS-constrained for
-- this session — so before this migration a portal client's Invoices, Dues,
-- Statement and Payment-Reminder tabs silently returned an empty/`None`-shaped
-- result for every real client, with no error: `resolve_fee_scope` reads zero
-- rows, returns `None`, and every caller's own "no scope" branch renders as a
-- calm empty state rather than a failure.
--
-- CONFIRMED AGAINST THE REAL POLICY STACK, NOT ASSUMED FROM migration 073's
-- OWN TEXT
-- 073's own CREATE TABLE declares exactly one policy,
-- `client_firm_customer_links_partner_only` (PERMISSIVE FOR ALL, `firm_id =
-- get_my_firm_id() AND get_my_role() = 'Partner'`) — reading only that file
-- would say this table carries a single PERMISSIVE policy and nothing else.
-- That is not what a database built from every migration in this tree
-- actually has, because two LATER migrations' own dynamic loops also touch
-- this table (it already existed, with a `client_id` column, by the time
-- both ran): migration 074's loop adds
-- `client_firm_customer_links_internal_partner_only` (RESTRICTIVE FOR ALL,
-- `get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM
-- my_internal_client_id()::text` — `client_firm_customer_links` is in 074's
-- own `tbls` array), and migration 084's loop adds
-- `client_firm_customer_links_assignment_scope` (RESTRICTIVE FOR ALL,
-- `can_access_client(client_id::text)` — the table is a BASE TABLE with a
-- `client_id` column and is not in 084's `skip` array). Verified by building
-- a throwaway database from the full migration set and reading
-- `pg_policies`: the real stack is THREE policies, one PERMISSIVE and two
-- RESTRICTIVE — the exact shape `customer_payment_links` had before
-- migration 441, not the one-PERMISSIVE-policy shape a naive read of 073
-- alone would suggest.
--
-- TWO THINGS BLOCK THIS TABLE FOR A PORTAL PRINCIPAL, AND BOTH ARE CONFIRMED
-- (1) `client_firm_customer_links_assignment_scope` is the actual blocker:
--     `can_access_client()` is `p_client_id IS NULL OR get_my_role() =
--     'Partner' OR EXISTS(... JOIN users u ON u.id = a.user_id WHERE
--     u.auth_user_id = auth.uid() ...)` — a portal client has no `users` row,
--     so the EXISTS is FALSE, `get_my_role()` is NULL, and `client_id` on
--     this table is NOT NULL, so the whole expression is `FALSE OR NULL OR
--     FALSE` = NULL = deny.
-- (2) `client_firm_customer_links_internal_partner_only` does NOT need
--     touching, for the identical reason migration 441's header records for
--     the analogous policy on `customer_payment_links`: its OR-branch is
--     `client_id::text IS DISTINCT FROM my_internal_client_id()::text`, and
--     `my_internal_client_id()` reads `firms WHERE id = get_my_firm_id()` —
--     `get_my_firm_id()` is NULL for a portal principal, so that lookup
--     returns no row and the function itself returns NULL. `<anything
--     non-null> IS DISTINCT FROM NULL` is TRUE by the operator's own
--     definition, and `client_id` on this table is `NOT NULL` (073's own
--     CREATE TABLE), so this RESTRICTIVE policy evaluates to `NULL OR TRUE`
--     = TRUE for every row, for any portal principal. Confirmed on the real
--     built database (test below), not merely reasoned from the SQL text.
-- The lone PERMISSIVE policy, `client_firm_customer_links_partner_only`, is
-- ALSO NULL for a portal principal (`get_my_firm_id()` is NULL, so the AND is
-- NULL), so even a widened RESTRICTIVE layer changes nothing without a
-- PERMISSIVE lane that can pass for a portal client — the exact
-- `customer_payment_links` shape (no portal-friendly PERMISSIVE policy at
-- all), not the simpler `portal_messages` shape (which already had one).
--
-- THE ROW'S OWN `client_id` GENUINELY IS THE PORTAL CLIENT'S OWN ID HERE —
-- UNLIKE THE customer_payment_links CASE THIS COULD HAVE COPIED WRONGLY
-- Migration 441's header warns, at length, that mirroring the sibling's
-- `client_id IN (SELECT my_portal_client_ids())` OR-branch onto
-- `customer_payment_links` would have been wrong there, because that table's
-- own `client_id` column is the FIRM's internal-client id (copied off the fee
-- invoice), never the portal client's own id — the portal client's identity
-- surfaces one hop further in, on `customer_id`. `client_firm_customer_links`
-- is not that shape: it is the very table that DEFINES the G3 mapping, so its
-- own `client_id` column (073: "client_id UUID NOT NULL REFERENCES
-- clients(id), -- practice client") IS, by construction, the practice
-- client's own external id — exactly `portal["client_id"]` as
-- `get_current_portal_client` sets it. `resolve_fee_scope` itself confirms
-- this: it is the function that PRODUCES `internal_customer_id` (the value
-- `my_portal_customer_ids()` exists to reach on the far side of this table)
-- FROM the caller's own `client_id`, by querying this table on exactly that
-- column. So `client_id IN (SELECT public.my_portal_client_ids())` — the
-- literal branch this table's investigation asked for — is the right branch
-- HERE, and reusing `my_portal_customer_ids()` (which is defined by composing
-- THROUGH this very table) would be circular: that helper's own body is
-- `SELECT internal_customer_id FROM client_firm_customer_links WHERE
-- client_id IN (SELECT my_portal_client_ids())`, so a policy on this table
-- that called it would make an RLS check on `client_firm_customer_links`
-- depend on reading `client_firm_customer_links` again to answer it.
-- `my_portal_client_ids()` is SECURITY DEFINER precisely so it never touches
-- this table (or any RLS-governed one) at all — it reads only
-- `client_portal_users` and `clients`.
--
-- ONLY SELECT NEEDS WIDENING
-- `resolve_fee_scope` is a SELECT and nothing else. Every writer of this
-- table is staff-only and Partner-gated: `services/billing_service.
-- ensure_customer_link` (its module docstring: "Partner-only (G1): billing
-- endpoints require the Partner/Owner role") is the ONLY INSERT, and no
-- caller anywhere touches it from a portal-authenticated route (grep
-- `client_firm_customer_links` across `routers/` and `services/` — the only
-- readers/writers are `billing_service.py`, staff-only, and
-- `portal_data_service.resolve_fee_scope`, a SELECT). So INSERT, UPDATE and
-- DELETE keep `can_access_client(client_id::text)` exactly as migration 084's
-- loop declared it — widening a write no portal caller can even reach would
-- be exactly the migration-380-documented mistake of opening a write ahead of
-- the feature that needs it.
--
-- THE 262 SHAPE (CLEAN DROP), NOT THE portal_messages SHAPE (KEEP THE BARE
-- NAME ALIVE)
-- Migration 294's idempotent restore loop names EIGHT policies by exact name
-- (`policyname = tablename || '_assignment_scope'` or `'_internal_partner_
-- only'`) for a table list that does NOT include `client_firm_customer_links`
-- — checked directly against 294's own `VALUES` list
-- (client_health_overrides, client_health_scores, government_notices ×2,
-- gstr2b_uploads ×2, portal_messages, year_end_adjustments). So, unlike
-- `portal_messages_assignment_scope`, there is no future out-of-band re-run
-- of 294 that could recreate `client_firm_customer_links_assignment_scope` by
-- that name if it stops existing — the FOR ALL RESTRICTIVE policy is DROPPED
-- outright and replaced by four per-command ones, migration 262's shape (the
-- same reasoning migration 441 gives for taking that shape on
-- `customer_payment_links`, which is also absent from 294's list).
--
-- VERIFIED ON A REAL DATABASE BUILT FROM THE FULL MIGRATION SET
-- Reproduced end to end: `SET request.jwt.claims`/`SET ROLE authenticated`
-- with a portal contact's own JWT claim, a seeded firm with an internal
-- client, two practice (portal) clients each linked to their own customer row
-- in the internal client's books, and a `client_portal_users` row per portal
-- client. Before this migration, the portal client's own SELECT against its
-- own row returns ZERO rows (RLS deny, not an error — a `SELECT` a
-- RESTRICTIVE policy blocks is silent, exactly like `portal_messages` before
-- 440/294). After, it returns exactly its own row, a different portal
-- client's SELECT still returns zero, and an unassigned staff member still
-- sees nothing — see tests/test_r442_portal_client_reads_own_fee_scope_pg.py.
--
-- BELT AND SUSPENDERS
-- Grants re-asserted idempotently, unchanged from migration 073's own
-- declaration — this environment cannot inspect production's actual ACL, and
-- grants have drifted from their own migrations independently of any RLS
-- question before (migration 194's whole premise).
--
-- ATOMIC, FOR THE SAME REASON AS BOTH SIBLING FIXES
-- `apply_migrations.py` invokes `psql -f` WITHOUT --single-transaction, so a
-- failure partway through a DROP-then-CREATE sequence must not leave the
-- RESTRICTIVE policy dropped with nothing yet in its place. BEGIN/COMMIT
-- makes that impossible: the file fully applies or does nothing.
--
-- ⚠️ MIGRATION-NUMBER COLLISION RISK, FLAGGED FOR WHOEVER INTEGRATES THIS
-- This worktree's own migrations directory tops out at 437 (the sibling
-- portal_messages/customer_payment_links fixes exist only on unmerged
-- branches, numbered 438/440 and 441 there). This file is deliberately
-- numbered 442 — one past 441 — rather than 438, the numerically "next free"
-- slot in THIS worktree alone, specifically to avoid colliding with those two
-- unmerged siblings once all three land. Re-check `ls apps/api/migrations`
-- on the actual merge target before this lands and renumber if 442 has since
-- been claimed by other in-flight work.

BEGIN;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_firm_customer_links TO authenticated;
GRANT ALL ON public.client_firm_customer_links TO service_role;

-- Declared VERBATIM as both sibling fixes declare it (SECURITY DEFINER,
-- reading BOTH the multi-contact link — client_portal_users, migration 109 —
-- and the legacy single-user link — clients.portal_user_id, migration 048) so
-- that whichever migration lands first in the merged history, `CREATE OR
-- REPLACE FUNCTION` leaves the others' re-declaration a harmless no-op: all
-- three name the same global function with the same body.
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

-- The portal-client lane: this table (like customer_payment_links, and
-- unlike portal_messages) never had a PERMISSIVE policy a portal principal
-- could satisfy at all. FOR SELECT only — see the header on why nothing else
-- needs widening.
DROP POLICY IF EXISTS "client_firm_customer_links_portal_client_select" ON public.client_firm_customer_links;
CREATE POLICY "client_firm_customer_links_portal_client_select" ON public.client_firm_customer_links
  FOR SELECT TO authenticated
  USING (client_id IN (SELECT public.my_portal_client_ids()));

-- The FOR ALL restrictive policy is DROPPED outright (the 262 shape — see the
-- header on why this table, unlike portal_messages, has no bare name to keep
-- alive) and replaced by four per-command ones. Only SELECT gains the
-- portal-client OR-branch.
DROP POLICY IF EXISTS "client_firm_customer_links_assignment_scope" ON public.client_firm_customer_links;

CREATE POLICY "client_firm_customer_links_assignment_scope_select" ON public.client_firm_customer_links
  AS RESTRICTIVE FOR SELECT
  USING (
    public.can_access_client(client_id::text)
    OR client_id IN (SELECT public.my_portal_client_ids())
  );

CREATE POLICY "client_firm_customer_links_assignment_scope_insert" ON public.client_firm_customer_links
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "client_firm_customer_links_assignment_scope_update" ON public.client_firm_customer_links
  AS RESTRICTIVE FOR UPDATE
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

CREATE POLICY "client_firm_customer_links_assignment_scope_delete" ON public.client_firm_customer_links
  AS RESTRICTIVE FOR DELETE
  USING (public.can_access_client(client_id::text));

COMMIT;
