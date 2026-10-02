-- Migration 475: the names of the functions in `public`, for the boot-time schema guard (ops-19).
--
-- WHY
--     core/schema_guard.py checks that the database has what the deployed code
--     calls. It knew columns (from `ADD COLUMN IF NOT EXISTS`) and, from ops-19, tables
--     (from the same single-row read of the columns). A function was invisible: code that
--     calls `.rpc("post_journal_atomic", ...)` against a database that does not have it
--     passed every check and failed on first use, which for a posting function is a
--     refused posting with a generic error. There is no PostgREST call that lists
--     functions, so the guard needs one of its own.
--
-- THE SAME SHAPE AS 265, AND FOR THE SAME REASON
--     One jsonb row, so the ~1000-row cap on a PostgREST response cannot cut it, and
--     `total_functions` is counted apart from the list so the caller can PROVE it received
--     everything (the failure 265 repaired was a capped read that looked complete).
--     Names, not signatures: the guard asks "does a function by this name exist", the only
--     question the code's `.rpc("name")` call can be held to; overloads collapse to one
--     name and the count is of DISTINCT names so the two agree.
--
-- WHAT IS LEFT OUT
--     Functions that belong to an extension (pg_depend deptype 'e'): pgcrypto, uuid-ossp and
--     the rest are not something a migration of ours creates or the code calls through
--     `.rpc()`, and in a plain-Postgres database built for CI they can land in `public`.
--     Aggregates and window functions (prokind 'a' / 'w'): PostgREST exposes neither.
--
-- WHO MAY CALL IT
--     `service_role` ONLY. The boot thread has no caller token, so it asks as the service
--     client. The list of every function name in the schema is not something a signed-in
--     member or the published anon key needs, and CREATE FUNCTION gives EXECUTE to PUBLIC
--     by default (and Supabase's default privileges add anon and authenticated), so each
--     is revoked by name: `REVOKE ... FROM anon` alone is a no-op against a privilege that
--     came from PUBLIC, which migration 141 recorded the hard way.
--
-- ADDITIVE: a new name, so no earlier definition is replaced. Rollback drops it; the
-- guard then reports the function half as "not checked", never as drift.

BEGIN;

CREATE OR REPLACE FUNCTION public.get_public_schema_functions()
RETURNS jsonb
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
STABLE
AS $$
  SELECT jsonb_build_object(
    -- Counted independently of the list below, and as DISTINCT names so an overloaded
    -- function is one name on both sides.
    'total_functions', (
      SELECT count(DISTINCT p.proname)
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
      WHERE n.nspname = 'public'
        AND p.prokind IN ('f', 'p')
        AND NOT EXISTS (
          SELECT 1 FROM pg_depend d
          WHERE d.classid = 'pg_proc'::regclass
            AND d.objid = p.oid
            AND d.deptype = 'e'
        )
    ),
    'functions', COALESCE((
      SELECT jsonb_agg(q.name ORDER BY q.name)
      FROM (
        SELECT DISTINCT p.proname::text AS name
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND p.prokind IN ('f', 'p')
          AND NOT EXISTS (
            SELECT 1 FROM pg_depend d
            WHERE d.classid = 'pg_proc'::regclass
              AND d.objid = p.oid
              AND d.deptype = 'e'
          )
      ) q
    ), '[]'::jsonb)
  );
$$;

COMMENT ON FUNCTION public.get_public_schema_functions() IS
    'Read-only introspection for the boot-time schema-drift guard (core/schema_guard.py, ops-19). '
    'Returns ONE jsonb row: {"total_functions": int, "functions": [name, ...]} — the distinct names '
    'of the non-extension functions and procedures in public. Single-row on purpose (a row-per-name '
    'function would be cut by PostgREST''s row cap); total_functions lets the caller prove it '
    'received the whole list. service_role only.';

REVOKE ALL ON FUNCTION public.get_public_schema_functions() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.get_public_schema_functions() FROM anon;
REVOKE ALL ON FUNCTION public.get_public_schema_functions() FROM authenticated;
GRANT EXECUTE ON FUNCTION public.get_public_schema_functions() TO service_role;

COMMIT;
