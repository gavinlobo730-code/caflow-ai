-- Migration 337: the published anon key could read a client's cash payments,
-- read the whole schema, and write to a conversation it does not own.
--
-- WHAT IS EXPOSED
-- Twelve SECURITY DEFINER functions in `public` are executable by `anon`,
-- confirmed against the live database with
--
--     SELECT p.proname, p.proacl,
--            has_function_privilege('anon', p.oid, 'EXECUTE')
--       FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
--      WHERE n.nspname = 'public' AND p.prosecdef;
--
-- Almost none of them carries an explicit grant to `anon`. They carry
-- `=X/postgres` or a NULL acl, which are both the EXECUTE-to-PUBLIC that
-- CREATE FUNCTION gives away by default, and `anon` is a member of PUBLIC.
-- That is why this migration revokes FROM PUBLIC and not only FROM anon:
-- migration 141 already recorded that lesson the expensive way — 089/090 ran
-- `REVOKE ... FROM anon, authenticated` against a privilege that came from
-- PUBLIC, so the revoke was a no-op and the function stayed reachable.
--
-- The anon key is not a secret. It is inlined into the browser bundle by
-- design (apps/web/wrangler.toml, NEXT_PUBLIC_SUPABASE_ANON_KEY) because RLS is
-- what protects the data — and RLS does not run inside a SECURITY DEFINER
-- function. So for the seven revoked below, anyone who has opened the app in a
-- browser held enough to call them. This is migration 272's finding again, in
-- the read direction.
--
-- ── THE ONE THAT MATTERS ────────────────────────────────────────────────────
--     get_cash_payments_above_threshold(p_firm_id uuid, p_client_id uuid,
--                                       p_threshold_paise bigint)
--
-- It takes the TENANT AS AN ARGUMENT and makes no caller-identity check at all
-- (migration 288). Given a firm id and a client id, it returns that client's
-- cash payments: narration, date, amount and the counterparty account on the
-- other leg. Client UUIDs appear in URLs, so they are not secret in the way
-- this design assumes, and a firm id is on every row the app has ever shown.
-- It is a §40A(3) review list — the payments a CA is about to be asked to
-- disallow — which is close to the most sensitive read in the ledger.
--
-- SHOULD IT DERIVE THE FIRM FROM THE CALLER INSTEAD? It should NOT, and this
-- migration deliberately does not change its signature. The only caller is
-- domain/income_tax/computation_workspace.auto_detect_40a3, which reaches it
-- through core.supabase_client.get_supabase() — the SERVICE role in the normal
-- deployment, where auth.uid() is NULL. A firm derived from the caller would
-- therefore be NULL on every real call and the scan would return nothing,
-- silently, which is the failure mode migration 288 exists to end. The tenant
-- argument is legitimate BECAUSE the caller is the API, which has already run
-- rbac() and assert_client_access; what was wrong is that an unauthenticated
-- role could be that caller. Restricting EXECUTE fixes exactly that, and a
-- caller-derived guard is a separate change that needs its own tests and a
-- decision about the service-role path. tests/test_s40a3_detection_pg.py calls
-- the function directly as the migration role and is unaffected either way.
--
-- ── WHAT IS REVOKED (7) ─────────────────────────────────────────────────────
--   get_cash_payments_above_threshold(uuid, uuid, bigint)
--       above. Reads ledger rows for a tenant named in the arguments.
--   get_public_columns()  /  get_public_schema_columns()
--       every (table, column) pair in the public schema. Read-only and no row
--       data, but it is the reconnaissance step for everything else, and the
--       only caller is core/schema_guard.py on the service-role client at boot
--       (migrations 242 and 265 say so in their own headers).
--   increment_message_count(uuid)
--       a WRITE. It UPDATEs public.ai_conversations for any conversation id,
--       as the owner, with RLS bypassed. Called only by
--       repositories/ai_copilot_repository.py.
--   is_client_fy_locked(uuid, uuid, date)
--       firm and client are arguments, same shape as the cash scan. It has NO
--       caller anywhere in apps/api or apps/web — checked — so nothing can
--       break; it is revoked because a tenant-argument SECURITY DEFINER
--       function reachable by anon is the pattern, not the one instance.
--   payroll_declaration_guard_verified_columns()
--   payroll_declaration_item_guard_verified_columns()
--       both RETURNS TRIGGER (migration 297). A trigger function cannot be
--       invoked as an RPC, and PostgreSQL checks EXECUTE on it when the
--       TRIGGER IS CREATED rather than when it fires, so revoking cannot stop
--       the employee-declaration guards from running. They are here to clear
--       the advisor rather than to close a live hole.
--
-- ── WHAT IS DELIBERATELY LEFT ALONE (5) ─────────────────────────────────────
-- can_access_client(text), get_my_role(), get_my_user_id(),
-- my_internal_client_id(), my_role_at_least(text).
--
-- These are the RLS PREDICATES. Two reasons, and the second is the decisive
-- one:
--
--   1. THEY LEAK NOTHING. Every one of them answers a question about the
--      CALLER — what is my role, what is my internal user id, may I see this
--      client. What comes back is a boolean or the caller's own id, never a
--      row belonging to a tenant, which is the whole difference from
--      get_cash_payments_above_threshold. can_access_client does take a
--      client id, and that is the one to look at twice: it is the id being
--      ASKED ABOUT, not a key that unlocks anything, and the answer is a
--      yes/no about the caller. Called by `anon`, auth.uid() is NULL, so
--      get_my_role() is NULL, my_role_at_least is false (role_rank(NULL) = -1,
--      which outranks nothing), and can_access_client is false for any real
--      client id. There is no answer to extract, and no way to turn one into a
--      row.
--
--   2. REVOKING WOULD BREAK, NOT DENY. The policies that call them were
--      written with no TO clause — clients_assignment_scope (084) and the
--      nine RESTRICTIVE write policies of migration 260 — so they apply to
--      EVERY role, `anon` included. `anon` still holds SELECT on two views
--      (public.clients_external from migration 073, public.salary_slips from
--      072, both confirmed live), whose underlying tables carry exactly those
--      policies. A role that lacks EXECUTE does not get "no rows"; it gets
--      `permission denied for function`, a 42501 error out of a policy that
--      was supposed to be a quiet denial. Migration 260 granted
--      my_role_at_least and role_rank to `anon` EXPLICITLY, for this reason;
--      undoing that here would be reversing a deliberate decision from the
--      outside.
--
-- The frontend calls no RPC at all — `grep -rn '\.rpc(' apps/web` outside
-- node_modules is zero, still true — and the public tokenised pages
-- (routers/engagement_sign_public.py and the portal routers) run on the
-- SERVICE role, not on anon. So nothing in the product loses a call it makes.
--
-- ── role_rank: a mutable search_path ────────────────────────────────────────
-- public.role_rank(text) has proconfig NULL. It is SECURITY INVOKER and its
-- body is a CASE over a literal, so the practical risk is small — but it is
-- called from inside my_role_at_least, which IS SECURITY DEFINER, and every
-- RESTRICTIVE write policy of migration 260 goes through the pair. Pinned with
-- ALTER FUNCTION, which does not rewrite the body, exactly as migration 144
-- pinned the other RLS helpers.
--
-- ── NOT FIXABLE FROM A MIGRATION ────────────────────────────────────────────
-- Supabase Auth's leaked-password protection (HaveIBeenPwned check on sign-up
-- and password change) is OFF. It is a project setting in the Supabase
-- dashboard — Authentication → Policies → Password protection — and there is
-- no SQL for it. Reported rather than fixed.
--
-- Idempotent, and safe to re-run.

BEGIN;

-- ── 1. Revoke PUBLIC (and therefore anon) on the seven ──────────────────────
-- FROM PUBLIC is the one that does the work; FROM anon is stated as well so a
-- future explicit grant to anon cannot reintroduce this quietly, and so the
-- intent reads off the file. Both are no-ops when already applied.

REVOKE EXECUTE ON FUNCTION public.get_cash_payments_above_threshold(uuid, uuid, bigint)
  FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_cash_payments_above_threshold(uuid, uuid, bigint)
  FROM anon;

REVOKE EXECUTE ON FUNCTION public.get_public_columns()        FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_public_columns()        FROM anon;

REVOKE EXECUTE ON FUNCTION public.get_public_schema_columns() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_public_schema_columns() FROM anon;

REVOKE EXECUTE ON FUNCTION public.increment_message_count(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.increment_message_count(uuid) FROM anon;

REVOKE EXECUTE ON FUNCTION public.is_client_fy_locked(uuid, uuid, date) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.is_client_fy_locked(uuid, uuid, date) FROM anon;

REVOKE EXECUTE ON FUNCTION public.payroll_declaration_guard_verified_columns()      FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.payroll_declaration_guard_verified_columns()      FROM anon;

REVOKE EXECUTE ON FUNCTION public.payroll_declaration_item_guard_verified_columns() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.payroll_declaration_item_guard_verified_columns() FROM anon;

-- ── 2. Re-grant the roles that legitimately call them ───────────────────────
-- Explicitly, rather than inherited from PUBLIC, so a later REVOKE ... FROM
-- PUBLIC somewhere else cannot quietly take the API's own access away with it.
-- Same shape migrations 271 and 272 used. The two trigger functions get the
-- grant back too: nothing calls them by name, but a re-run of migration 297's
-- CREATE TRIGGER under a non-owner role would need it, and a trigger that
-- refuses to be created is a guard that silently stops existing.

GRANT EXECUTE ON FUNCTION public.get_cash_payments_above_threshold(uuid, uuid, bigint)
  TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.get_public_columns()           TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.get_public_schema_columns()    TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.increment_message_count(uuid)  TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.is_client_fy_locked(uuid, uuid, date)
  TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.payroll_declaration_guard_verified_columns()
  TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.payroll_declaration_item_guard_verified_columns()
  TO authenticated, service_role;

-- ── 3. Pin role_rank's search_path ──────────────────────────────────────────
ALTER FUNCTION public.role_rank(text) SET search_path = public, pg_catalog;

-- ── 4. Invariant: the seven are actually gone from anon ─────────────────────
-- A REVOKE that silently did nothing is exactly the failure migration 141
-- documented, and it looks identical to a successful one in a migration log.
-- This makes the difference loud. The five RLS predicates are NOT asserted
-- here — they are meant to stay reachable, and asserting that they do would
-- freeze a decision that belongs in prose above, not in a constraint.
DO $$
DECLARE
  sig      text;
  still    text[] := '{}';
  sigs     text[] := ARRAY[
    'public.get_cash_payments_above_threshold(uuid, uuid, bigint)',
    'public.get_public_columns()',
    'public.get_public_schema_columns()',
    'public.increment_message_count(uuid)',
    'public.is_client_fy_locked(uuid, uuid, date)',
    'public.payroll_declaration_guard_verified_columns()',
    'public.payroll_declaration_item_guard_verified_columns()'
  ];
BEGIN
  -- The role may legitimately be absent on a plain PostgreSQL that has not
  -- run _supabase_compat_bootstrap.sql; there is nothing to assert then.
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    RAISE NOTICE 'migration 337: role anon not present, skipping the check';
    RETURN;
  END IF;

  FOREACH sig IN ARRAY sigs LOOP
    IF to_regprocedure(sig) IS NOT NULL
       AND has_function_privilege('anon', sig, 'EXECUTE') THEN
      still := still || sig;
    END IF;
  END LOOP;

  IF array_length(still, 1) IS NOT NULL THEN
    RAISE EXCEPTION 'migration 337: anon can still EXECUTE: %',
      array_to_string(still, ', ');
  END IF;
END $$;

COMMIT;


-- ═══════════════════════════════════════════════════════════════════════════
-- 5. RECOMMENDED, NOT DONE HERE — three leftover working tables on production.
--
-- THIS MIGRATION CHANGES NOTHING BELOW THIS LINE. It is a note for the owner,
-- and the three statements at the end of it are the whole of the change if the
-- owner decides to make it. Merging to `main` applies a migration to the live
-- database with no human review step in between (docs/deploy-migrations.md), a
-- DROP TABLE is irreversible, and dropping production tables is not something
-- to do as a side effect of a security fix.
--
-- WHAT THEY ARE
--     public._backup_247_invoices        736 kB
--     public._backup_247_journal_lines     4 MB
--     public._mig247_targets             904 kB
--
-- Created by hand while migrations 247 and 248 were being applied — 247 made
-- invoice round-off opt-in, 248 retro-fitted the existing ledger — as the
-- before-copies and the working set for that correction.
--
-- THEY ARE LITTER, NOT AN EXPOSURE. All three have RLS ENABLED and NO POLICY,
-- so they are already unreadable through PostgREST by anyone but the service
-- role, which bypasses RLS anyway. Nothing reaches them: they appear in no
-- router, no repository and no frontend select list.
--
-- WHAT MAKES THEM WORTH REMOVING IS THE DRIFT, NOT THE RISK. No migration in
-- this repository creates them — the strings appear nowhere in migrations/,
-- checked — so they exist only on the live database, outside the schema the
-- repo describes, and every schema-drift comparison in tests/fixtures has to
-- keep accounting for them (docs/schema-drift.md).
--
-- ⚠️ DO NOT RUN THIS AGAINST REAL BOOKS. Production carries dummy data today
-- (seven fabricated clients), so the pre-correction copies protect nothing. A
-- backup of pre-correction journal lines is evidence of an edit to the general
-- ledger, and Companies Act s.128(5) with Rule 3(1) of the Companies (Accounts)
-- Rules 2014 wants that kind of record kept, not dropped. Once this deployment
-- holds a real client's books, the answer to this note becomes "no".
--
-- Nothing recreates them if they go: no migration defines their shape, so no
-- rollback in this repository can restore them. That asymmetry is the reason
-- they are a recommendation here rather than three statements above.
--
--     DROP TABLE IF EXISTS public._backup_247_invoices;
--     DROP TABLE IF EXISTS public._backup_247_journal_lines;
--     DROP TABLE IF EXISTS public._mig247_targets;
