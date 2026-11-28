-- Migration 786: the definitions that a re-run of six old migrations reverted are restored (POST-A-583).
--
-- WHAT WENT WRONG
--   The runner (scripts/db/apply_migrations.py) applies a migration again when its file's checksum is not the one production
--   recorded: that is how a fix to a file that FAILED gets retried. On 27-11-2026 a sweep that renamed test files also rewrote the
--   old test names where they stood in the COMMENTS of eight migrations production had applied long before (245, 269, 274, 306,
--   318, 440, 442, 443). A comment is part of the checksum. The push to main at 14:55 UTC ran the six that still run cleanly a
--   second time, in number order, over a database that every later migration had already changed, and two (442, 443) failed on a
--   policy that already exists and were remembered, which kept the production job red from then on.
--
--   A second run of an old migration puts back what it defined and silently undoes every later change to the same object:
--     * 274 re-created public.post_journal_atomic with its September body. The wrapper of migrations 486, 533, 545 and 546 was gone:
--       no question of who is calling, no check that the client is the firm's, no closure check, no audit actor, the lines' order
--       and cost centre not stored (the old body wrote the lines itself and never reached post_journal_atomic__unguarded), and
--       274's own GRANT gave EXECUTE back to `authenticated`, which 546 had taken away. A signed-in session could post through a
--       SECURITY DEFINER function that asked nothing.
--     * 440 re-created public.my_portal_client_ids() without migration 768's `deleted_at` test, and re-created the four
--       portal_messages_assignment_scope policies in the once-per-row form that migration 526 had rewritten.
--   The other four changed nothing that a later migration had changed (245 revokes what is still revoked, 269 and 306 grant the
--   service role what it still holds, 318 restates three constraints nothing has restated since). Read on production on
--   28-11-2026, read-only, against a database built from the migrations: these seven objects differed and nothing else the six
--   files touch did. No journal entry had been posted on production between the re-run and that reading.
--
-- WHAT THIS DOES
--   1. Restates public.post_journal_atomic as migration 546 defined it (the last migration to define it, found by number), byte
--      for byte, and its privileges: nobody signed in, anonymous or PUBLIC may execute it; the service role may.
--   2. Restates public.my_portal_client_ids() as migration 768 defined it, with its privileges.
--   3. Runs migration 526's own rewrite loop again, which finds every policy that calls can_access_client once per row and
--      rewrites it, and refuses to finish while one is left. It says how many it rewrote (RAISE WARNING, which the runner keeps):
--      four on production, none on a database built from the migrations.
--   4. Checks itself and fails the whole file (one transaction: the runner wraps it) if the posting function does not ask who is
--      calling, or a signed-in or anonymous role can still execute it.
--   On a database built from the migrations in order this file changes nothing, and tests/test_786_..._pg.py proves both halves:
--   the six files run again undo the definitions, and this file puts every function, policy and privilege back.
--
-- WHAT IT DOES NOT DO
--   It does not touch migrations 442 and 443: their two comment lines are put back in the same commit, so their checksums are
--   again the ones production recorded on 29-09-2026 and the runner stops trying them. It does not edit the six that ran again:
--   production now records their NEW checksums, and editing them back would run them a third time. The rule that an applied
--   migration is never edited, not even a comment, is held from now on by tests/test_an_applied_migration_is_never_edited.py.
--
-- There is no rollback worth the name: the rollback file is a no-op that says why.

-- ── 1. post_journal_atomic: migration 546's wrapper, byte for byte ──
CREATE OR REPLACE FUNCTION public.post_journal_atomic(p_entry jsonb, p_lines jsonb)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    v_firm   uuid;
    v_client uuid;
    v_date   date;
    v_rev    uuid;
    v_reason text;
BEGIN
    -- The old body refused an empty payload in these words, and a caller (and a test) may rely on them.
    IF p_entry IS NULL OR p_entry = '{}'::jsonb THEN
        RAISE EXCEPTION 'post_journal_atomic: empty entry payload';
    END IF;

    v_firm   := NULLIF(p_entry->>'firm_id', '')::uuid;
    v_client := NULLIF(p_entry->>'client_id', '')::uuid;

    PERFORM public.assert_caller_acts_for('post_journal_atomic', v_firm, v_client,
        '[["banking","write","Executive"],
          ["accounting","write","Manager"],["client","write","Manager"],["year_end","approve","Manager"],
          ["accounting","approve","Partner"],["payroll","finalize","Partner"]]'::jsonb);

    -- MIGRATION 546: THE SERVER'S OWN CALL NAMES A CLIENT OF ITS FIRM. With no auth.uid() (the API's privileged client, a job, a
    -- connection with no JWT) the check above returned without asking anything, and the unguarded body asks the client's firm
    -- only for a signed-in caller. The posting is the server's own act now, so the database asks the one thing a route cannot
    -- have got wrong by being right about the person: that the client in the payload belongs to the firm in the payload. A NULL
    -- firm or client names no such client. (A signed-in caller was asked this by assert_caller_acts_for, above.)
    IF auth.uid() IS NULL AND NOT EXISTS (
            SELECT 1 FROM public.clients c WHERE c.id = v_client AND c.firm_id = v_firm) THEN
        RAISE EXCEPTION 'post_journal_atomic: client % is not a client of firm %', v_client, v_firm USING ERRCODE = '42501';
    END IF;

    -- MIGRATION 545: for a privileged caller (no auth.uid()), the posting person's auth id travels with the transaction so the
    -- audit triggers record who posted: the reserved payload key `audit_actor` (an auth id, which the API takes from the person its
    -- authentication dependency verified) or, when it is absent, the internal user id in `created_by`. A signed-in caller is its own actor and this does
    -- nothing for it. The key is removed again before the unguarded body, which builds its INSERT from the payload's keys.
    PERFORM public.carry_audit_actor(p_entry->>'audit_actor', p_entry->>'created_by', v_firm);

    -- A REVERSAL STAMPS ITS ORIGINAL, AND THE ORIGINAL MUST BE THIS CLIENT'S. The unguarded body flips `is_reversed` on the
    -- entry named in `reversal_of` for the payload's firm, and asks nothing about its client, its date or the caller's
    -- assignment: an Executive assigned to client A could hide client B's entry (or one of A's own in a finalised year) from
    -- every statement, the TDS register and section 43B(h), block its genuine reversal and free its reference number. (Found by
    -- the independent review of this migration.) Posting the reversal into an OPEN year of an entry in a closed one is the
    -- remedy the closure's own sentence offers, so the entry's DATE is deliberately not asked here, only whose it is.
    v_rev := NULLIF(p_entry->>'reversal_of', '')::uuid;
    IF v_rev IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.journal_entries e WHERE e.id = v_rev AND e.firm_id = v_firm AND e.client_id = v_client) THEN
        RAISE EXCEPTION 'post_journal_atomic: the entry being reversed is not an entry of this client' USING ERRCODE = '42501';
    END IF;

    -- THE CLOSURE: the firm's locked year, or this client's finalised year-end. An entry date that cannot be read
    -- is a refusal, never a reason to skip the check (the kernel's ACC-27 rule: the one value that must not buy
    -- its way past a control is the one the control cannot read).
    BEGIN
        v_date := NULLIF(p_entry->>'entry_date', '')::date;
    EXCEPTION WHEN others THEN
        v_date := NULL;
    END;
    IF v_date IS NULL OR v_date = 'infinity'::date OR v_date = '-infinity'::date THEN
        RAISE EXCEPTION 'post_journal_atomic: ''%'' is not a posting date. Use YYYY-MM-DD: a date this cannot read is a date the year-end lock cannot be checked against.',
            COALESCE(p_entry->>'entry_date', '') USING ERRCODE = '22007';
    END IF;
    v_reason := public.period_closure_reason(v_firm, v_client, v_date);
    IF v_reason IS NOT NULL THEN
        RAISE EXCEPTION '%', v_reason;
    END IF;

    RETURN public.post_journal_atomic__unguarded(p_entry - 'audit_actor', p_lines);
END;
$fn$;

REVOKE ALL ON FUNCTION public.post_journal_atomic(jsonb, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO service_role;

-- ── 2. my_portal_client_ids(): migration 768's definition, byte for byte ──
CREATE OR REPLACE FUNCTION public.my_portal_client_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT cpu.client_id FROM public.client_portal_users cpu
    JOIN public.clients c ON c.id = cpu.client_id AND c.deleted_at IS NULL
   WHERE cpu.auth_user_id = auth.uid() AND cpu.status = 'active'
  UNION
  SELECT id FROM public.clients
   WHERE portal_user_id = auth.uid() AND deleted_at IS NULL
$$;

REVOKE EXECUTE ON FUNCTION public.my_portal_client_ids() FROM PUBLIC, anon;
GRANT  EXECUTE ON FUNCTION public.my_portal_client_ids() TO authenticated;

-- ── 3. migration 526's rewrite loop, run again ──
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
  RAISE WARNING 'migration 786: % policies were put back to reading the caller''s clients once per query', changed;

  -- The closing check: no policy in `public` still calls can_access_client per row.
  SELECT count(*) INTO changed
    FROM pg_policy p
    JOIN pg_class c      ON c.oid = p.polrelid
    JOIN pg_namespace ns ON ns.oid = c.relnamespace
   WHERE ns.nspname = 'public'
     AND (coalesce(pg_get_expr(p.polqual, p.polrelid), '') ~ 'can_access_client'
          OR coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '') ~ 'can_access_client');
  IF changed <> 0 THEN
    RAISE EXCEPTION 'migration 786: % policies still call can_access_client once per row', changed;
  END IF;
END $$;

-- ── 4. The file checks its own work ──
DO $check$
DECLARE
  v_src text;
BEGIN
  SELECT p.prosrc INTO v_src
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
   WHERE n.nspname = 'public' AND p.proname = 'post_journal_atomic'
     AND pg_get_function_identity_arguments(p.oid) = 'p_entry jsonb, p_lines jsonb';
  IF v_src IS NULL OR position('assert_caller_acts_for' in v_src) = 0
     OR position('post_journal_atomic__unguarded' in v_src) = 0 OR position('period_closure_reason' in v_src) = 0 THEN
    RAISE EXCEPTION 'migration 786: post_journal_atomic is not the wrapper that asks who is calling';
  END IF;
  IF has_function_privilege('authenticated', 'public.post_journal_atomic(jsonb, jsonb)', 'EXECUTE')
     OR has_function_privilege('anon', 'public.post_journal_atomic(jsonb, jsonb)', 'EXECUTE') THEN
    RAISE EXCEPTION 'migration 786: a signed-in or anonymous role can still execute post_journal_atomic';
  END IF;
  IF NOT has_function_privilege('service_role', 'public.post_journal_atomic(jsonb, jsonb)', 'EXECUTE') THEN
    RAISE EXCEPTION 'migration 786: the service role cannot execute post_journal_atomic';
  END IF;
  SELECT p.prosrc INTO v_src
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
   WHERE n.nspname = 'public' AND p.proname = 'my_portal_client_ids';
  IF v_src IS NULL OR position('deleted_at IS NULL' in v_src) = 0 THEN
    RAISE EXCEPTION 'migration 786: my_portal_client_ids does not leave out a deleted client';
  END IF;
END $check$;
