-- Migration 264: the columns an employee-portal invite needs.
--
-- WHY
--     Migration 262 made the employee portal READABLE — an employee who is
--     linked to a Supabase identity can see their own payslips and leave. It
--     deliberately did not create that link, and its header says so: nothing in
--     the codebase writes payroll_employees.auth_user_id or .portal_enabled, so
--     the portal has always been correct-but-empty. This is the other half.
--
-- THE SHAPE IS COPIED, NOT INVENTED
--     Client-portal invites already solve this exact problem, and migration 153
--     hardened them after a real vulnerability: binding used to happen whenever
--     a session's email matched a row, on every page load — no token, no expiry,
--     no explicit action, so a recycled or typo'd address inherited someone
--     else's data on first login. The fix was a single-use expiring token
--     presented explicitly.
--
--     Employee invites get the same columns and the same unique partial index,
--     so the same service-layer rules apply: 256-bit random token, TTL, cleared
--     on bind, email checked as defence in depth, generic 404 on every failure
--     so it cannot be used as an oracle.
--
-- WHY THE COLUMNS LIVE ON payroll_employees
--     For clients the invite lives on client_portal_users, a row per portal
--     identity. For an employee, payroll_employees IS that row — it already
--     carries auth_user_id and portal_enabled from migration 031. Adding a
--     parallel table would mean two places to look for one fact.
--
-- ABOUT email
--     payroll_employees had no email at all — it stores name, PAN, Aadhaar
--     last-4, UAN and bank details, but no way to reach the person. An invite
--     has to go somewhere, and acceptance checks that the address presented
--     matches the one invited, so the address has to be stored to be compared.
--     Nullable: most employees will never be invited, and payroll works without
--     it. This is a new PII field on employee records — it is deliberately NOT
--     added to any existing SELECT, so nothing starts returning it by accident.

BEGIN;

ALTER TABLE public.payroll_employees
  ADD COLUMN IF NOT EXISTS email                     TEXT,
  ADD COLUMN IF NOT EXISTS portal_invite_token_hash  TEXT,
  ADD COLUMN IF NOT EXISTS portal_invite_expires_at  TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS portal_invited_at         TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS portal_invited_by         UUID,
  ADD COLUMN IF NOT EXISTS portal_activated_at       TIMESTAMPTZ;

COMMENT ON COLUMN public.payroll_employees.email IS
  'Where the portal invite is sent, and the address acceptance is checked against.';
COMMENT ON COLUMN public.payroll_employees.portal_invite_token_hash IS
  'sha256 of the single-use invite token. The token itself is returned once by '
  'the invite endpoint and never stored. Cleared on acceptance.';

-- Unique so a token identifies at most one employee, partial so the many
-- employees with no pending invite do not collide on NULL. Same shape as
-- uq_client_portal_users_invite_token in migration 153.
CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_employees_portal_invite_token
  ON public.payroll_employees (portal_invite_token_hash)
  WHERE portal_invite_token_hash IS NOT NULL;

-- The invite lookup is by token alone and must not scan; the firm+email lookup
-- is how a re-invite finds the existing employee.
CREATE INDEX IF NOT EXISTS idx_payroll_employees_firm_email
  ON public.payroll_employees (firm_id, lower(email))
  WHERE email IS NOT NULL;

-- ─── WHY A HASH, NOT THE TOKEN ───────────────────────────────────────────────
-- payroll_employees is granted to `authenticated` and read directly through
-- PostgREST by firm staff, so anything in a column here is readable by every
-- staff member of the firm.
--
-- The first draft of this migration tried to close that with
--     REVOKE SELECT (portal_invite_token) ON payroll_employees FROM authenticated;
-- That is a NO-OP, and the comment claiming otherwise would have been worse
-- than no comment. Postgres table-level privileges cannot be reduced by a
-- column-level revoke — a column REVOKE only removes a column-level GRANT, and
-- migration 014 granted SELECT on the whole table. Proved on a real instance:
-- after that exact REVOKE, `SET ROLE authenticated; SELECT portal_invite_token`
-- still returns rows. Making it real would mean revoking table SELECT and
-- granting every column individually, which silently un-grants any column added
-- later — a worse trap than the thing it fixes.
--
-- So the token is not stored at all. The invite endpoint mints it, returns it
-- once to the caller who will send it, and stores only sha256(token). Reading
-- this table yields a hash, which cannot be presented to the accept endpoint.
-- This is stronger than the client-portal flow it is otherwise modelled on,
-- where client_portal_users.invite_token holds the live secret in plaintext.
--
-- (Not a preimage concern: the token is 32 random bytes from secrets.token_urlsafe,
-- so there is nothing to guess and no need for a slow KDF or a per-row salt.)

COMMIT;
