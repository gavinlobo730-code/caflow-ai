-- Migration 542: the two FX record tables and the portal session log are WRITTEN BY THE API ONLY and READ BY THE MEMBERS ASSIGNED
-- TO THE CLIENT (POST-A-299's last tranche).
--
-- WHAT WAS WRONG
-- Three client tables carried a NOT NULL client and a firm policy and nothing else (migrations 149, 156 and 194), so any member of the
-- firm, an unassigned Reviewer included, read and wrote them over PostgREST, and the signed-in role held INSERT, UPDATE and DELETE:
--
--   * fx_adjustments: the realised gain or loss of a foreign receipt or vendor payment and the unrealised one of a revaluation, which
--     the FX reports and the vendor statement read back and a reversal reads to undo a payment's AP relief;
--   * fx_revaluations: the rows the next revaluation diffs against (`_prior_runs`), so a forged row changes the next journal;
--   * client_portal_sessions: the log the client-health score reads a client's login recency from (a Reviewer forged a row on a
--     throwaway database on 21-10-2026).
--
-- WHAT THIS DOES (one transaction)
--   1. The writers of the two FX tables moved to the privileged client in the change BEFORE this one (`fx_writer`: the foreign
--      receipt, the two foreign vendor payment paths and the revaluation), and the portal touch has always written with the service
--      client. THAT HAS TO BE LIVE FIRST: this migration merges only after that change has been on Render for at least an hour (the
--      sandbox cannot see which commit Render is serving, so the hour is a delay and the dashboard is the check); the old API against
--      these revoked grants fails soft and wrong (a foreign receipt posts its journal and then fails to record the exchange
--      difference).
--   2. INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES and TRIGGER (and MAINTAIN where the server has it) are revoked from
--      `authenticated`, and everything from `anon` and PUBLIC; SELECT stays on `authenticated`, because the API reads the tables under
--      the caller's own sign-in (USE_USER_JWT, the production default) and row security is then the second lock on those reads. The
--      service role's four privileges are granted explicitly, so nothing above can have removed them through PUBLIC. Nothing in
--      apps/web reads or writes the tables.
--   3. The two RESTRICTIVE policies every client table carries (the assignment scope and the internal practice's Partner-only guard,
--      in the once-per-query form of migrations 525 to 536) are written for all three, so a member reads the rows of the clients they
--      are assigned to, a Partner reads every row of the firm, and the practice's own rows are a Partner's. With the writes revoked
--      they are the second lock on the write side too.
--   4. The policies and the grants are changed inside ONE DO block, every statement written out literally (the production-drift guard
--      finds a policy by its CREATE POLICY text). DROP POLICY and CREATE POLICY take ACCESS EXCLUSIVE on the table until the
--      migration commits (measured on 16 in the review of this change; GRANT and REVOKE take no table lock and sit in the block so
--      that the file is applied as one unit), and the runner sends one top-level statement per round trip, so a lock taken at the top
--      level is held across the round trips that follow (the review of migration 539 measured what that costs). The block
--      therefore asks for the three tables' lock first, in ACCESS EXCLUSIVE mode WITHOUT QUEUEING (NOWAIT, retried every half second
--      for up to fifteen seconds): a plain request would sit in the lock queue and every later read and write of the table would wait
--      behind it, and three taken one after another would hold the earlier tables while waiting for the later. After fifteen seconds
--      the migration fails in its own words, to be re-run. The block also ENABLES row security on the three tables (a no-op where it
--      is on, as production's snapshot says), because every policy below means nothing with it off.
--   5. Firm separation rests on the firm policy each table already carries (the permissive one of migrations 149, 156 and 194); the
--      two restrictive policies written here narrow it and carry no firm clause of their own, as in 528 and 536.
--
-- The migration ends by verifying the EFFECTIVE privileges, read from the ACL itself (so a grant through PUBLIC is seen, and so is
-- MAINTAIN, the PostgreSQL 17 privilege that the PG16 CI database does not have), that row security is on, the six policies, and that
-- the service role keeps its writes. The three entries of
-- tests/fixtures/assignment_scope_exceptions.json leave the shrink-only list in the same commit, which empties its `pending` kind.
--
-- NO ROLE TIER is added: the revoked grant is the control, and the routes that write these tables (the receipt, the vendor payment and
-- the revaluation) ask the role themselves.
--
-- ROLLBACK gives back what migrations 149, 156 and 194 granted (SELECT, INSERT, UPDATE and DELETE to `authenticated`) and drops the
-- six policies, restoring the firm policy as the only rule. Production may hold more than the migrations granted (the platform's
-- default privileges); the revoke does not depend on what it held.

SELECT set_config('lock_timeout', '15s', true);

DO $apply$
DECLARE
  v_try integer := 0;
BEGIN
  LOOP
    BEGIN
      LOCK TABLE public.fx_adjustments, public.fx_revaluations, public.client_portal_sessions IN ACCESS EXCLUSIVE MODE NOWAIT;
      EXIT;
    EXCEPTION WHEN lock_not_available THEN
      v_try := v_try + 1;
      IF v_try >= 30 THEN
        RAISE EXCEPTION 'migration 542: could not lock the three FX and portal tables in 15 seconds (a transaction is using one); run it again';
      END IF;
      PERFORM pg_sleep(0.5);
    END;
  END LOOP;

  ALTER TABLE public.fx_adjustments ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.fx_revaluations ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.client_portal_sessions ENABLE ROW LEVEL SECURITY;

  DROP POLICY IF EXISTS "fx_adjustments_assignment_scope" ON public.fx_adjustments;
  CREATE POLICY "fx_adjustments_assignment_scope" ON public.fx_adjustments
    AS RESTRICTIVE FOR ALL
    USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                     OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
    WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                          OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

  DROP POLICY IF EXISTS "fx_adjustments_internal_partner_only" ON public.fx_adjustments;
  CREATE POLICY "fx_adjustments_internal_partner_only" ON public.fx_adjustments
    AS RESTRICTIVE FOR ALL
    USING ((SELECT public.get_my_role()) = 'Partner'::text
           OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
    WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
                OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

  REVOKE ALL ON public.fx_adjustments FROM PUBLIC, anon, authenticated;
  GRANT SELECT ON public.fx_adjustments TO authenticated;
  GRANT SELECT, INSERT, UPDATE, DELETE ON public.fx_adjustments TO service_role;

  DROP POLICY IF EXISTS "fx_revaluations_assignment_scope" ON public.fx_revaluations;
  CREATE POLICY "fx_revaluations_assignment_scope" ON public.fx_revaluations
    AS RESTRICTIVE FOR ALL
    USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                     OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
    WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                          OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

  DROP POLICY IF EXISTS "fx_revaluations_internal_partner_only" ON public.fx_revaluations;
  CREATE POLICY "fx_revaluations_internal_partner_only" ON public.fx_revaluations
    AS RESTRICTIVE FOR ALL
    USING ((SELECT public.get_my_role()) = 'Partner'::text
           OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
    WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
                OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

  REVOKE ALL ON public.fx_revaluations FROM PUBLIC, anon, authenticated;
  GRANT SELECT ON public.fx_revaluations TO authenticated;
  GRANT SELECT, INSERT, UPDATE, DELETE ON public.fx_revaluations TO service_role;

  DROP POLICY IF EXISTS "client_portal_sessions_assignment_scope" ON public.client_portal_sessions;
  CREATE POLICY "client_portal_sessions_assignment_scope" ON public.client_portal_sessions
    AS RESTRICTIVE FOR ALL
    USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                     OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
    WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                          OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

  DROP POLICY IF EXISTS "client_portal_sessions_internal_partner_only" ON public.client_portal_sessions;
  CREATE POLICY "client_portal_sessions_internal_partner_only" ON public.client_portal_sessions
    AS RESTRICTIVE FOR ALL
    USING ((SELECT public.get_my_role()) = 'Partner'::text
           OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
    WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
                OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

  REVOKE ALL ON public.client_portal_sessions FROM PUBLIC, anon, authenticated;
  GRANT SELECT ON public.client_portal_sessions TO authenticated;
  GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_portal_sessions TO service_role;
END $apply$;

DO $$
DECLARE
  t       text;
  v_left  text;
  v_priv  text;
BEGIN
  FOREACH t IN ARRAY ARRAY['fx_adjustments', 'fx_revaluations', 'client_portal_sessions'] LOOP
    -- what the signed-in, anonymous and PUBLIC grantees hold, read from the ACL itself: the signed-in role keeps SELECT and nothing
    -- else, and the anonymous role and PUBLIC hold nothing
    SELECT string_agg(DISTINCT CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END || ':' || a.privilege_type,
                      ', ' ORDER BY CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END || ':' || a.privilege_type)
      INTO v_left
      FROM pg_class c, aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) a
     WHERE c.oid = ('public.' || t)::regclass
       AND (a.grantee = 0
            OR a.grantee = (SELECT oid FROM pg_roles WHERE rolname = 'anon')
            OR (a.grantee = (SELECT oid FROM pg_roles WHERE rolname = 'authenticated') AND a.privilege_type <> 'SELECT'));
    IF v_left IS NOT NULL THEN
      RAISE EXCEPTION 'migration 542: public.% still grants %', t, v_left;
    END IF;
    IF has_any_column_privilege('authenticated', 'public.' || t, 'INSERT, UPDATE, REFERENCES')
       OR has_any_column_privilege('anon', 'public.' || t, 'SELECT, INSERT, UPDATE, REFERENCES') THEN
      RAISE EXCEPTION 'migration 542: a column privilege on public.% is still held by the signed-in or anonymous role', t;
    END IF;
    IF NOT (SELECT c.relrowsecurity FROM pg_class c WHERE c.oid = ('public.' || t)::regclass) THEN
      RAISE EXCEPTION 'migration 542: row security is off on public.%, so its policies decide nothing', t;
    END IF;
    IF NOT has_table_privilege('authenticated', 'public.' || t, 'SELECT') THEN
      RAISE EXCEPTION 'migration 542: a signed-in session no longer reads %, and the API reads it as the caller', t;
    END IF;
    FOREACH v_priv IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE'] LOOP
      IF NOT has_table_privilege('service_role', 'public.' || t, v_priv) THEN
        RAISE EXCEPTION 'migration 542: the API (service_role) cannot % %', v_priv, t;
      END IF;
    END LOOP;
    -- the two policies, RESTRICTIVE and for every command
    IF (SELECT count(*) FROM pg_policy p
         WHERE p.polrelid = ('public.' || t)::regclass AND NOT p.polpermissive AND p.polcmd = '*'
           AND p.polname IN (t || '_assignment_scope', t || '_internal_partner_only')) <> 2 THEN
      RAISE EXCEPTION 'migration 542: public.% does not carry its two restrictive policies', t;
    END IF;
  END LOOP;
END $$;
