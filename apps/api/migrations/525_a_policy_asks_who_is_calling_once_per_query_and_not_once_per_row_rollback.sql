-- Rollback for migration 525: the helper calls in `public` policies are unwrapped again, so each is evaluated once per
-- ROW, as before.
--
-- Rolling back changes no answer a policy gives and costs the speed 525 buys (about 400 times on the firm policy, measured
-- on 100,000 rows; on a table carrying a `my_permission` tier policy beside a bare firm policy, 61 s bare against 6 s wrapped).
-- It does NOT restore the exact text every policy had before 525: it unwraps EVERY wrapped helper call in a `public` policy,
-- because the catalog cannot tell 525's wrapping from earlier hand-written wrapping, so the policies earlier migrations
-- wrote wrapped (008's `auth.uid()` ones, the `get_my_firm_id()` firm policies of 045 to 047, and the `auth.uid()` and
-- `get_my_user_id()` policies of 109, 153, 484, 506 and 510) go back to a per-row call too, with their answers unchanged,
-- and a re-apply of 525 wraps them all again. The policies that migration 524 wrote wrapped on purpose
-- (`*_banking_read_tier`) are the one exclusion.

DO $$
DECLARE
  r record;
  new_using text;
  new_check text;
  stmt text;
  pat constant text := '\(\s*SELECT\s+((?:public\.)?(?:get_my_firm_id|get_my_role|get_my_user_id|my_internal_client_id|my_permission|my_role_at_least)\([^()]*\)|auth\.(?:uid|jwt|role)\(\))\s+AS\s+[a-z_]+\)';
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
       AND p.polname NOT LIKE '%\_banking\_read\_tier'
  LOOP
    new_using := regexp_replace(r.using_expr, pat, '\1', 'g');
    new_check := regexp_replace(r.check_expr, pat, '\1', 'g');
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
