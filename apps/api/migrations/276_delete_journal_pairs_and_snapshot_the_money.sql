-- Migration 276: a reversed pair may be deleted together, and every deletion
-- records what it deleted — the lines included.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY
-- ═══════════════════════════════════════════════════════════════════════════
-- 275 let a CA discard a manual journal entry while its period is open, and
-- refused three things. Two of those refusals are still right. The third was
-- wrong, and it was wrong in the exact case the feature was built for.
--
-- A CA posts a dummy entry to show a trainee what a screen does, reverses it
-- because that was the only tool available, and is now holding two permanent
-- rows netting to zero. 275 refuses BOTH of them: the original because "the
-- reversal would be left pointing at nothing", the reversal because "its
-- original would be left flagged is_reversed with nothing to show for it".
-- Both sentences are true of deleting ONE half. Neither is true of deleting
-- the pair, which is precisely what the CA is asking for and the one operation
-- 275 never considered.
--
-- Deleting a reversal pair is also the SAFEST deletion there is. A pair
-- already nets to zero, so no balance moves — strictly less disturbance than
-- discarding a lone entry, which 275 already permits.
--
-- This is what the market does. TallyPrime 3.0 — where these firms are
-- migrating from — introduced Edit Log to meet the proviso to Rule 3(1) of the
-- Companies (Accounts) Rules 2014: on by default, not disableable. It did NOT
-- stop letting you delete a voucher. The voucher leaves the books; the log
-- keeps every version of it. Delete is permitted; the LOG is what is immutable.
-- That is the line this migration draws.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE OTHER HALF: THE LOG HAS TO HOLD THE MONEY
-- ═══════════════════════════════════════════════════════════════════════════
-- 266 already gave journal_lines its own audit trigger, because the generic
-- audit_capture() reads firm_id off the row and journal_lines has none. So
-- edits are covered: edit_posted_journal deletes and reinserts the lines, and
-- trg_audit_capture_line fires with old_data on each.
--
-- A DISCARD is different, and the difference was missed. It is an UPDATE on
-- journal_entries alone — deleted_at is stamped, the lines are not touched.
-- trg_audit_capture_line therefore never fires. What audit_log ends up holding
-- for a deleted entry is its HEADER: date, reference, narration. Every amount
-- and every account is absent from the deletion record.
--
-- The figures do exist in audit_log, as the per-line 'create' events from when
-- the entry was posted — scattered by timestamp, and only where that posting
-- carried a user JWT (audit_capture_journal_line returns early when auth.uid()
-- is NULL, so a service-role post writes nothing). Reconstructing a deleted
-- entry from that is a correlation exercise across N rows that may not exist.
-- An edit log you have to reconstruct is not one.
--
-- So the deletion now writes ONE audit_log row carrying the whole entry and
-- every line, resolved to account codes and names so it stays readable after a
-- chart of accounts has moved on. And it is written INSIDE the transaction with
-- no EXCEPTION handler: if the record cannot be written, the deletion does not
-- happen. Every other audit path in this schema swallows its own failures on
-- purpose — auditing must never break a user's write. That trade is right when
-- the row survives the failure. It is exactly wrong here, where the write being
-- audited is the one that makes the row unreachable.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IS UNCHANGED
-- ═══════════════════════════════════════════════════════════════════════════
--   * Manual entries only. An auto-posted journal is still corrected by
--     correcting its document. Both halves of a pair must be manual.
--   * The period must be open, judged by journal_period_lock_reason — the same
--     function the edit path calls. For a pair, BOTH dates are judged: a
--     reversal is usually dated later than its original, often in a different
--     month, and a pair that straddles a filed return must not move.
--   * Soft delete. deleted_at is stamped; the row and its lines stay where they
--     are. This is Tally's shape, not a weaker version of it — a deleted Tally
--     voucher lives on in the Edit Log store too.
--
-- The FUNCTION keeps its name. `discard_posted_journal` is referenced by the
-- router, the tests and 275's history; the product calls the button Delete,
-- which is what a CA off Tally goes looking for. Renaming the function would
-- buy a matching word and cost a working reference.
--
-- No new tables, no column changes. Idempotent, and safe to re-run.

BEGIN;

-- ═══════════════════════════════════════════════════════════════════════════
-- 1. THE SNAPSHOT
-- ═══════════════════════════════════════════════════════════════════════════
-- to_jsonb(je) rather than a column list on purpose: journal_entries has grown
-- columns across 270-odd migrations and will grow more, and a hand-written list
-- silently stops capturing whatever is added next. The whole row, whatever it
-- is that day.
--
-- The lines carry account_code and account_name alongside account_id. An id is
-- only a record while the chart of accounts still holds it under that name;
-- the point of this row is to be legible to an auditor years later.
--
-- SECURITY INVOKER: it reads the ledger and must stay behind RLS for anyone who
-- calls it directly. Its callers scope it themselves, and inside a SECURITY
-- DEFINER function it runs as that function's owner.
CREATE OR REPLACE FUNCTION public.journal_entry_snapshot(
    p_firm     uuid,
    p_client   uuid,
    p_entry_id uuid
) RETURNS jsonb LANGUAGE sql STABLE
SET search_path = public, pg_catalog AS $$
    SELECT to_jsonb(je) || jsonb_build_object(
        'lines',
        COALESCE((
            SELECT jsonb_agg(
                       to_jsonb(jl) || jsonb_build_object(
                           'account_code', coa.account_code,
                           'account_name', coa.account_name
                       ) ORDER BY jl.id
                   )
              FROM public.journal_lines jl
              LEFT JOIN public.chart_of_accounts coa ON coa.id = jl.account_id
             WHERE jl.journal_entry_id = je.id
        ), '[]'::jsonb)
    )
      FROM public.journal_entries je
     WHERE je.id = p_entry_id AND je.firm_id = p_firm AND je.client_id = p_client;
$$;

COMMENT ON FUNCTION public.journal_entry_snapshot(uuid, uuid, uuid) IS
    'The complete journal entry as jsonb — the whole row plus every line with '
    'its account code and name resolved. Written into audit_log by '
    'discard_posted_journal before a deletion, because a deletion record that '
    'holds only the header records nothing of what was deleted. Migration 276.';

REVOKE EXECUTE ON FUNCTION public.journal_entry_snapshot(uuid, uuid, uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.journal_entry_snapshot(uuid, uuid, uuid) FROM anon;
GRANT EXECUTE ON FUNCTION public.journal_entry_snapshot(uuid, uuid, uuid)
    TO authenticated, service_role;


-- ═══════════════════════════════════════════════════════════════════════════
-- 2. THE DELETE
-- ═══════════════════════════════════════════════════════════════════════════
-- 275's signature was (uuid, uuid, uuid, uuid). CREATE OR REPLACE with a fifth
-- parameter would OVERLOAD rather than replace, and a four-argument call would
-- then be ambiguous against the defaulted five-argument one and fail outright.
-- The old signature has to go first.
DROP FUNCTION IF EXISTS public.discard_posted_journal(uuid, uuid, uuid, uuid);

CREATE OR REPLACE FUNCTION public.discard_posted_journal(
    p_firm      uuid,
    p_client    uuid,
    p_entry_id  uuid,
    p_actor     uuid    DEFAULT NULL,
    p_with_pair boolean DEFAULT false
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_catalog AS $$
DECLARE
    v_entry       public.journal_entries;
    v_mate        public.journal_entries;
    v_has_mate    boolean := false;
    v_targets     public.journal_entries[];
    v_target      public.journal_entries;
    v_reason      text;
    v_actor_auth  uuid;
    v_actor_email text;
    v_ids         uuid[] := ARRAY[]::uuid[];
    v_refs        text[] := ARRAY[]::text[];
BEGIN
    SELECT * INTO v_entry
      FROM public.journal_entries
     WHERE id = p_entry_id AND firm_id = p_firm AND client_id = p_client
       AND deleted_at IS NULL
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Journal entry not found.' USING ERRCODE = 'no_data_found';
    END IF;

    -- ── The counterpart ─────────────────────────────────────────────────────
    -- Entanglement is decided by what is actually THERE, not by the flag. An
    -- is_reversed original whose reversal has already been deleted points at
    -- nothing, so deleting it alone breaks nothing; the same the other way
    -- round. Locked in the same statement that finds it — a pair must not be
    -- half-deleted by two concurrent callers.
    IF COALESCE(v_entry.is_reversed, FALSE) THEN
        SELECT * INTO v_mate
          FROM public.journal_entries
         WHERE reversal_of = v_entry.id AND firm_id = p_firm AND client_id = p_client
           AND deleted_at IS NULL
         ORDER BY created_at
         LIMIT 1
         FOR UPDATE;
        v_has_mate := FOUND;
    ELSIF v_entry.reversal_of IS NOT NULL THEN
        SELECT * INTO v_mate
          FROM public.journal_entries
         WHERE id = v_entry.reversal_of AND firm_id = p_firm AND client_id = p_client
           AND deleted_at IS NULL
         FOR UPDATE;
        v_has_mate := FOUND;
    END IF;

    -- Deleting one half alone is still refused, and this is the only refusal
    -- 276 keeps from 275's third limit. The message names the counterpart and
    -- says what to do about it, rather than reading as a dead end.
    IF v_has_mate AND NOT p_with_pair THEN
        IF COALESCE(v_entry.is_reversed, FALSE) THEN
            RAISE EXCEPTION
                'This entry was reversed by %. Delete the two together — a '
                'reversal cannot outlive the entry it reverses.',
                COALESCE(NULLIF(v_mate.reference_no, ''), 'its reversal');
        ELSE
            RAISE EXCEPTION
                'This entry is the reversal of %. Delete the two together — a '
                'reversal cannot outlive the entry it reverses.',
                COALESCE(NULLIF(v_mate.reference_no, ''), 'the original entry');
        END IF;
    END IF;

    -- ── Validate every row that is about to go ──────────────────────────────
    -- Built once and walked twice. One loop over one or two rows, so a pair can
    -- never be held to a weaker standard than a single entry by an oversight in
    -- a second copy of the rules.
    v_targets := CASE WHEN v_has_mate THEN ARRAY[v_entry, v_mate] ELSE ARRAY[v_entry] END;

    FOREACH v_target IN ARRAY v_targets LOOP
        -- (1) Manual only. An auto-posted journal is corrected by correcting
        --     its document, or the document is left pointing at nothing. This
        --     covers a manual entry reversed by a document cascade: the
        --     cascade's half fails here and names itself.
        IF COALESCE(v_target.source_type, '') <> 'manual' THEN
            RAISE EXCEPTION
                'Entry % was posted automatically from a %. Correct the '
                'document itself — deleting its journal would leave the '
                'document pointing at nothing.',
                COALESCE(NULLIF(v_target.reference_no, ''), v_target.id::text),
                COALESCE(NULLIF(v_target.source_type, ''), 'source document');
        END IF;

        -- (2) The period must be open. The SAME function the edit path calls,
        --     applied to EACH date: a reversal is normally dated later than
        --     its original and often lands in a different month, so judging
        --     the pair by the original's date alone would let a pair straddling
        --     a filed return move.
        v_reason := public.journal_period_lock_reason(p_firm, p_client, v_target.entry_date);
        IF v_reason IS NOT NULL THEN
            IF v_has_mate THEN
                RAISE EXCEPTION 'Entry % cannot be deleted. %',
                    COALESCE(NULLIF(v_target.reference_no, ''), v_target.id::text), v_reason;
            END IF;
            RAISE EXCEPTION '%', v_reason;
        END IF;
    END LOOP;

    -- ── The record, before the deletion ─────────────────────────────────────
    -- Deliberately NOT wrapped in an exception handler, unlike every audit
    -- trigger in this schema. Those swallow so that auditing can never break a
    -- user's write, which is the right trade when the row survives the failure.
    -- Here the write being audited is the one that takes the row off every
    -- screen: if this INSERT cannot happen, the deletion must not either.
    SELECT u.auth_user_id, u.email INTO v_actor_auth, v_actor_email
      FROM public.users u WHERE u.id = p_actor;

    FOREACH v_target IN ARRAY v_targets LOOP
        INSERT INTO public.audit_log
            (firm_id, actor_id, actor_email, entity_type, entity_id, action,
             old_data, new_data, metadata)
        VALUES
            (p_firm, v_actor_auth, v_actor_email, 'journal_entry',
             v_target.id::text, 'delete',
             public.journal_entry_snapshot(p_firm, p_client, v_target.id),
             NULL,
             jsonb_build_object(
                 'source', 'discard_posted_journal',
                 'migration', 276,
                 'soft_delete', true,
                 'pair', v_has_mate,
                 'requested_entry', p_entry_id,
                 'client_id', p_client
             ));

        v_ids  := v_ids  || v_target.id;
        v_refs := v_refs || COALESCE(NULLIF(v_target.reference_no, ''), v_target.id::text);
    END LOOP;

    -- ── The deletion ────────────────────────────────────────────────────────
    -- app.journal_edit is what lets a posted row be written at all —
    -- prevent_posted_journal_update otherwise refuses everything but the
    -- is_reversed flip. Set around the single statement and cleared after, as
    -- edit_posted_journal does it. One UPDATE covers both rows, so a pair
    -- cannot end up half-deleted.
    PERFORM set_config('app.journal_edit', 'on', true);

    UPDATE public.journal_entries
       SET deleted_at = now(),
           updated_at = now()
     WHERE id = ANY(v_ids);

    PERFORM set_config('app.journal_edit', '', true);

    -- The passbook's triggers are additive-only and did not see that. Rebuild
    -- once for the pair, then PROVE it.
    PERFORM public.apb_rebuild_client(p_firm, p_client);
    PERFORM public.apb_assert_no_drift();

    RETURN jsonb_build_object(
        'id', p_entry_id,
        'discarded', true,
        'deleted_ids', to_jsonb(v_ids),
        'deleted_refs', to_jsonb(v_refs),
        'pair', v_has_mate,
        'entry_date', v_entry.entry_date,
        'reference_no', v_entry.reference_no,
        'discarded_by', p_actor
    );
END
$$;

-- SECURITY DEFINER, so PUBLIC/anon must not hold EXECUTE — the anon key is
-- inlined into the browser bundle by design (migration 272's finding).
REVOKE EXECUTE ON FUNCTION public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean) FROM anon;
GRANT EXECUTE ON FUNCTION public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean)
    TO authenticated, service_role;

COMMENT ON FUNCTION public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean) IS
    'Soft-delete a MANUAL journal entry while its period is open, judged by '
    'journal_period_lock_reason — the same gate edit_posted_journal uses. With '
    'p_with_pair, a reversed entry and its reversal go together (both must be '
    'manual, both dates open); without it, either half alone is refused by a '
    'message naming the other. Writes the full entry and its lines to audit_log '
    'first, in-transaction and unswallowed. Rebuilds account_period_balances '
    'and asserts no drift. See migrations 275 and 276.';

COMMIT;
