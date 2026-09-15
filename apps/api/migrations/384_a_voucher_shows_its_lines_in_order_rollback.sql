-- Rollback for 384. Restores migration 243's post_journal_atomic exactly
-- (no line_order, no WITH ORDINALITY) and drops the column.
CREATE OR REPLACE FUNCTION public.post_journal_atomic(p_entry jsonb, p_lines jsonb)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $function$
DECLARE
  v_id            uuid;
  v_existing      uuid;
  v_keys          text;
  v_total_debit   bigint;
  v_total_credit  bigint;
  v_my_firm       uuid;
  v_internal      uuid;
  v_reversed      uuid;
BEGIN
  -- Restates journal_entries' own RLS policies, which SECURITY DEFINER bypasses.
  IF auth.uid() IS NOT NULL THEN
    v_my_firm := public.get_my_firm_id();

    IF v_my_firm IS NULL THEN
      RAISE EXCEPTION 'post_journal_atomic: caller has no user record in this database'
        USING ERRCODE = '42501';
    END IF;

    IF (p_entry->>'firm_id')::uuid IS DISTINCT FROM v_my_firm THEN
      RAISE EXCEPTION 'post_journal_atomic: firm_id % is not the caller''s firm',
        p_entry->>'firm_id'
        USING ERRCODE = '42501';
    END IF;

    IF NOT public.can_access_client(p_entry->>'client_id') THEN
      RAISE EXCEPTION 'post_journal_atomic: client % is not assigned to the caller',
        p_entry->>'client_id'
        USING ERRCODE = '42501';
    END IF;

    -- The firm's own internal client is Partner-only (migration 073's pattern).
    v_internal := public.my_internal_client_id();
    IF v_internal IS NOT NULL
       AND (p_entry->>'client_id')::uuid = v_internal
       AND COALESCE(public.get_my_role(), '') <> 'Partner' THEN
      RAISE EXCEPTION 'post_journal_atomic: only a Partner may post to the firm''s internal client'
        USING ERRCODE = '42501';
    END IF;
  END IF;

  SELECT COALESCE(sum(COALESCE((l->>'debit_paise')::bigint, 0)), 0),
         COALESCE(sum(COALESCE((l->>'credit_paise')::bigint, 0)), 0)
    INTO v_total_debit, v_total_credit
    FROM jsonb_array_elements(p_lines) AS l;

  IF v_total_debit <> v_total_credit THEN
    RAISE EXCEPTION 'post_journal_atomic: journal imbalance debit=% credit=% for ref=%',
      v_total_debit, v_total_credit, p_entry->>'reference_no';
  END IF;
  IF v_total_debit = 0 THEN
    RAISE EXCEPTION 'post_journal_atomic: refusing to post a zero-value journal entry for ref=%',
      p_entry->>'reference_no';
  END IF;

  SELECT string_agg(quote_ident(k), ', ')
    INTO v_keys
    FROM jsonb_object_keys(p_entry) AS k;
  IF v_keys IS NULL THEN
    RAISE EXCEPTION 'post_journal_atomic: empty entry payload';
  END IF;

  BEGIN
    EXECUTE format(
      'INSERT INTO public.journal_entries (%1$s) '
      'SELECT %1$s FROM jsonb_populate_record(NULL::public.journal_entries, $1) '
      'RETURNING id', v_keys
    ) INTO v_id USING p_entry;
  EXCEPTION WHEN unique_violation THEN
    SELECT id INTO v_existing
      FROM public.journal_entries
     WHERE firm_id      = (p_entry->>'firm_id')::uuid
       AND client_id    = (p_entry->>'client_id')::uuid
       AND reference_no = p_entry->>'reference_no'
       AND entry_date   = (p_entry->>'entry_date')::date
       AND deleted_at IS NULL
     ORDER BY created_at
     LIMIT 1;
    RETURN v_existing;
  END;

  INSERT INTO public.journal_lines (
    journal_entry_id, account_id, debit_paise, credit_paise, narration,
    txn_currency, base_currency, exchange_rate, txn_debit, txn_credit,
    rate_source, rate_type, rate_date
  )
  SELECT
    v_id,
    (l->>'account_id')::uuid,
    COALESCE((l->>'debit_paise')::bigint, 0),
    COALESCE((l->>'credit_paise')::bigint, 0),
    l->>'narration',
    COALESCE(NULLIF(l->>'txn_currency', ''), 'INR'),
    COALESCE(NULLIF(l->>'base_currency', ''), 'INR'),
    COALESCE((l->>'exchange_rate')::numeric, 1),
    NULLIF(l->>'txn_debit', '')::bigint,
    NULLIF(l->>'txn_credit', '')::bigint,
    l->>'rate_source',
    COALESCE(NULLIF(l->>'rate_type', ''), 'booking'),
    NULLIF(l->>'rate_date', '')::date
  FROM jsonb_array_elements(p_lines) AS l;

  -- ── NEW ────────────────────────────────────────────────────────────────────
  -- This entry IS a reversal, so stamp the original in the same transaction.
  --
  -- The firm_id match is not redundant with the guard above: it pins the stamp
  -- to the firm whose payload was just validated, so a forged reversal_of
  -- cannot reach another tenant's row even though SECURITY DEFINER means RLS
  -- is not running.
  --
  -- COALESCE(is_reversed, false) = false is load-bearing, not defensive.
  -- prevent_posted_journal_update permits the flip only FROM false; attempting
  -- it on an already-stamped row RAISES. Without this predicate a re-post of
  -- the same reversal would error instead of being the no-op it should be.
  v_reversed := NULLIF(p_entry->>'reversal_of', '')::uuid;
  IF v_reversed IS NOT NULL THEN
    UPDATE public.journal_entries
       SET is_reversed = true
     WHERE id = v_reversed
       AND firm_id = (p_entry->>'firm_id')::uuid
       AND COALESCE(is_reversed, false) = false;
  END IF;

  RETURN v_id;
END
$function$;
REVOKE EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) FROM anon;
GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO authenticated;
GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO service_role;

-- And migration 338's edit_posted_journal, verbatim (no line_order).
CREATE OR REPLACE FUNCTION public.edit_posted_journal(
    p_firm         uuid,
    p_client       uuid,
    p_entry_id     uuid,
    p_lines        jsonb,
    p_narration    text     DEFAULT NULL,
    p_reference_no text     DEFAULT NULL,
    p_entry_date   date     DEFAULT NULL,
    p_actor        uuid     DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_catalog AS $$
DECLARE
    v_entry      public.journal_entries;
    v_new_date   date;
    v_reason     text;
    v_debit      bigint;
    v_credit     bigint;
    v_count      int;
BEGIN
    SELECT * INTO v_entry
      FROM public.journal_entries
     WHERE id = p_entry_id AND firm_id = p_firm AND client_id = p_client
       AND deleted_at IS NULL
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Journal entry not found.' USING ERRCODE = 'no_data_found';
    END IF;

    -- (1) Manual only — the gate migration 275 gave the discard path, in the
    -- same words, because it is the same rule about the same entries.
    IF COALESCE(v_entry.source_type, '') <> 'manual' THEN
        RAISE EXCEPTION
            'This entry was posted automatically from a %. Correct the document '
            'itself — editing its journal would leave the document and the '
            'ledger saying different things.',
            COALESCE(NULLIF(v_entry.source_type, ''), 'source document');
    END IF;

    IF COALESCE(v_entry.is_reversed, FALSE) THEN
        RAISE EXCEPTION 'This entry has been reversed and can no longer be edited.';
    END IF;

    v_new_date := COALESCE(p_entry_date, v_entry.entry_date);

    -- BOTH dates are checked. Moving an entry OUT of a locked period is as much
    -- a change to that period's numbers as editing one already in it, and a
    -- check on the new date alone would let a locked year be quietly emptied.
    v_reason := public.journal_period_lock_reason(p_firm, p_client, v_entry.entry_date);
    IF v_reason IS NOT NULL THEN RAISE EXCEPTION '%', v_reason; END IF;
    IF v_new_date <> v_entry.entry_date THEN
        v_reason := public.journal_period_lock_reason(p_firm, p_client, v_new_date);
        IF v_reason IS NOT NULL THEN RAISE EXCEPTION '%', v_reason; END IF;
    END IF;

    SELECT count(*),
           COALESCE(sum((ln->>'debit_paise')::bigint), 0),
           COALESCE(sum((ln->>'credit_paise')::bigint), 0)
      INTO v_count, v_debit, v_credit
      FROM jsonb_array_elements(p_lines) ln;

    IF v_count < 2 THEN
        RAISE EXCEPTION 'A journal entry needs at least two lines.';
    END IF;
    -- Double entry. Integer paise on both sides, compared exactly — the same
    -- invariant post_journal_atomic enforces on the way in, enforced again on
    -- the way through, because an edit is a posting too.
    IF v_debit <> v_credit THEN
        RAISE EXCEPTION 'Unbalanced entry: debit % paise <> credit % paise.', v_debit, v_credit;
    END IF;

    PERFORM set_config('app.journal_edit', 'on', true);

    UPDATE public.journal_entries
       SET entry_date   = v_new_date,
           narration    = COALESCE(p_narration, narration),
           reference_no = COALESCE(p_reference_no, reference_no),
           updated_at   = now()
     WHERE id = p_entry_id;

    -- Replace rather than reconcile. The audit trigger records the deletes and
    -- the inserts, so the before/after of every figure survives in the log.
    DELETE FROM public.journal_lines WHERE journal_entry_id = p_entry_id;

    INSERT INTO public.journal_lines
        (journal_entry_id, account_id, debit_paise, credit_paise, narration)
    SELECT p_entry_id,
           (ln->>'account_id')::uuid,
           (ln->>'debit_paise')::bigint,
           (ln->>'credit_paise')::bigint,
           NULLIF(ln->>'narration', '')
      FROM jsonb_array_elements(p_lines) ln;

    PERFORM set_config('app.journal_edit', '', true);

    -- The passbook's triggers are additive-only and did not see any of the
    -- above. Rebuild, then PROVE it — an unasserted rebuild is how 249's drift
    -- went unnoticed in the first place.
    PERFORM public.apb_rebuild_client(p_firm, p_client);
    PERFORM public.apb_assert_no_drift();

    RETURN jsonb_build_object(
        'id', p_entry_id,
        'entry_date', v_new_date,
        'lines', v_count,
        'total_debit_paise', v_debit,
        'total_credit_paise', v_credit,
        'edited_by', p_actor
    );
END;
$$;

REVOKE ALL ON FUNCTION public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid) TO authenticated, service_role;

ALTER TABLE public.journal_lines DROP COLUMN IF EXISTS line_order;
