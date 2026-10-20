-- Migration 525 — a row-security policy asks who is calling once per QUERY, not once per ROW
-- (found while measuring migration 524's bank-line policies; resolves the measurement half of POST-A-219).
--
-- THE PROBLEM, MEASURED
--
--   A policy such as `firm_id = get_my_firm_id()` or `my_permission('payroll', 'read', 'Manager')` calls a STABLE
--   function whose arguments are constants. Written bare, Postgres calls it once for EVERY ROW the query touches: the
--   planner only evaluates a function once per statement when it is wrapped in a scalar sub-select, `(SELECT fn(...))`,
--   which becomes an InitPlan. These helpers are SQL or plpgsql SECURITY DEFINER functions with a `SET search_path`, so
--   they cannot be inlined either; each call is a function call plus a query on `users` or `user_permissions`.
--
--   Measured on this repository's migrated schema, 100,000 rows, `SELECT count(*)` as a signed-in session (an
--   `authenticated` role with a JWT, which is what a browser read over PostgREST is, and what the API is when
--   USE_USER_JWT is on):
--
--       firm policy `firm_id = get_my_firm_id()`            5,537 ms bare      13 ms wrapped
--       tier policy `my_permission('banking','read',...)`  61,115 ms bare   6,262 ms wrapped (with the firm policy bare)
--
--   so the helper call costs about 55 microseconds a row for the firm policy and about 560 for `my_permission`, on EVERY
--   table that carries one and on EVERY row a query reads before it filters. 603 policy expressions call
--   `get_my_firm_id()`, 339 `my_permission(...)`, 183 `my_role_at_least(...)`, 128 `get_my_role()`, 108
--   `my_internal_client_id()`, 21 `auth.uid()`: every table the browser reads directly, and every API read when the API
--   runs as the caller, paid it on every row. Supabase's own performance advisor names the pattern (`auth_rls_initplan`);
--   migration 008 applied the rewrite to a few `auth.uid()` policies and nothing did it for the rest.
--
-- WHAT THIS DOES
--
--   For every policy in `public`, wraps each call of a helper that takes no argument or only constants in `(SELECT ...)`,
--   in the USING and in the WITH CHECK, with `ALTER POLICY` (name, command, roles and the permissive/restrictive kind are
--   untouched):
--
--       get_my_firm_id()  get_my_role()  get_my_user_id()  my_internal_client_id()
--       my_permission('resource', 'action', 'Role')  my_role_at_least('Role')  auth.uid()  auth.jwt()  auth.role()
--
--   The meaning is identical: each is STABLE and reads the caller's session, so its value cannot differ between two rows
--   of one statement; the sub-select is evaluated once, lazily, the first time a row needs it. The proof of that is not
--   this argument but the role-by-table matrix (tests/test_rls_role_by_table_matrix_pg.py: 101 tables x ten actors x four
--   operations = 4,040 cells) and every other real-Postgres test that signs in as someone, all of which pass unchanged on
--   the rewritten schema, and a shape test that builds one synthetic policy of every shape on a table of its own.
--
--   The rewrite is read from the catalog rather than restated from the migrations that wrote each policy, on purpose:
--   those migrations are a long history of `CREATE POLICY` statements, some replaced by later ones, some with a
--   production-only twin (CLAUDE.md, Migrations), and a rewrite that restated them would have to guess which wording is
--   live. It is idempotent: a call already preceded by `SELECT ` is left alone, so a second run changes nothing, and the
--   closing check fails the migration (and so the deploy) if any bare call survives.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--
--   * `can_access_client((client_id)::text)`, which is called 394 times in 221 policies (the assignment scope, migration 084). It takes
--     the ROW's client, so it cannot be hoisted this way, and it is the larger cost: measured on the same 100,000 rows it
--     is 13,232 ms as a Partner against 12 ms for the equivalent set-based form. That is the next migration, and not a
--     rewrite to make quietly: the function is SECURITY DEFINER so that it can read `user_client_assignments` without
--     recursing into that table's own policies, and a set-based form has to keep that property.
--   * The policies of the `storage` schema (the file buckets), which are owned by the Storage service and are per object.
--   * `my_employee_ids()`, `my_payroll_run_ids()`, `my_portal_*_ids()` and `my_it_declaration_ids()`, which return sets
--     and are already inside `IN (SELECT ...)`.
--   * No function, grant, table, column or row changes. No backfill.
--
-- WHO NOTICES
--
--   Nobody should: every answer is the same. Queries that read many rows as a signed-in session get cheaper by the
--   amounts above. `scripts/db/guard_snapshot.py` hashes policy expressions after folding the `( SELECT auth.uid() AS
--   uid)` form back to `auth.uid()`; it folds every helper above the same way now, so this rewrite does not read as drift
--   from the production snapshot, and a real change to WHO a policy admits still changes the hash. One caveat: the
--   committed snapshot (2026-09-03) was hashed with the old fold, so the two policies migration 046 had already written
--   wrapped by hand (`firm_isolation` on client_health_scores and client_health_overrides) show as informational
--   `policies_differ` lines until the snapshot is next captured with the fold of today.
--
-- LOCKS. `ALTER POLICY` takes an ACCESS EXCLUSIVE lock on its table, and the migration is one transaction, so every table
-- it touches is locked until it commits. Measured here, rewriting 796 policies took about half a second, which in-flight
-- requests wait for. The block sets a lock_timeout of 15 seconds for its own transaction, so that a long-running
-- transaction holding one of these tables fails the migration (and the deploy, to be re-run) instead of queueing every
-- later request on the table behind a migration that is itself waiting.
--
-- Idempotent. Reversible: 525_..._rollback.sql unwraps EVERY wrapped helper call in a `public` policy, including the calls
-- earlier migrations wrote wrapped by hand (it cannot tell its own wrapping from theirs), except the wrapped-by-design
-- policies of 524; that costs the speed and nothing else, and a re-apply of this file wraps them all again.

DO $$
DECLARE
  r record;
  new_using text;
  new_check text;
  stmt text;
  changed int := 0;
  -- A call of a helper with no argument or constants only (no parentheses can occur inside such an argument list), not
  -- already the target of a sub-select (deparsed as `( SELECT fn() AS fn)`), and not the tail of a longer name.
  pat constant text := '(?<!SELECT )(?<![A-Za-z_.])((?:public\.)?(?:get_my_firm_id|get_my_role|get_my_user_id|my_internal_client_id|my_permission|my_role_at_least)\([^()]*\)|auth\.(?:uid|jwt|role)\(\))';
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
    new_using := regexp_replace(r.using_expr, pat, '(SELECT \1)', 'g');
    new_check := regexp_replace(r.check_expr, pat, '(SELECT \1)', 'g');
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
  RAISE NOTICE 'migration 525: % policies now ask who is calling once per query', changed;

  -- The closing check: no policy in `public` still calls one of the helpers bare.
  SELECT count(*) INTO changed
    FROM pg_policy p
    JOIN pg_class c      ON c.oid = p.polrelid
    JOIN pg_namespace ns ON ns.oid = c.relnamespace
   WHERE ns.nspname = 'public'
     AND (coalesce(pg_get_expr(p.polqual, p.polrelid), '') ~ pat
          OR coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '') ~ pat);
  IF changed <> 0 THEN
    RAISE EXCEPTION 'migration 525: % policies still call a helper once per row', changed;
  END IF;
END $$;
