-- Migration 275: a CA may DISCARD a manual journal entry until the period is
-- locked or its return is filed — the same gate migration 266 gave editing.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY
-- ═══════════════════════════════════════════════════════════════════════════
-- 266 argued that absolute immutability is stricter than Indian law: the
-- proviso to Rule 3(1) of the Companies (Accounts) Rules 2014 requires an edit
-- log of each change, which PRESUMES entries can change, and Tally lets a
-- posted voucher be altered and records it. It then permitted correction until
-- a HUMAN act ends it — the CA locks the year, or a return covering the period
-- is filed.
--
-- It stopped one step short: "Deletion stays forbidden even inside an edit."
-- No reasoning was given, and on inspection there is none that survives. A CA
-- teaching a trainee, or posting a dummy entry to see what a screen does, is
-- left with a reversal — two permanent rows and a net of zero — to undo
-- something that was never a transaction at all. That is noise in the books
-- masquerading as rigour.
--
-- The same edit log that makes correction lawful makes discarding lawful. What
-- it does NOT permit is a discard that leaves no trace, which is why this is a
-- soft delete: deleted_at is set, the row and every line survive, and
-- trg_audit_capture records the change. The entry leaves every screen, every
-- report and the reporting passbook; it does not leave the record.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE THREE LIMITS, AND WHY EACH IS THERE
-- ═══════════════════════════════════════════════════════════════════════════
-- 1. MANUAL ENTRIES ONLY (source_type = 'manual').
--    Most journals are auto-posted from a sales invoice, receipt, payment or
--    bank line. Discarding one of those leaves the document pointing at a
--    journal that is gone and the sub-ledger disagreeing with the GL. Those
--    are corrected by correcting the DOCUMENT, which posts its own reversal.
--    A trainee demo or a dummy entry is manual by construction, so this costs
--    the actual use case nothing and removes the half that corrupts.
--
-- 2. THE PERIOD MUST BE OPEN, judged by journal_period_lock_reason — the SAME
--    function edit_posted_journal calls. Not a re-listing of "GST filed or
--    year locked": a second implementation would drift from the first, and an
--    entry that is editable but not discardable (or worse, the reverse) is a
--    rule nobody can explain. One function, one answer, and the reason it
--    returns is a sentence written for a CA.
--
-- 3. NOT ENTANGLED WITH A REVERSAL. An entry that has been reversed cannot be
--    discarded — the reversal would be left pointing at nothing — and a
--    reversal cannot itself be discarded, which would leave its original
--    flagged is_reversed with nothing to show for it. Both are refused by
--    name rather than silently skipped.
--
-- The passbook is rebuilt and asserted afterwards, exactly as the edit path
-- does it. apb_rebuild_client filters `is_posted AND deleted_at IS NULL`, so a
-- discarded entry drops out on rebuild; without the rebuild,
-- account_period_balances would keep the discarded entry's figures and the
-- trial balance would silently stop agreeing with the ledger.
--
-- Idempotent, and safe to re-run.

BEGIN;

CREATE OR REPLACE FUNCTION public.discard_posted_journal(
    p_firm     uuid,
    p_client   uuid,
    p_entry_id uuid,
    p_actor    uuid DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_catalog AS $$
DECLARE
    v_entry  public.journal_entries;
    v_reason text;
BEGIN
    SELECT * INTO v_entry
      FROM public.journal_entries
     WHERE id = p_entry_id AND firm_id = p_firm AND client_id = p_client
       AND deleted_at IS NULL
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Journal entry not found.' USING ERRCODE = 'no_data_found';
    END IF;

    -- (1) Manual only.
    IF COALESCE(v_entry.source_type, '') <> 'manual' THEN
        RAISE EXCEPTION
            'This entry was posted automatically from a %. Correct the document '
            'itself — discarding its journal would leave the document pointing '
            'at nothing.', COALESCE(NULLIF(v_entry.source_type, ''), 'source document');
    END IF;

    -- (3) Not entangled with a reversal. Checked before the period, because
    -- "this was reversed" is a better answer than "the period is closed" when
    -- both are true.
    IF COALESCE(v_entry.is_reversed, FALSE) THEN
        RAISE EXCEPTION
            'This entry has been reversed. Discarding it would leave the '
            'reversal pointing at nothing.';
    END IF;
    IF v_entry.reversal_of IS NOT NULL THEN
        RAISE EXCEPTION
            'This entry IS a reversal. Discarding it would leave the entry it '
            'reversed marked as reversed with nothing to show for it.';
    END IF;

    -- (2) The period must be open. Same function the edit path calls.
    v_reason := public.journal_period_lock_reason(p_firm, p_client, v_entry.entry_date);
    IF v_reason IS NOT NULL THEN
        RAISE EXCEPTION '%', v_reason;
    END IF;

    -- Soft delete. The row and its lines stay; deleted_at is what every read
    -- path already filters on (the journal list, the approval queue,
    -- _assert_journal_scope_db, and apb_rebuild_client itself).
    --
    -- app.journal_edit is what lets a posted row be written at all —
    -- prevent_posted_journal_update otherwise refuses everything but the
    -- is_reversed flip. Set and cleared around the single statement, as
    -- edit_posted_journal does it.
    PERFORM set_config('app.journal_edit', 'on', true);

    UPDATE public.journal_entries
       SET deleted_at = now(),
           updated_at = now()
     WHERE id = p_entry_id;

    PERFORM set_config('app.journal_edit', '', true);

    -- The passbook's triggers are additive-only and did not see that. Rebuild,
    -- then PROVE it.
    PERFORM public.apb_rebuild_client(p_firm, p_client);
    PERFORM public.apb_assert_no_drift();

    RETURN jsonb_build_object(
        'id', p_entry_id,
        'discarded', true,
        'entry_date', v_entry.entry_date,
        'reference_no', v_entry.reference_no,
        'discarded_by', p_actor
    );
END
$$;

-- SECURITY DEFINER, so PUBLIC/anon must not hold EXECUTE — the anon key is
-- inlined into the browser bundle by design (migration 272's finding).
REVOKE EXECUTE ON FUNCTION public.discard_posted_journal(uuid, uuid, uuid, uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.discard_posted_journal(uuid, uuid, uuid, uuid) FROM anon;
GRANT EXECUTE ON FUNCTION public.discard_posted_journal(uuid, uuid, uuid, uuid)
    TO authenticated, service_role;

COMMENT ON FUNCTION public.discard_posted_journal(uuid, uuid, uuid, uuid) IS
    'Soft-delete a MANUAL journal entry while its period is open, judged by '
    'journal_period_lock_reason — the same gate edit_posted_journal uses. '
    'Refuses auto-posted entries, reversals, and reversed entries. Rebuilds '
    'account_period_balances and asserts no drift. See migration 275.';

COMMIT;
