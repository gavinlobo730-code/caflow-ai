-- Rollback for migration 338: restore migration 266's edit_posted_journal,
-- WITHOUT the source_type gate.
--
-- WHAT THIS RESTORES IS THE HOLE. Without the gate, the journal behind a sales
-- invoice, purchase bill, receipt, payment, bank posting, depreciation run,
-- opening balance, trial-balance import or year-end adjustment can have its
-- accounts, amounts and date rewritten while the document it came from does
-- not move — so the GL and the sub-ledger disagree, and GSTR-1 (built from the
-- invoice rows) stops tying to the trial balance (built from the GL). Run this
-- only to unblock a caller that 338 broke, and only long enough to find out
-- which caller it is; the fix is then to correct that caller's document, not
-- to keep this file applied.
--
-- The body below is migration 266's, verbatim. Idempotent, and safe to re-run.

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

-- SECURITY DEFINER + no PUBLIC execute: the carve-out flag is only reachable
-- through this function, so "posted entries are immutable except here" stays a
-- fact about the database rather than a convention in the application.

REVOKE ALL ON FUNCTION public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid) TO authenticated, service_role;
