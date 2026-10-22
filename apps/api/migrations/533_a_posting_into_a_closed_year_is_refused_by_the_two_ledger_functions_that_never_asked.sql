-- Migration 533 — a posting into a closed year is refused by the two database functions that write the ledger and
-- never asked whether the year was closed (security, ledger POST-A-316, found by the independent review of
-- migration 532 and reproduced on a throwaway database on 21-10-2026).
--
-- THE HOLE
--   "Closed" is the CA's own deliberate act: the firm locked the financial year, or the client's year-end was
--   finalised (migration 361's `period_closure_reason` answers both). The posting kernel in the API asks it before
--   every posting (`_create_journal` calls `period_lock_service.closure_reason` with the request's own client), and
--   until migration 532 that call could not see a finalised year at all when the API ran as the signed-in person.
--   Two functions write the ledger and neither asks the question:
--
--     post_journal_atomic     SECURITY DEFINER, executable by every signed-in user; writes the entry, its lines and
--                             the reversal stamp of the entry it reverses. It restates the journal table's row
--                             security (the caller's firm, a client they can reach, the internal practice client
--                             for a Partner only) and nothing about the PERIOD.
--     settle_receipt_atomic   migration 486's guarded wrapper over the receipt, its journal and its allocations.
--                             The API's plain rupee customer receipt posts through it and NOT through the kernel
--                             (receipt_service._settle_receipt_via_atomic_rpc), and the receipt asks only the
--                             firm's financial-year lock (and the filed-return lock for an advance-GST client),
--                             never the client's finalised year.
--
--   So a receipt dated inside a year the CA had finalised was accepted for everyone including the Partner, and a
--   signed-in person could call either function directly over PostgREST with their own token and post a dated entry
--   into a closed year: the review reproduced it as an assigned Executive, Manager, Reviewer and Partner. This is the
--   other half of the lock migration 532 made visible: 532 made the year readable by the members who post into it,
--   and the two functions that write the ledger had to be made to ask.
--
--   post_journal_atomic is also the one definer function migration 486 did not wrap with the role-pair check, because
--   it already restated the row policies of `journal_entries`. Those policies are SELECT-only for a signed-in
--   user (the function IS the write path), so the role tier the table's other families got in migrations 487 to 489
--   was never put anywhere here: a Reviewer assigned to a client, whom the API refuses on every route that posts,
--   could post straight over PostgREST.
--
-- WHAT THIS DOES (by RENAME, as 486 did, so the long body of post_journal_atomic is not restated and cannot drift
-- from the migration that last defined it, which is 418)
--   * post_journal_atomic is renamed to post_journal_atomic__unguarded (EXECUTE for the service role only) and a
--     SECURITY DEFINER wrapper with the original name, parameter names and return type runs, in this order:
--       1. `assert_caller_acts_for` with the entry's firm and client and the permission pairs the routes that post
--          ask (below): a signed-in caller must have a live member record, name their own firm, a client they can
--          reach (the internal practice client being a Partner's) and hold at least one of those pairs through
--          `my_permission`, which counts the per-person grid. The service role and a connection with no JWT pass
--          as the backend.
--       2. the closure check: `period_closure_reason(firm, client, entry_date)`, asked as the function's owner (the
--          reason it is asked HERE and not left to a policy: row security does not run inside a definer function,
--          and `client_year_locks` is invisible to a member who is not assigned to the client, which is the point
--          of 532). A date that cannot be read is a refusal and not a reason to skip the check (the kernel's
--          ACC-27 rule), and the sentence raised is the closure's own, which names the remedy.
--       3. the original body, unchanged.
--     Between 1 and 2 it also asks that the entry named in `reversal_of`, if any, is an entry of the payload's own firm and
--     client (see the comment at that line): the body's reversal stamp asked neither.
--   * settle_receipt_atomic keeps migration 486's wrapper and gains the same closure check, on the journal's date
--     and on the receipt's date, between 486's caller check and the call to the unguarded body.
--
-- THE PAIRS post_journal_atomic ASKS, AND WHY THEY ARE A UNION
--   A union, because every route that posts asks its own pair and the function cannot know which one called it.
--   Six pairs, read route by route off the handlers that write a journal entry through the request's own sign-in
--   (the independent review of this migration, 22-10-2026): banking:write (Executive: the bank module), accounting:write
--   (Manager: sales and purchase documents, notes, receipts, payments, fixed assets, CWIP, recurring and manual journals,
--   imports), client:write (Manager: creating or editing a customer or vendor posts the opening-balance journal),
--   year_end:approve (Manager: posting an approved adjustment), accounting:approve (Partner: cancelling a document or
--   reversing a receipt, which post the reversal) and payroll:finalize (Partner: the payroll accrual, disbursement and
--   settlement). The lowest tier among them is Executive, so a Reviewer, a Client-role member and a member whose grid
--   denies every one of them cannot post; nothing the API lets a role do through a posting route is refused (the same
--   union semantics settle_receipt_atomic has, which asks accounting:write OR banking:write).
--   THE FIRST READING OVER-COLLECTED AND WAS CORRECTED: it took every non-read pair of every router that posts, which put
--   billing:write, invoice:write (it guards sending a document), payroll:write, year_end:write (it guards drafting an
--   adjustment) and banking:approve into the list although no route that posts asks them. An Executive denied every pair a
--   posting route asks of an Executive could still post over PostgREST through invoice:write, and a Reviewer granted only
--   billing:write could. The list is the pairs that are asked, and tests/test_the_two_ledger_functions_ask_the_closure_and_
--   the_pairs_the_posting_routes_ask.py makes every router that reaches a posting module either have one of them or be on a
--   reviewed list of routers that post nothing, with the reason, so a new router has to be classified.
--   It is a floor and not a per-route check on purpose: a per-route check is the API's rbac(), and this is the
--   second lock. The list is ordered lowest tier first, so an Executive, a Manager and a Partner are each admitted by
--   the first pair that is theirs (one permission lookup for an Executive or a Manager's usual route; measured at about
--   4 ms for the whole guard against 1.6 ms for the old function on a local database, small beside the Singapore to
--   Mumbai round trip).
--
-- WHAT IT DOES NOT DO, AND SAYS SO
--   * It does not ask the FILED-RETURN branch (`period_lock_reason`). The kernel deliberately does not, for the
--     calendar reason migration 361's header records (June's bank work happens after June's returns are filed),
--     and these two functions are the kernel's and the receipt's database half.
--   * It does not make the direct call as narrow as the routes. The function cannot tell a manual journal from a
--     document's journal (the caller names `source_type` and every other column the body honours: `created_by`, `status`,
--     `is_posted`), so a person who holds any one pair above can post any balanced entry for a client they reach over
--     PostgREST, where the API would ask accounting:write for a manual journal. The durable fix is to take the door away
--     (the kernel posting with the privileged client after the route's own checks, and EXECUTE revoked from signed-in
--     users, the shape migrations 499 and 519 gave the payroll tables); that is a change to the hottest write path and is
--     its own ledger item (POST-A-317), not done here.
--   * It does not change what the Python kernel says: the kernel asks first, so a posting through the API is
--     refused with the kernel's own message and this check is only what a direct call reaches.
--   * A posting that is a duplicate of an existing entry is still answered with the existing entry's id by the
--     unguarded body, but only after the closure check passes; the kernel's fast path has the same order.
--   * `edit_posted_journal` and `discard_posted_journal` already ask `journal_period_lock_reason` inside the
--     function and are untouched. No table, policy, row or grant on a table changes. No backfill.
--
-- TO CHANGE post_journal_atomic's LOGIC LATER, REPLACE `post_journal_atomic__unguarded` (derive its body from the
-- migration that last defined the ORIGINAL name, found by number, which is 418 as this is written), never the
-- wrapper: a CREATE OR REPLACE of the public name from an older migration would put the unguarded body back.
--
-- Reversible: 533_..._rollback.sql drops the wrapper, renames the original back with its original grants, and
-- puts migration 486's settle_receipt_atomic wrapper back, which RE-OPENS the hole.


-- ── post_journal_atomic ──────────────────────────────────────────────────────────────────────────────────────
ALTER FUNCTION public.post_journal_atomic(jsonb, jsonb) RENAME TO post_journal_atomic__unguarded;
REVOKE ALL ON FUNCTION public.post_journal_atomic__unguarded(jsonb, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.post_journal_atomic__unguarded(jsonb, jsonb) TO service_role;

CREATE FUNCTION public.post_journal_atomic(p_entry jsonb, p_lines jsonb)
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

REVOKE ALL ON FUNCTION public.post_journal_atomic(jsonb, jsonb) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO authenticated, service_role;


-- ── settle_receipt_atomic ───────────────────────────────────────────────────────────────────────────────────
-- Migration 486's wrapper, verbatim, with the closure check added after its caller check. CREATE OR REPLACE keeps
-- the owner and the grants 486 gave it.
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


-- ── the closing check: both are the guarded wrappers, and the original is out of reach ─────────────────────
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = 'public.post_journal_atomic(jsonb, jsonb)'::regprocedure AND prosecdef) THEN
        RAISE EXCEPTION 'migration 533: post_journal_atomic is not the SECURITY DEFINER wrapper'; END IF;
    IF NOT has_function_privilege('authenticated', 'public.post_journal_atomic(jsonb, jsonb)'::regprocedure, 'EXECUTE')
       OR NOT has_function_privilege('service_role', 'public.post_journal_atomic(jsonb, jsonb)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.post_journal_atomic(jsonb, jsonb)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 533: post_journal_atomic has the wrong grants'; END IF;
    IF has_function_privilege('authenticated', 'public.post_journal_atomic__unguarded(jsonb, jsonb)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.post_journal_atomic__unguarded(jsonb, jsonb)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 533: post_journal_atomic__unguarded is still executable by a signed-in user'; END IF;
    IF NOT has_function_privilege('authenticated', 'public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 533: settle_receipt_atomic has the wrong grants'; END IF;
    IF has_function_privilege('authenticated', 'public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 533: settle_receipt_atomic__unguarded is executable by a signed-in user'; END IF;
END
$$;
