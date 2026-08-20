-- Migration 272: the published anon key could execute three SECURITY DEFINER
-- write functions.
--
-- WHAT IS EXPOSED
-- Three atomic write RPCs are SECURITY DEFINER, and all three grant EXECUTE to
-- PUBLIC — which includes `anon`:
--
--     numbered_document_atomic     acl: =X/postgres ...   SECURITY DEFINER
--     settle_receipt_atomic        acl: =X/postgres ...   SECURITY DEFINER
--     record_fee_receipt_atomic    acl: NULL (= PUBLIC)   SECURITY DEFINER
--
-- `=X/postgres` is a grant to PUBLIC. A NULL acl is the same thing by default.
-- SECURITY DEFINER runs as the owner, so each one writes with the owner's
-- privileges and bypasses RLS entirely.
--
-- The anon key is not a secret. It is inlined into the browser bundle by design
-- (apps/web/wrangler.toml, NEXT_PUBLIC_SUPABASE_ANON_KEY) because RLS is what
-- protects the data. That reasoning holds only for paths where RLS actually
-- runs, and it does not run inside a SECURITY DEFINER function. So anyone who
-- opened the app in a browser held enough to call all three.
--
-- WHAT EACH ONE WOULD HAVE ALLOWED
--   * numbered_document_atomic(p_header_table text, p_header jsonb,
--     p_lines_table text, p_lines jsonb, p_lines_fk_column text)
--     — the caller names the TABLE. quote_ident() stops SQL injection of the
--     identifier but not the choice of identifier, so this is an arbitrary
--     INSERT into any table in the public schema, as the owner, with RLS off.
--     This is the worst of the three by some distance.
--   * settle_receipt_atomic — writes a receipt, a journal entry, its lines and
--     the allocations, all from raw jsonb the caller supplies.
--   * record_fee_receipt_atomic(p_firm_id uuid, ...) — the firm is a plain
--     parameter, so any firm's fee receipts.
--
-- 271 revoked PUBLIC on post_journal_atomic as part of making it SECURITY
-- DEFINER, and said these three needed their own migration. This is it.
--
-- WHY A REVOKE IS SAFE HERE
-- Nothing calls these anonymously. Every call site is backend service code
-- running as `authenticated` (USE_USER_JWT) or `service_role`:
--
--     numbered_document_atomic   services/numbering.py
--     settle_receipt_atomic      services/receipt_service.py
--     record_fee_receipt_atomic  services/fee_billing_service.py
--
-- The frontend makes no .rpc() calls at all — checked across apps/web, the
-- count is zero; its direct Supabase access is .from(...).select(...) on tables.
-- The public/unauthenticated routers (engagement_sign_public, portal_data,
-- portal_self) touch none of the three.
--
-- WHAT THIS DOES NOT DO
-- It does not add a tenant guard. Once EXECUTE is limited to `authenticated`,
-- a logged-in user of firm A can still call these with firm B's identifiers,
-- because SECURITY DEFINER means no RLS policy will stop them — the same gap
-- 271 closed for post_journal_atomic by restating its policies in the body.
-- That fix is per-function, needs its own tests, and in settle_receipt_atomic's
-- case means reproducing a 169-line body to prepend a guard. Bundling it into a
-- migration whose whole value is being small and obviously-correct would trade
-- a certain fix for a risky one. It is the next piece of work, not this one.
--
-- What this migration does buy, on its own: the attack requires an account in
-- the system rather than a copy of a key that ships to every visitor.
--
-- Idempotent, and safe to re-run.

-- ── numbered_document_atomic ────────────────────────────────────────────────
REVOKE EXECUTE ON FUNCTION public.numbered_document_atomic(
  text, jsonb, text, jsonb, text
) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.numbered_document_atomic(
  text, jsonb, text, jsonb, text
) FROM anon;

-- ── settle_receipt_atomic ───────────────────────────────────────────────────
REVOKE EXECUTE ON FUNCTION public.settle_receipt_atomic(
  jsonb, jsonb, jsonb, jsonb
) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.settle_receipt_atomic(
  jsonb, jsonb, jsonb, jsonb
) FROM anon;

-- ── record_fee_receipt_atomic ───────────────────────────────────────────────
-- This one's acl is NULL, i.e. PUBLIC EXECUTE inherited from the default. The
-- REVOKE is what materialises an explicit acl in the first place.
REVOKE EXECUTE ON FUNCTION public.record_fee_receipt_atomic(
  uuid, uuid, date, bigint, text, text, text
) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.record_fee_receipt_atomic(
  uuid, uuid, date, bigint, text, text, text
) FROM anon;

-- ── Re-grant the two roles that legitimately call them ──────────────────────
-- Explicit rather than inherited from PUBLIC, so a future REVOKE ... FROM
-- PUBLIC elsewhere cannot quietly take the API's own access away with it. This
-- is the same shape 271 used for post_journal_atomic.
GRANT EXECUTE ON FUNCTION public.numbered_document_atomic(
  text, jsonb, text, jsonb, text
) TO authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.settle_receipt_atomic(
  jsonb, jsonb, jsonb, jsonb
) TO authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.record_fee_receipt_atomic(
  uuid, uuid, date, bigint, text, text, text
) TO authenticated, service_role;
