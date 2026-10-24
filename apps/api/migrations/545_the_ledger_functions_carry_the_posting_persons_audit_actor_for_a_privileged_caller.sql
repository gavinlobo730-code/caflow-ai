-- Migration 545 — the ledger functions carry the posting person's audit actor for a privileged caller (POST-A-317, step 1).
--
-- WHAT IS WRONG TODAY
--   Every posting reaches the ledger through post_journal_atomic (the kernel) or settle_receipt_atomic (a plain rupee receipt), both
--   called with the REQUEST's own client, so the audit triggers (migration 111 for every table, redacted by 336; migration 266 for
--   journal_lines) see auth.uid() and write the row-level edit log: Companies (Accounts) Rules 2014 Rule 3(1) leans on it, and
--   production holds 14,479 journal-entry creates written by the trigger against 15 written by the application. Both functions are
--   SECURITY DEFINER and executable by every signed-in user, and migration 533 admits the caller by a union of the role pairs the
--   posting routes ask, so a member who holds ANY one of them can post any balanced entry for a client they reach over PostgREST
--   with any content (source_type, status, created_by, posted_by): the ledger-door item, POST-A-317. The durable fix is to take the
--   door away: the API's kernel calls the two functions with its privileged client after the route's own checks, and EXECUTE is
--   revoked from signed-in users.
--
-- WHY THIS COMES FIRST
--   The privileged client has no auth.uid(), and the audit triggers record a write only when auth.uid() is present, so the moment
--   the kernel stops calling as the person the journal-entry, journal-line, receipt and invoice-settlement rows would vanish from
--   the edit log. This migration lets the two functions CARRY the person's auth id for the length of their own transaction, before
--   anything depends on it. It changes nothing for a signed-in caller (auth.uid() wins) and nothing for a caller that names no
--   person. (An independent review of the first version found that it carried the person only into audit_capture and not into
--   audit_capture_journal_line, which writes the line rows from its own function, and that most postings name no created_by to
--   carry: both are in this version.)
--
-- WHAT IT DOES
--   * public.carry_audit_actor(audit_actor text, created_by text, firm uuid): SECURITY INVOKER, executable by nobody signed in (it
--     is called from inside the two definer wrappers). When auth.uid() is NULL it first clears the setting (a second posting in one
--     transaction never inherits the first one's person), then resolves the person: `audit_actor` is an AUTH id, which the API takes
--     from the person its authentication dependency verified for the request; it must name a member of the entry's own firm, and a value that does not is no actor and is not
--     replaced by anything else. When `audit_actor` is absent a job's person is found from the internal user id in `created_by`,
--     again only inside the entry's own firm. The result is the transaction-local setting `app.audit_actor`.
--   * public.carried_audit_actor(): the one reader of that setting; a value that is not a uuid is no actor.
--   * audit_capture is migration 336's definition and audit_capture_journal_line is migration 266's, each with one addition: when
--     auth.uid() is NULL they read the carried actor, and a row written for one says so in its metadata (`actor_source`: carried),
--     because the person did not make the write with their own token. The setting is read only then, so a signed-in session's
--     actor is never replaced, however the session sets the setting.
--   * the two wrappers are migration 533's, with one added call after the caller check, and with the reserved payload key
--     `audit_actor` removed again before the unguarded body, which builds its INSERT from the payload's keys. A signed-in caller
--     that sends the key has it removed and ignored.
--   Each is the whole definition of the function, restated from the migration that LAST defined it (found by number: 336, 266 and
--   533); the test reconstructs the ancestor by scanning the migration directory and asserts the new body is the ancestor plus
--   exactly the added lines.
--
-- WHAT IT DOES NOT DO
--   It does not change who may call either function (that is the last step of POST-A-317), the kernel or any table. A job that
--   already posts with the service role and names a person in `created_by` is now audited as that person: the row says what the
--   entry's own created_by column already says.
--
-- Reversible: 545_..._rollback.sql restores the four definitions and drops the carrier and its reader. Roll 546 back first.


CREATE OR REPLACE FUNCTION public.carry_audit_actor(p_audit_actor text, p_created_by text, p_firm uuid)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    v_claimed uuid;
    v_user    uuid;
    v_auth    uuid;
BEGIN
    -- A signed-in caller is the actor the audit triggers already record (auth.uid()); nothing is carried for it.
    IF auth.uid() IS NOT NULL THEN
        RETURN;
    END IF;
    -- A second posting in the same transaction never inherits the first one's person.
    PERFORM set_config('app.audit_actor', '', true);
    IF p_firm IS NULL THEN
        RETURN;
    END IF;
    IF p_audit_actor IS NOT NULL AND btrim(p_audit_actor) <> '' THEN
        -- The auth id of the person the API verified for this request. It must name a member of the entry's own firm:
        -- anything else is no actor, and is not replaced by `created_by`, which would hide a wrong value.
        BEGIN
            v_claimed := p_audit_actor::uuid;
        EXCEPTION WHEN invalid_text_representation THEN
            RETURN;
        END;
        SELECT u.auth_user_id INTO v_auth FROM public.users u WHERE u.auth_user_id = v_claimed AND u.firm_id = p_firm LIMIT 1;
    ELSIF p_created_by IS NOT NULL AND btrim(p_created_by) <> '' THEN
        -- A job names its person only by the internal user id in `created_by`; the person must belong to the entry's own firm.
        BEGIN
            v_user := p_created_by::uuid;
        EXCEPTION WHEN invalid_text_representation THEN
            RETURN;
        END;
        SELECT u.auth_user_id INTO v_auth FROM public.users u WHERE u.id = v_user AND u.firm_id = p_firm LIMIT 1;
    END IF;
    IF v_auth IS NOT NULL THEN
        -- transaction-local (third argument true): gone when the posting's transaction ends.
        PERFORM set_config('app.audit_actor', v_auth::text, true);
    END IF;
END;
$fn$;

REVOKE ALL ON FUNCTION public.carry_audit_actor(text, text, uuid) FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.carried_audit_actor()
RETURNS uuid
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
DECLARE
    v_setting text := nullif(current_setting('app.audit_actor', true), '');
BEGIN
    IF v_setting IS NULL THEN
        RETURN NULL;
    END IF;
    BEGIN
        RETURN v_setting::uuid;
    EXCEPTION WHEN others THEN
        RETURN NULL;
    END;
END;
$fn$;

REVOKE ALL ON FUNCTION public.carried_audit_actor() FROM PUBLIC, anon, authenticated;

-- ── the two audit trigger functions: migration 336's audit_capture and 266's audit_capture_journal_line, with the carried actor read when auth.uid() is NULL ──
CREATE OR REPLACE FUNCTION public.audit_capture()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_actor  uuid := auth.uid();
  v_email  text;
  v_firm   uuid;
  v_entity text;
  v_etype  text;
  v_action text;
  v_old    jsonb;
  v_new    jsonb;
  v_carried boolean := false;
BEGIN
  -- Only capture end-user (browser) writes. Service-role backend writes have a
  -- NULL auth.uid() and are audited in-app by audit_service.log_event.
  --
  -- MIGRATION 545: a privileged caller of post_journal_atomic / settle_receipt_atomic (the API, whose posting kernel calls them with
  -- its privileged client) has no auth.uid(). Those two functions carry the posting person's AUTH id for the length of their own
  -- transaction in the setting `app.audit_actor` (public.carry_audit_actor), read here by public.carried_audit_actor() ONLY when
  -- auth.uid() is NULL, so a signed-in session's own actor can never be replaced by it. An unreadable value is no actor, and
  -- auditing still never breaks the write. A row written for a carried actor says so in its metadata (`actor_source`), because the
  -- person did not make this write with their own token and a reader of the edit log should be able to tell.
  IF v_actor IS NULL THEN
    v_actor := public.carried_audit_actor();
    v_carried := v_actor IS NOT NULL;
  END IF;
  IF v_actor IS NULL THEN
    RETURN NULL;
  END IF;

  -- THE ONLY CHANGE FROM MIGRATION 111: the snapshots go through audit_redact.
  -- firm_id and id are read from the redacted payload below, and neither is on
  -- the redaction list, so the routing still works exactly as it did.
  IF (TG_OP = 'INSERT') THEN
    v_action := 'create'; v_new := public.audit_redact(to_jsonb(NEW));
  ELSIF (TG_OP = 'UPDATE') THEN
    v_action := 'update';
    v_new := public.audit_redact(to_jsonb(NEW));
    v_old := public.audit_redact(to_jsonb(OLD));
  ELSE
    v_action := 'delete'; v_old := public.audit_redact(to_jsonb(OLD));
  END IF;

  -- audit_log.firm_id is NOT NULL — skip any firm-less row.
  v_firm := nullif(coalesce(v_new->>'firm_id', v_old->>'firm_id'), '')::uuid;
  IF v_firm IS NULL THEN
    RETURN NULL;
  END IF;

  v_entity := coalesce(v_new->>'id', v_old->>'id');

  -- Normalise the table name to the app's singular entity vocabulary so events
  -- from triggers and from log_event share one set of filter values.
  v_etype := CASE TG_TABLE_NAME
    WHEN 'chart_of_accounts'   THEN 'account'
    WHEN 'accounts'            THEN 'account'
    WHEN 'compliance_calendar' THEN 'compliance'
    ELSE CASE
      WHEN TG_TABLE_NAME LIKE '%ies' THEN left(TG_TABLE_NAME, length(TG_TABLE_NAME) - 3) || 'y'
      WHEN TG_TABLE_NAME LIKE '%s'   THEN left(TG_TABLE_NAME, length(TG_TABLE_NAME) - 1)
      ELSE TG_TABLE_NAME
    END
  END;

  SELECT u.email INTO v_email FROM public.users u WHERE u.auth_user_id = v_actor LIMIT 1;

  INSERT INTO public.audit_log
    (firm_id, actor_id, actor_email, entity_type, entity_id, action, old_data, new_data, metadata)
  VALUES
    (v_firm, v_actor, v_email, v_etype, v_entity, v_action, v_old, v_new,
     jsonb_build_object('source', 'db_trigger', 'table', TG_TABLE_NAME)
       || CASE WHEN v_carried THEN jsonb_build_object('actor_source', 'carried') ELSE '{}'::jsonb END);

  RETURN NULL;
EXCEPTION WHEN OTHERS THEN
  -- Auditing must never break the user's write.
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION public.audit_capture_journal_line()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
  v_actor uuid := auth.uid();
  v_email text;
  v_firm  uuid;
  v_entry uuid;
  v_action text;
  v_old jsonb;
  v_new jsonb;
  v_carried boolean := false;
BEGIN
  --
  -- MIGRATION 545: a privileged caller of post_journal_atomic / settle_receipt_atomic (the API, whose posting kernel calls them with
  -- its privileged client) has no auth.uid(). Those two functions carry the posting person's AUTH id for the length of their own
  -- transaction in the setting `app.audit_actor` (public.carry_audit_actor), read here by public.carried_audit_actor() ONLY when
  -- auth.uid() is NULL, so a signed-in session's own actor can never be replaced by it. An unreadable value is no actor, and
  -- auditing still never breaks the write. A row written for a carried actor says so in its metadata (`actor_source`), because the
  -- person did not make this write with their own token and a reader of the edit log should be able to tell.
  IF v_actor IS NULL THEN
    v_actor := public.carried_audit_actor();
    v_carried := v_actor IS NOT NULL;
  END IF;
  IF v_actor IS NULL THEN
    RETURN NULL;
  END IF;

  IF (TG_OP = 'INSERT') THEN
    v_action := 'create'; v_new := to_jsonb(NEW); v_entry := NEW.journal_entry_id;
  ELSIF (TG_OP = 'UPDATE') THEN
    v_action := 'update'; v_new := to_jsonb(NEW); v_old := to_jsonb(OLD);
    v_entry := NEW.journal_entry_id;
  ELSE
    v_action := 'delete'; v_old := to_jsonb(OLD); v_entry := OLD.journal_entry_id;
  END IF;

  SELECT je.firm_id INTO v_firm FROM public.journal_entries je WHERE je.id = v_entry;
  IF v_firm IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT u.email INTO v_email FROM public.users u WHERE u.auth_user_id = v_actor LIMIT 1;

  -- entity_id is the PARENT entry, not the line: an auditor asks "what changed
  -- on this entry", and a log keyed on line ids they have never seen cannot
  -- answer that. The line's own id is in old_data/new_data.
  INSERT INTO public.audit_log
    (firm_id, actor_id, actor_email, entity_type, entity_id, action, old_data, new_data, metadata)
  VALUES
    (v_firm, v_actor, v_email, 'journal_line', v_entry::text, v_action, v_old, v_new,
     jsonb_build_object('source', 'db_trigger', 'table', TG_TABLE_NAME)
       || CASE WHEN v_carried THEN jsonb_build_object('actor_source', 'carried') ELSE '{}'::jsonb END);

  RETURN NULL;
EXCEPTION WHEN OTHERS THEN
  RETURN NULL;
END;
$$;

-- ── post_journal_atomic: migration 533's wrapper with the actor carried ──
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

-- ── settle_receipt_atomic: migration 533's wrapper with the actor carried ──
CREATE OR REPLACE FUNCTION public.settle_receipt_atomic(p_receipt jsonb, p_journal_entry jsonb, p_journal_lines jsonb, p_allocations jsonb)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    v_reason text;
    v_date   text;
    v_day    date;
BEGIN
    -- The receipt and its journal must name the same firm and client, for everyone: the function takes each from
    -- its own payload, so a mismatch is a receipt for one client posted against another's books.
    IF NULLIF(p_receipt->>'firm_id', '')::uuid   IS DISTINCT FROM NULLIF(p_journal_entry->>'firm_id', '')::uuid
       OR NULLIF(p_receipt->>'client_id', '')::uuid IS DISTINCT FROM NULLIF(p_journal_entry->>'client_id', '')::uuid THEN
        RAISE EXCEPTION 'settle_receipt_atomic: the receipt and its journal name different firms or clients'
            USING ERRCODE = '42501';
    END IF;
    -- accounting:write is Manager; a bank match-multi settles receipts as an Executive (banking:write).
    PERFORM public.assert_caller_acts_for('settle_receipt_atomic',
        NULLIF(p_journal_entry->>'firm_id', '')::uuid, NULLIF(p_journal_entry->>'client_id', '')::uuid,
        '[["accounting","write","Manager"],["banking","write","Executive"]]'::jsonb);
    -- MIGRATION 545: see post_journal_atomic. The receipt, the invoice settlement and the journal are audited as the poster.
    PERFORM public.carry_audit_actor(p_journal_entry->>'audit_actor', p_journal_entry->>'created_by', NULLIF(p_journal_entry->>'firm_id', '')::uuid);
    -- THE CLOSURE (migration 533): the journal's date and the receipt's own date, each against the firm's locked
    -- year and this client's finalised year-end. A date that is missing or cannot be read is a refusal, as in
    -- post_journal_atomic (both columns are NOT NULL, so a payload without one was going to fail later and less legibly).
    FOREACH v_date IN ARRAY ARRAY[p_journal_entry->>'entry_date', p_receipt->>'receipt_date'] LOOP
        BEGIN
            IF v_date IS NULL OR v_date = '' THEN
                RAISE invalid_datetime_format;
            END IF;
            v_day := v_date::date;
            IF v_day = 'infinity'::date OR v_day = '-infinity'::date THEN
                RAISE invalid_datetime_format;
            END IF;
            v_reason := public.period_closure_reason(
                NULLIF(p_journal_entry->>'firm_id', '')::uuid, NULLIF(p_journal_entry->>'client_id', '')::uuid, v_day);
        EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow OR invalid_text_representation THEN
            RAISE EXCEPTION 'settle_receipt_atomic: ''%'' is not a posting date. Use YYYY-MM-DD: a date this cannot read is a date the year-end lock cannot be checked against.', v_date
                USING ERRCODE = '22007';
        END;
        IF v_reason IS NOT NULL THEN
            RAISE EXCEPTION '%', v_reason;
        END IF;
    END LOOP;
    RETURN public.settle_receipt_atomic__unguarded(p_receipt, p_journal_entry - 'audit_actor', p_journal_lines, p_allocations);
END;
$fn$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = 'public.carry_audit_actor(text, text, uuid)'::regprocedure AND NOT prosecdef)
       OR NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = 'public.carried_audit_actor()'::regprocedure AND NOT prosecdef) THEN
        RAISE EXCEPTION 'migration 545: the carrier or its reader is missing or is SECURITY DEFINER'; END IF;
    IF has_function_privilege('authenticated', 'public.carry_audit_actor(text, text, uuid)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.carry_audit_actor(text, text, uuid)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('authenticated', 'public.carried_audit_actor()'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.carried_audit_actor()'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 545: the carrier or its reader is executable by a signed-in user'; END IF;
    IF position('carry_audit_actor' IN pg_get_functiondef('public.post_journal_atomic(jsonb, jsonb)'::regprocedure)) = 0
       OR position('carry_audit_actor' IN pg_get_functiondef('public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb)'::regprocedure)) = 0 THEN
        RAISE EXCEPTION 'migration 545: a ledger function does not carry the audit actor'; END IF;
    IF position(chr(39) || 'audit_actor' || chr(39) IN pg_get_functiondef('public.post_journal_atomic(jsonb, jsonb)'::regprocedure)) = 0
       OR position(chr(39) || 'audit_actor' || chr(39) IN pg_get_functiondef('public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb)'::regprocedure)) = 0 THEN
        RAISE EXCEPTION 'migration 545: a ledger function does not remove the reserved payload key'; END IF;
    IF position('carried_audit_actor' IN pg_get_functiondef('public.audit_capture()'::regprocedure)) = 0
       OR position('carried_audit_actor' IN pg_get_functiondef('public.audit_capture_journal_line()'::regprocedure)) = 0 THEN
        RAISE EXCEPTION 'migration 545: an audit trigger function does not read the carried actor'; END IF;
    -- the grants are the ones 533 gave and are not touched here
    IF NOT has_function_privilege('authenticated', 'public.post_journal_atomic(jsonb, jsonb)'::regprocedure, 'EXECUTE')
       OR NOT has_function_privilege('service_role', 'public.post_journal_atomic(jsonb, jsonb)'::regprocedure, 'EXECUTE')
       OR NOT has_function_privilege('service_role', 'public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.post_journal_atomic(jsonb, jsonb)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 545: the wrappers'' grants changed'; END IF;
END
$$;
