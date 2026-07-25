-- Migration 242: schema-introspection RPC for the boot-time schema-drift guard.
--
-- core/schema_guard.py checks, at app startup, that every column the
-- currently-deployed code depends on (per ADD COLUMN IF NOT EXISTS statements
-- across migrations/*.sql) actually exists on THIS database -- the exact gap
-- that let migrations 233-241 sit committed and CI-validated but unapplied
-- against production for up to 6 days while their dependent code was already
-- live (task #244 audit finding; see also 234/241's own docstrings for two of
-- the concrete failures this caused).
--
-- PostgREST does not expose information_schema by default, so the app's
-- normal service-role REST client (core/supabase_client.py's get_supabase())
-- has no way to see its own schema. This SECURITY DEFINER function is the one
-- narrow, read-only window it needs -- no row-level data, just (table,
-- column) pairs for the public schema.
CREATE OR REPLACE FUNCTION public.get_public_columns()
RETURNS TABLE(table_name text, column_name text)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_catalog
STABLE
AS $$
  SELECT c.table_name::text, c.column_name::text
  FROM information_schema.columns c
  WHERE c.table_schema = 'public';
$$;

COMMENT ON FUNCTION public.get_public_columns() IS
    'Read-only schema introspection for the boot-time schema-drift guard (core/schema_guard.py, task #244). Returns every (table, column) pair in the public schema so startup code can detect migrations that were committed but never applied to this database.';

GRANT EXECUTE ON FUNCTION public.get_public_columns() TO authenticated, service_role;
