-- Migration 526 — the assignment scope reads the caller's clients once per query, not once per row
-- (POST-A-297, found while measuring migration 525).
--
-- THE PROBLEM, MEASURED
--
--   Migration 084 gave the tables that then had a `client_id` a RESTRICTIVE `<table>_assignment_scope` policy,
--   `can_access_client((client_id)::text)`, and later migrations wrote the same call into policies of their own (per-command
--   and portal-composite ones): a Partner sees every client, anyone else sees the clients they are assigned
--   to. `can_access_client` is a SQL function that is SECURITY DEFINER with a `SET search_path`, so Postgres cannot inline
--   it, and it takes the ROW's client, so (unlike the helpers migration 525 wrapped) it cannot be hoisted out of the row
--   either. It is called once for every row a query touches, and each call is a function call plus `get_my_role()`,
--   `get_my_user_id()` and, for anyone who is not a Partner, an `EXISTS` query on `user_client_assignments`.
--
--   Measured on this repository's migrated schema, 100,000 rows, `SELECT count(*)` as a signed-in session (what a browser
--   read over PostgREST is, and what the API is when USE_USER_JWT is on), firm policy already wrapped (525):
--
--       Partner                  13,232 ms today      ->   12 to 30 ms as a set    (all 100,000 rows returned)
--       Manager, one client      33,818 ms today      ->   51 ms as a set          (the same 50,000 rows returned)
--
--   so the assignment scope cost about 130 microseconds a row for a Partner and about 340 for everyone else, in every
--   policy that calls it (221 policies on a migrated database, 394 calls: the USING and the WITH CHECK are counted apart,
--   which is the figure migration 525's header gives), on every row a query read before it filtered. A client's journal
--   runs to tens of thousands of lines. These are counts over a synthetic table: no screen has been timed against them.
--
-- WHAT THIS DOES
--
--   1. Adds `public.my_assigned_client_ids()`: the clients the caller is assigned to, as a set of text, the shape of
--      `my_employee_ids()` (migration 262). It is SECURITY DEFINER as `can_access_client` is (migration 084), so that it
--      reads `user_client_assignments` whatever the caller's own grants and policies on that table are, and the rewritten
--      predicate keeps the function's exact posture. (That table is the assignment source and carries no assignment scope
--      of its own: 084 left it out for that reason.) It takes no argument, so it is not one of the argument-taking definer
--      functions that must ask who is calling (migration 486), and it is executable by anon as the other RLS predicates
--      are (see the GRANT below). It answers nothing for a member who is no longer live, because `get_my_user_id()` is
--      NULL for them.
--   2. Rewrites every policy in `public` that calls `can_access_client((<column>)::text)`, in the USING and the WITH
--      CHECK, with `ALTER POLICY`, as
--
--          COALESCE(<column>::text IS NULL
--                   OR (SELECT get_my_role()) = 'Partner'
--                   OR <column>::text IN (SELECT my_assigned_client_ids()), false)
--
--      which is the function's body (`p IS NULL OR role = 'Partner' OR EXISTS (assignment)`) with the row-independent
--      parts evaluated once and the assignment lookup as an uncorrelated `IN (SELECT ...)`, planned as a hashed subplan
--      built once per statement. The `COALESCE(..., false)` keeps the answer a plain true or false, as the function's was
--      (an `IN` over a set holding a NULL would otherwise answer NULL, which a policy treats as false but a `NOT` would
--      not). Nothing else about a policy changes: name, command, roles, the permissive/restrictive kind and the rest of
--      its expression (the portal branches `OR id IN (SELECT my_employee_ids())` and their like) are as they were.
--   3. Closes with a check that no policy in `public` calls `can_access_client` any more, and leaves the function in
--      place: SQL functions and the API call it, and its answer has not changed.
--
--   The meaning is identical. The proof is the role-by-table matrix (tests/test_rls_role_by_table_matrix_pg.py: ten actors
--   x four operations x every table the browser reaches) cell for cell, and the shape test that builds a Partner, a
--   Manager with and without an assignment, an Executive assigned to nothing and a suspended member against rows with and
--   without a client.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--
--   * `can_access_client` itself, and the `storage` schema's policies (the file buckets: the argument there is a folder
--     name, per object, and the schema belongs to the Storage service).
--   * `scripts/db/guard_snapshot.py` folds the new shape back to `can_access_client((<column>)::text)` before hashing a
--     policy, so this rewrite does not read as drift from the production snapshot; a real change to WHO a policy admits
--     still changes the hash.
--
-- LOCKS. `ALTER POLICY` takes an ACCESS EXCLUSIVE lock on its table and the migration is one transaction, so every table
-- it touches is locked until it commits (half a second for 800 policies in migration 525's measurement). A lock_timeout of
-- 15 seconds for this transaction makes a long-running transaction fail the migration, to be re-run, instead of queueing
-- every later request on the table behind it.
--
-- Idempotent (a second run finds no `can_access_client` call to rewrite). Reversible:
-- 526_..._rollback.sql puts the function call back, which costs the speed and nothing else.

CREATE OR REPLACE FUNCTION public.my_assigned_client_ids()
RETURNS SETOF text
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT a.client_id::text
    FROM public.user_client_assignments a
   WHERE a.user_id = public.get_my_user_id()
$$;

-- EXECUTABLE BY EVERY ROLE, anon included, and on purpose: this is an RLS predicate helper, in the class migration 337
-- left alone (can_access_client, get_my_role, get_my_user_id, my_internal_client_id, my_role_at_least). The policies it
-- now sits in were written with no TO clause, so they apply to anon too, wherever anon holds a table privilege (Supabase's
-- default privileges give it one on public tables), and a role without EXECUTE does not get "no rows" from such a policy
-- but `permission denied for function`, a 42501 error out of what was a quiet denial. That is a change of answer, and it
-- was measured: with SELECT granted to anon, 44 tables answered an anonymous count with 0 rows before this migration
-- and with that error after a first draft that revoked it. It leaks nothing: for anon `get_my_user_id()` is NULL, so the
-- function returns no row, and what it would return to a signed-in person is their own assignments.
GRANT EXECUTE ON FUNCTION public.my_assigned_client_ids() TO PUBLIC, anon, authenticated;

DO $$
DECLARE
  r record;
  new_using text;
  new_check text;
  stmt text;
  changed int := 0;
  -- `can_access_client((client_id)::text)` and the same on a qualified or renamed column: `(e.client_id)::text`,
  -- `(client_id_a)::text`, `(id)::text`. The argument is always the column cast to text in a policy (a function of the
  -- row), never a constant.
  pat constant text := 'can_access_client\(\(([a-z_][a-z_0-9.]*)\)::text\)';
  rep constant text := 'COALESCE(((\1)::text IS NULL OR (SELECT public.get_my_role()) = ''Partner''::text OR (\1)::text IN (SELECT public.my_assigned_client_ids())), false)';
BEGIN
  PERFORM set_config('lock_timeout', '15s', true);
  FOR r IN
    SELECT p.polname, c.relname,
           pg_get_expr(p.polqual, p.polrelid)      AS using_expr,
           pg_get_expr(p.polwithcheck, p.polrelid) AS check_expr
      FROM pg_policy p
      JOIN pg_class c      ON c.oid = p.polrelid
      JOIN pg_namespace ns ON ns.oid = c.relnamespace
     WHERE ns.nspname = 'public'
  LOOP
    new_using := regexp_replace(r.using_expr, pat, rep, 'g');
    new_check := regexp_replace(r.check_expr, pat, rep, 'g');
    IF new_using IS DISTINCT FROM r.using_expr OR new_check IS DISTINCT FROM r.check_expr THEN
      stmt := format('ALTER POLICY %I ON public.%I', r.polname, r.relname);
      IF r.using_expr IS NOT NULL THEN
        stmt := stmt || ' USING (' || new_using || ')';
      END IF;
      IF r.check_expr IS NOT NULL THEN
        stmt := stmt || ' WITH CHECK (' || new_check || ')';
      END IF;
      EXECUTE stmt;
      changed := changed + 1;
    END IF;
  END LOOP;
  RAISE NOTICE 'migration 526: % policies now read the caller''s clients once per query', changed;

  -- The closing check: no policy in `public` still calls can_access_client per row.
  SELECT count(*) INTO changed
    FROM pg_policy p
    JOIN pg_class c      ON c.oid = p.polrelid
    JOIN pg_namespace ns ON ns.oid = c.relnamespace
   WHERE ns.nspname = 'public'
     AND (coalesce(pg_get_expr(p.polqual, p.polrelid), '') ~ 'can_access_client'
          OR coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '') ~ 'can_access_client');
  IF changed <> 0 THEN
    RAISE EXCEPTION 'migration 526: % policies still call can_access_client once per row', changed;
  END IF;
END $$;
