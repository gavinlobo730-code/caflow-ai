-- Migration 546 — the two ledger functions are executable by the server alone, and the server's own call must name a client of its firm (POST-A-317, last step).
--
-- WHAT IS WRONG TODAY
--   post_journal_atomic (the posting kernel) and settle_receipt_atomic (a plain rupee customer receipt) are the database's ledger
--   writers. Both are SECURITY DEFINER and executable by every signed-in user, who is admitted by a union of the role pairs the
--   posting routes ask (banking:write at Executive is enough for either). A member who holds ANY ONE of them can therefore post, over
--   PostgREST with their own token and for any client they reach, a balanced entry with any content: any source_type, status,
--   created_by, posted_by or narration, in an open year, with none of the questions the application's routes ask before they post
--   (the document the entry claims to belong to, the filed-return lock where the document feeds a return, the tax and numbering
--   rules). Migration 533 closed the CLOSED-year hole in both; this closes the door they were reached through.
--
-- WHAT IT DOES
--   * REVOKEs EXECUTE on both functions from PUBLIC, anon and authenticated, and keeps service_role. The two unguarded bodies were
--     never executable by anyone signed in and are not touched.
--   * Both wrappers keep every check they have for a signed-in caller (the caller's firm, reach to the client, the internal
--     practice, the role pair, the reversal's ownership, the closure and the receipt-and-journal agreement): no signed-in caller
--     can reach them now, and a grant restored by hand would meet the same checks as before, no fewer. They gain one for a
--     PRIVILEGED caller (no auth.uid()): the client in the payload must be a client of the firm in the payload. Until now
--     assert_caller_acts_for returned at once for the service role and the unguarded body asks the client's firm only for a
--     signed-in caller, so a route that passed another firm's client id would have posted into it. A NULL firm or client names no
--     such client and is refused in the same words.
--   Each wrapper is migration 545's definition (the migration that LAST defined it, found by number) plus exactly the added lines;
--   the test reconstructs the ancestor by scanning the migration directory and asserts it.
--
-- ORDER, AND WHY IT MATTERS
--   The API has called both functions through its privileged client since the change that added services/ledger_door.py, and
--   migration 545 lets them carry the posting person into the audit trigger. THIS MIGRATION MUST NOT APPLY BEFORE THAT CHANGE IS
--   DEPLOYED: the previous API calls them with the caller's own token, and against a revoked grant every posting is refused with
--   42501 (permission denied for function), which looks like a permission problem on every screen that posts and not like what it is.
--   The change merged at least an hour before this one for that reason, and the rollback below is the way back.
--
-- WHAT IT DOES NOT DO
--   It does not touch edit_posted_journal (the manual journal's edit, which asks who is calling since 486 and is limited to a
--   manual journal in an open period), numbered_document_atomic or any table. It does not change what the application checks
--   before it posts: that is the routes' own, hardened separately.
--
-- Reversible: 546_..._rollback.sql restores migration 545's two definitions and gives authenticated its EXECUTE back.


-- ── post_journal_atomic: migration 545's wrapper with the server's own call asked for a client of its firm ──
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

-- ── settle_receipt_atomic: migration 545's wrapper with the server's own call asked for a client of its firm ──
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

    -- MIGRATION 546: THE SERVER'S OWN CALL NAMES A CLIENT OF ITS FIRM. With no auth.uid() (the API's privileged client, a job, a
    -- connection with no JWT) the check above returned without asking anything, and the unguarded body asks the client's firm
    -- only for a signed-in caller. The posting is the server's own act now, so the database asks the one thing a route cannot
    -- have got wrong by being right about the person: that the client in the payload belongs to the firm in the payload. A NULL
    -- firm or client names no such client. (A signed-in caller was asked this by assert_caller_acts_for, above.)
    IF auth.uid() IS NULL AND NOT EXISTS (
            SELECT 1 FROM public.clients c WHERE c.id = NULLIF(p_journal_entry->>'client_id', '')::uuid AND c.firm_id = NULLIF(p_journal_entry->>'firm_id', '')::uuid) THEN
        RAISE EXCEPTION 'settle_receipt_atomic: client % is not a client of firm %', NULLIF(p_journal_entry->>'client_id', '')::uuid, NULLIF(p_journal_entry->>'firm_id', '')::uuid USING ERRCODE = '42501';
    END IF;
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

-- ── who may call them: the server, and nobody signed in ──
-- Migration 272 took PUBLIC away and 533 left `authenticated` (a signed-in member's own token) and `service_role`. The API's
-- posting kernel and plain receipt now call both through its privileged client (services/ledger_door.py), so the signed-in
-- grant has no caller left and is what a member who held one posting permission could use over PostgREST. `anon` never had it.
-- The two unguarded bodies were never executable by anyone signed in and are not touched.
REVOKE ALL ON FUNCTION public.post_journal_atomic(jsonb, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb) TO service_role;

DO $$
DECLARE
    v_fn regprocedure;
BEGIN
    FOREACH v_fn IN ARRAY ARRAY['public.post_journal_atomic(jsonb, jsonb)'::regprocedure,
                                'public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb)'::regprocedure] LOOP
        IF has_function_privilege('authenticated', v_fn, 'EXECUTE') OR has_function_privilege('anon', v_fn, 'EXECUTE') THEN
            RAISE EXCEPTION 'migration 546: % is still executable by a signed-in user', v_fn; END IF;
        IF NOT has_function_privilege('service_role', v_fn, 'EXECUTE') THEN
            RAISE EXCEPTION 'migration 546: % is not executable by the service role', v_fn; END IF;
        IF position('is not a client of firm' IN pg_get_functiondef(v_fn)) = 0
           OR position('assert_caller_acts_for' IN pg_get_functiondef(v_fn)) = 0
           OR position('carry_audit_actor' IN pg_get_functiondef(v_fn)) = 0
           OR position(chr(39) || 'audit_actor' || chr(39) IN pg_get_functiondef(v_fn)) = 0 THEN
            RAISE EXCEPTION 'migration 546: % lost one of its checks', v_fn; END IF;
    END LOOP;
    -- the unguarded bodies stay the service role's alone
    IF has_function_privilege('authenticated', 'public.post_journal_atomic__unguarded(jsonb, jsonb)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('authenticated', 'public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 546: an unguarded ledger body is executable by a signed-in user'; END IF;
END
$$;
