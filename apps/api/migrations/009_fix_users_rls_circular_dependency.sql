-- Migration 009: Fix the circular RLS dependency on the users table
-- ROOT CAUSE: Migration 005 created policy "users_own_firm" ON users
-- USING (firm_id = get_my_firm_id()) — this calls get_my_firm_id() which reads
-- FROM users, triggering the same policy → infinite loop → "permission denied"
--
-- Migration 007 dropped "users_own_row" (which didn't exist yet) and re-created it,
-- but never dropped the original broken "users_own_firm" policy.
-- So the bad policy has been in place the whole time.
--
-- FIX: Drop both old policies, create a single clean one using auth.uid() directly.

-- Step 1: Drop the broken circular policy (from migration 005)
DROP POLICY IF EXISTS "users_own_firm" ON users;

-- Step 2: Drop any duplicate fix attempts (from migration 007 and 008)
DROP POLICY IF EXISTS "users_own_row" ON users;

-- Step 3: Create the correct policy — direct auth.uid() check, no function call
-- (select auth.uid()) evaluated once per query, not per row
CREATE POLICY "users_own_row" ON users
  FOR ALL USING (auth_user_id = (SELECT auth.uid()));

-- Step 4: Ensure get_my_firm_id is hardened (idempotent — safe to re-run)
CREATE OR REPLACE FUNCTION get_my_firm_id()
RETURNS UUID
LANGUAGE SQL
SECURITY DEFINER
STABLE
SET search_path = pg_catalog, public
AS $$
  SELECT firm_id FROM public.users WHERE auth_user_id = (SELECT auth.uid()) LIMIT 1;
$$;

REVOKE EXECUTE ON FUNCTION get_my_firm_id() FROM anon;
GRANT EXECUTE ON FUNCTION get_my_firm_id() TO authenticated;

-- VERIFY after running:
-- From Supabase Table Editor > users — your row should be visible
-- From SQL Editor with Role = authenticated (if supported): SELECT get_my_firm_id();
-- From browser console: supabase.from('users').select('firm_id') should return your row
