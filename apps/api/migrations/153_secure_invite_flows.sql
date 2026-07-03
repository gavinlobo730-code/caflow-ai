-- 153 — Secure staff and portal invite flows (fixes audit findings F21, F22).
--
-- F21 — /join privilege escalation
-- ---------------------------------
-- apps/web/app/join/page.tsx read firm_id/role/name from URL QUERY PARAMS and, if
-- no pre-invited `users` row matched (email, firm_id), INSERTED a brand-new row
-- with those attacker-controlled values directly from the browser. This is a full
-- account-takeover primitive: ANY authenticated Supabase user (self-signup is
-- open via /signup) can navigate to /join?firm=<any-firm-uuid>&role=Partner and
-- gain Partner-level access (every client of that firm — authz.py's
-- can_access_client returns True for any client_id when firm-wide) to a firm they
-- have no relationship with. RLS did NOT block this: two PERMISSIVE policies
-- applied to INSERT — "users_own_row" (USING auth_user_id = auth.uid(), no
-- firm_id constraint at all) and "partners_can_invite_users" (WITH CHECK
-- firm_id = get_my_firm_id()) — and Postgres ORs multiple permissive policies
-- together, so satisfying the first (trivial — the new row's own auth_user_id
-- always equals the caller's uid) is sufficient regardless of the second.
--
-- Root fix (code, this migration only does the schema/RLS half):
--   * users-row CREATION already goes through the audited, Partner-only backend
--     (routers/identity.py:create_user, RBAC team:write) — that part (M6) was
--     already correct. What was missing was making the LINKING step (binding a
--     Supabase auth_user_id to that pre-created row) go through the backend too,
--     gated by a single-use, expiring, server-issued token — instead of trusting
--     URL params and allowing a raw insert as a fallback. See
--     routers/identity.py:accept_invite.
--   * This migration adds the token/expiry columns AND removes the RLS/grant
--     paths that made the raw browser INSERT possible in the first place, so the
--     vulnerability is closed at the database layer too (defense in depth) — not
--     just by deleting the vulnerable frontend code path.
--
-- F22 — tokenless, auto-binding portal invites
-- ---------------------------------------------
-- services/portal_access_service.py bound ANY client_portal_users invite whose
-- email matched the caller's Supabase session email, on EVERY call to
-- list_portal_memberships (i.e. every portal page load) — no token, no expiry.
-- A recycled or typo'd email address silently grants that stranger the client's
-- invoices, statements and compliance data on first login. Root fix (code): the
-- bind now requires a single-use, expiring token presented explicitly via
-- POST /api/portal/accept-invite (services/portal_access_service.py:accept_portal_invite);
-- list_portal_memberships becomes read-only (no side effects). This migration
-- adds the token/expiry columns portal invites now carry.

-- ── users: invite token + expiry ─────────────────────────────────────────────
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS invite_token TEXT,
  ADD COLUMN IF NOT EXISTS invite_expires_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS uq_users_invite_token
  ON public.users (invite_token) WHERE invite_token IS NOT NULL;

-- ── client_portal_users: invite token + expiry ───────────────────────────────
ALTER TABLE public.client_portal_users
  ADD COLUMN IF NOT EXISTS invite_token TEXT,
  ADD COLUMN IF NOT EXISTS invite_expires_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS uq_client_portal_users_invite_token
  ON public.client_portal_users (invite_token) WHERE invite_token IS NOT NULL;

-- ── users RLS/grant hardening ─────────────────────────────────────────────────
-- Every SECURITY-SENSITIVE users-row mutation (role, firm_id, auth_user_id,
-- status, is_active, invite_token, ...) now happens exclusively via the
-- backend's service-role client (routers/onboarding.py:create_firm,
-- routers/identity.py:create_user/accept_invite/change_role/suspend/...).
-- INSERT is revoked outright — a repo-wide check confirms the frontend has
-- ZERO legitimate `.from("users").insert(...)` call sites; account creation is
-- 100% backend-issued-invite-token gated (see accept_invite above).
--
-- UPDATE is NOT revoked outright: app/settings/page.tsx's "save my display
-- name" feature legitimately does `.from("users").update({full_name}).eq(
-- "auth_user_id", ...)` from the browser, and that is worth preserving rather
-- than migrating to a new backend endpoint for one harmless field. Instead of
-- an all-columns UPDATE grant gated only by a row-level RLS check, this uses a
-- COLUMN-level GRANT: `authenticated` may only ever SET full_name, regardless
-- of RLS. This is deliberately NOT the same mistake as an earlier draft of
-- this migration, which relied solely on an RLS WITH CHECK (auth_user_id =
-- auth.uid()) for an UPDATE policy — verified against a real Postgres that
-- WITH CHECK alone only constrains WHICH ROW may be touched, not which COLUMNS
-- or VALUES, so a caller could still UPDATE their own row's `role` to
-- 'Partner' or `firm_id` to another firm. A column-level GRANT closes that at
-- a layer BELOW RLS: Postgres rejects the entire statement (verified on a real
-- Postgres 16: "permission denied for table users") the moment any ungranted
-- column appears in the SET clause, no matter what the RLS policy's WITH
-- CHECK does or does not constrain.
REVOKE INSERT, UPDATE, DELETE ON public.users FROM authenticated;
GRANT UPDATE (full_name) ON public.users TO authenticated;

DROP POLICY IF EXISTS "partners_can_invite_users" ON public.users;
DROP POLICY IF EXISTS "users_own_row" ON public.users;

-- A user may read their own row (needed to resolve firm_id/role client-side
-- for navigation) and rename themselves — nothing else. No INSERT, no DELETE;
-- every other mutation is backend/service-role only.
CREATE POLICY "users_own_row_select" ON public.users
  FOR SELECT TO authenticated
  USING (auth_user_id = (SELECT auth.uid()));

CREATE POLICY "users_own_row_rename" ON public.users
  FOR UPDATE TO authenticated
  USING (auth_user_id = (SELECT auth.uid()))
  WITH CHECK (auth_user_id = (SELECT auth.uid()));
