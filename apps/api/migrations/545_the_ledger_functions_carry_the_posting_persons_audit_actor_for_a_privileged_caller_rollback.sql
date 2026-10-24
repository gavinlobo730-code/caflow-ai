-- Rollback of migration 545: the four functions go back to the definitions migrations 336, 266 and 533 gave them (derived from those
-- files by script, not retyped) and the carrier and its reader are dropped. A privileged caller of the two ledger functions is
-- audited by nobody again.
-- ORDER: roll back migration 546 FIRST. Migration 546 redefines the two wrappers from 545's text; rolling 545 back under it
-- reinstates 533's wrappers and silently drops 546's check that a privileged call names a client of its firm, while the signed-in
-- grant stays revoked.

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
BEGIN
  -- Only capture end-user (browser) writes. Service-role backend writes have a
  -- NULL auth.uid() and are audited in-app by audit_service.log_event.
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
     jsonb_build_object('source', 'db_trigger', 'table', TG_TABLE_NAME));

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
BEGIN
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
     jsonb_build_object('source', 'db_trigger', 'table', TG_TABLE_NAME));

  RETURN NULL;
EXCEPTION WHEN OTHERS THEN
  RETURN NULL;
END;
$$;

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

    RETURN public.post_journal_atomic__unguarded(p_entry, p_lines);
END;
$fn$;

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
    RETURN public.settle_receipt_atomic__unguarded(p_receipt, p_journal_entry, p_journal_lines, p_allocations);
END;
$fn$;

DROP FUNCTION IF EXISTS public.carry_audit_actor(text, text, uuid);
DROP FUNCTION IF EXISTS public.carried_audit_actor();
