-- Rollback for migration 526: the policies call can_access_client((<column>)::text) once per row again, as migration 084
-- wrote them, and the helper 526 added is dropped.
--
-- Rolling back changes no answer a policy gives and costs the speed 526 buys (between about 440 and 1,100 times for a Partner and about 660 times for
-- a Manager with one client, measured on 100,000 rows of a synthetic table). Nothing else changes; no row is touched.
--
-- Roll back in the reverse order of the migrations: 526 before 525. This file matches the text 525 left in the rewritten
-- policies (`( SELECT get_my_role() AS get_my_role)`); after 525's rollback it matches nothing, restores nothing, and the
-- DROP FUNCTION below then fails because the policies still use the helper, which is loud and leaves nothing half done.

DO $$
DECLARE
  r record;
  new_using text;
  new_check text;
  stmt text;
  -- The deparsed form of what 526 wrote (a wrapped get_my_role is `( SELECT get_my_role() AS get_my_role)`).
  pat constant text := 'COALESCE\(\(\(\(([a-z_][a-z_0-9.]*)\)::text IS NULL\) OR \(\( SELECT (?:public\.)?get_my_role\(\) AS get_my_role\) = ''Partner''::text\) OR \(\(\1\)::text IN \( SELECT (?:public\.)?my_assigned_client_ids\(\) AS my_assigned_client_ids\)\)\), false\)';
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
    new_using := regexp_replace(r.using_expr, pat, 'can_access_client((\1)::text)', 'g');
    new_check := regexp_replace(r.check_expr, pat, 'can_access_client((\1)::text)', 'g');
    IF new_using IS DISTINCT FROM r.using_expr OR new_check IS DISTINCT FROM r.check_expr THEN
      stmt := format('ALTER POLICY %I ON public.%I', r.polname, r.relname);
      IF r.using_expr IS NOT NULL THEN
        stmt := stmt || ' USING (' || new_using || ')';
      END IF;
      IF r.check_expr IS NOT NULL THEN
        stmt := stmt || ' WITH CHECK (' || new_check || ')';
      END IF;
      EXECUTE stmt;
    END IF;
  END LOOP;
END $$;

DROP FUNCTION IF EXISTS public.my_assigned_client_ids();
