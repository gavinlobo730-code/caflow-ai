-- Migration 486 — the database functions that write as their owner now ask who is calling
-- (security_privacy, found while building the Reviewer-write fix and confirmed by two independent read-only audits
-- and by a catalogue read of production on 14-10-2026; ledger POST-A-221).
--
-- THE HOLE
--   Nine functions in schema public are SECURITY DEFINER (they run as the table owner, so row security does not
--   apply inside them), are EXECUTE-able by every signed-in user (`authenticated`, which the API's own end-user
--   sign-in is, under USE_USER_JWT) and never check that their arguments belong to the caller. Migration 272
--   closed them to the published `anon` key and recorded, for `numbered_document_atomic`, that the caller names the
--   TABLE and so it is an arbitrary INSERT into any public table as the owner; it left the signed-in caller alone
--   and called that "the next piece of work". This is that piece. Reproduced on a throwaway database copy (never on
--   production): a signed-in identity with no staff record at all could make that one function write a Partner
--   `users` row for itself, which a direct insert refuses.
--
--     numbered_document_atomic        any public table, any row         credit/debit note issue
--     settle_receipt_atomic           a receipt + journal + allocations for any firm and client
--     edit_posted_journal             rewrite any manual journal         the Journal screen
--     discard_posted_journal          delete any manual journal          the Journal screen
--     replace_gstr2b_reconciliation   replace any client's GSTR-2B       the 2B upload
--     record_fee_receipt_atomic       a fee receipt on any firm's fee invoice (fee economics are Partner-only)
--     increment_message_count         bump any conversation's counter
--     get_cash_payments_above_threshold  READ any client's cash payments (anon was closed by 337/272)
--     hub_client_worklist             READ per-client counts and receivable/payable totals for any client of the
--                                     caller's OWN firm, the internal practice client included (it checked the
--                                     firm and left the client ids to its caller, which uses the service role)
--
--   Ids are unguessable UUIDs, so the realistic reach today is inside one firm, where it defeats the role tier and
--   the client assignment: a Reviewer, or an Executive not assigned to a client, could edit or delete any client's
--   manual journal, replace its 2B reconciliation or post a receipt, and could promote themselves by writing rows
--   into `users`, `user_permissions` or `user_client_assignments`. The access matrix could not see it: it tries
--   table writes, and these are function calls.
--
-- WHAT THIS DOES (by RENAME, so no function body is restated and none can drift from production)
--   For each function: ALTER ... RENAME TO <name>__unguarded, take EXECUTE away from PUBLIC, anon and authenticated
--   (the service role keeps it), and create a SECURITY DEFINER wrapper with the ORIGINAL name, parameter names and
--   defaults (PostgREST resolves named arguments, so callers are unchanged) that runs a guard and then calls the
--   original. The guard, `assert_caller_acts_for`, is the check post_journal_atomic has made since migration 271:
--   a signed-in caller must have a live user record, the arguments must name THEIR firm, a client they can reach
--   (the internal practice client being Partner-only), and a permission pair the function's own routes ask,
--   through `my_permission` so the per-person grid counts. A Partner reaches every client id by can_access_client's
--   own rule, so the guard also asks that the client belongs to the firm named:
--
--     numbered_document_atomic   only the four documents the application numbers (credit_notes, debit_notes,
--                                purchase_credit_notes, sales_debit_notes, each with its own lines table), for
--                                EVERYONE; then accounting:write (Manager)
--     settle_receipt_atomic      the receipt and its journal must name one firm and client; accounting:write
--                                (Manager) OR banking:write (Executive: a bank match-multi settles receipts)
--     edit/discard_posted_journal   accounting:write (Manager) and the actor recorded must be the caller
--     replace_gstr2b_reconciliation   gst:compute (Executive)
--     record_fee_receipt_atomic  billing:write (Partner) and the invoice's client
--     increment_message_count    the conversation belongs to the caller's firm
--     get_cash_payments_above_threshold   the caller's firm and reach of the client (a read: no tier)
--     hub_client_worklist        the caller's firm; a signed-in caller who is not a Partner is narrowed to the
--                                clients they can reach and never the internal client, whatever list they pass
--     is_client_fy_locked        no wrapper: nothing in the application or the database calls it, so signed-in
--                                users lose EXECUTE (the service role keeps it)
--
--   The service role, and a connection with no JWT at all (a migration, a test harness), pass as the backend. A JWT
--   that says `authenticated` but names nobody is refused.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * pair_bank_transfer / unpair_bank_transfer are executable by the service role only and are called with the
--     caller's sign-in, so they are refused for everyone: a broken feature, not a hole (ledger POST-A-222).
--   * The nine read-only definer functions that DO compare their arguments with the caller (cash_flow_report,
--     cost_centre_allocation, fx_dated_adjustments, fx_foreign_bank_balances, party_opening_position,
--     schedule_iii_ageing and the three stock_* functions) were read against production and are untouched.
--   * is_fy_locked answers a yes/no about whether a firm has locked a year, for any firm id. Its one caller is the
--     period validator, on the caller's sign-in and failing closed in about sixty-seven places, and it was not
--     traced for every kind of caller, so it is left as it is and recorded (ledger POST-A-221). It is one bit.
--   * No table, policy, row or grant on a table changes. No backfill.
--
-- TO CHANGE ONE OF THESE FUNCTIONS' LOGIC LATER, REPLACE `<name>__unguarded` (derive its body from the migration that
-- last defined the ORIGINAL name, found by number), never the wrapper: a CREATE OR REPLACE of the public name from an
-- older migration would put the unguarded body back. tests/test_a_function_that_runs_as_its_owner_and_a_signed_in_user_
-- can_call_asks_who_is_calling_pg.py fails that.
--
-- Reversible: 486_..._rollback.sql drops the wrappers and the two guards and renames the originals back, which
-- RE-OPENS the hole. Idempotency: the migration runs once (a rename cannot be repeated); the runner records it.



-- ── the two guards every wrapper below calls ────────────────────────────────────────────────────────────────
-- They restate, for a function that bypasses row security, what row security would have asked of the same person
-- (the shape post_journal_atomic has had since migration 271): the caller's firm, their reach of the client, the
-- firm's internal client being Partner-only, and the role tier through `my_permission`, which honours the
-- per-person grid. The service role and a connection with no JWT at all (a migration, a test harness) are the
-- backend and pass; a JWT that says `authenticated` but names nobody does NOT, which is the difference between
-- "no caller" and "a caller we could not identify".

CREATE OR REPLACE FUNCTION public.assert_caller_acts_for(
    p_function text, p_firm uuid, p_client uuid, p_pairs jsonb DEFAULT NULL)
RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    v_claims   text := current_setting('request.jwt.claims', true);
    v_role     text;
    v_my_firm  uuid;
    v_internal uuid;
    v_pair     jsonb;
    v_ok       boolean := false;
BEGIN
    IF v_claims IS NOT NULL AND v_claims <> '' THEN
        BEGIN
            v_role := (v_claims::jsonb) ->> 'role';
        EXCEPTION WHEN others THEN
            v_role := NULL;
        END;
    END IF;
    v_role := COALESCE(v_role, NULLIF(current_setting('request.jwt.claim.role', true), ''));

    IF auth.uid() IS NULL THEN
        IF v_role IN ('authenticated', 'anon') THEN
            RAISE EXCEPTION '%: the request names no signed-in person', p_function USING ERRCODE = '42501';
        END IF;
        RETURN;
    END IF;

    v_my_firm := public.get_my_firm_id();
    IF v_my_firm IS NULL THEN
        RAISE EXCEPTION '%: the caller has no live user record in this database', p_function
            USING ERRCODE = '42501';
    END IF;
    IF p_firm IS NULL OR p_firm IS DISTINCT FROM v_my_firm THEN
        RAISE EXCEPTION '%: firm % is not the caller''s firm', p_function, p_firm USING ERRCODE = '42501';
    END IF;

    IF p_client IS NOT NULL THEN
        -- A Partner reaches every client id by can_access_client's own rule, so the client must be asked to
        -- belong to the FIRM named: otherwise a Partner could point their own firm's document at another firm's client.
        IF NOT EXISTS (SELECT 1 FROM public.clients c WHERE c.id = p_client AND c.firm_id = p_firm) THEN
            RAISE EXCEPTION '%: client % is not a client of firm %', p_function, p_client, p_firm
                USING ERRCODE = '42501';
        END IF;
        IF NOT public.can_access_client(p_client::text) THEN
            RAISE EXCEPTION '%: client % is not one the caller can reach', p_function, p_client
                USING ERRCODE = '42501';
        END IF;
        v_internal := public.my_internal_client_id();
        IF v_internal IS NOT NULL AND p_client = v_internal AND COALESCE(public.get_my_role(), '') <> 'Partner' THEN
            RAISE EXCEPTION '%: only a Partner may act on the firm''s internal client', p_function
                USING ERRCODE = '42501';
        END IF;
    END IF;

    IF p_pairs IS NOT NULL THEN
        FOR v_pair IN SELECT value FROM jsonb_array_elements(p_pairs) LOOP
            IF public.my_permission(v_pair ->> 0, v_pair ->> 1, v_pair ->> 2) THEN
                v_ok := true;
                EXIT;
            END IF;
        END LOOP;
        IF NOT v_ok THEN
            RAISE EXCEPTION '%: the caller''s role or access grid does not allow this', p_function
                USING ERRCODE = '42501';
        END IF;
    END IF;
END;
$fn$;

CREATE OR REPLACE FUNCTION public.assert_caller_is_actor(p_function text, p_actor uuid)
RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
BEGIN
    -- The actor is written into the edit log. A signed-in caller may name themselves (the API passes either the
    -- auth id or the users.id, depending on the route) and nobody else; a backend call may name whom it acts for.
    IF p_actor IS NULL OR auth.uid() IS NULL THEN
        RETURN;
    END IF;
    IF p_actor IS DISTINCT FROM auth.uid() AND p_actor IS DISTINCT FROM public.get_my_user_id() THEN
        RAISE EXCEPTION '%: the actor recorded must be the caller', p_function USING ERRCODE = '42501';
    END IF;
END;
$fn$;

REVOKE ALL ON FUNCTION public.assert_caller_acts_for(text, uuid, uuid, jsonb) FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.assert_caller_is_actor(text, uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.assert_caller_acts_for(text, uuid, uuid, jsonb) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.assert_caller_is_actor(text, uuid) TO authenticated, service_role;


-- ── numbered_document_atomic ───────────────────────────────────────────────────────────────
ALTER FUNCTION public.numbered_document_atomic(text, jsonb, text, jsonb, text) RENAME TO numbered_document_atomic__unguarded;
REVOKE ALL ON FUNCTION public.numbered_document_atomic__unguarded(text, jsonb, text, jsonb, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.numbered_document_atomic__unguarded(text, jsonb, text, jsonb, text) TO service_role;

CREATE FUNCTION public.numbered_document_atomic(p_header_table text, p_header jsonb, p_lines_table text, p_lines jsonb, p_lines_fk_column text)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    -- (nothing to declare)
BEGIN
    -- THE CALLER NAMES THE TABLE, so this is the whole of the protection for everyone, the service role
    -- included: only the four numbered documents the application creates, each with its own lines table.
    IF NOT (p_header_table, p_lines_table, p_lines_fk_column) IN (
         ('credit_notes',          'credit_note_lines',          'credit_note_id'),
         ('debit_notes',           'debit_note_lines',           'debit_note_id'),
         ('purchase_credit_notes', 'purchase_credit_note_lines', 'credit_note_id'),
         ('sales_debit_notes',     'sales_debit_note_lines',     'debit_note_id')) THEN
        RAISE EXCEPTION 'numbered_document_atomic: % with lines in % is not a numbered document',
            p_header_table, p_lines_table USING ERRCODE = '42501';
    END IF;
    PERFORM public.assert_caller_acts_for('numbered_document_atomic',
        NULLIF(p_header->>'firm_id', '')::uuid, NULLIF(p_header->>'client_id', '')::uuid,
        '[["accounting","write","Manager"]]'::jsonb);
    RETURN public.numbered_document_atomic__unguarded(p_header_table, p_header, p_lines_table, p_lines, p_lines_fk_column);
END;
$fn$;

REVOKE ALL ON FUNCTION public.numbered_document_atomic(text, jsonb, text, jsonb, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.numbered_document_atomic(text, jsonb, text, jsonb, text) TO authenticated, service_role;


-- ── settle_receipt_atomic ───────────────────────────────────────────────────────────────
ALTER FUNCTION public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb) RENAME TO settle_receipt_atomic__unguarded;
REVOKE ALL ON FUNCTION public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb) TO service_role;

CREATE FUNCTION public.settle_receipt_atomic(p_receipt jsonb, p_journal_entry jsonb, p_journal_lines jsonb, p_allocations jsonb)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    -- (nothing to declare)
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
    RETURN public.settle_receipt_atomic__unguarded(p_receipt, p_journal_entry, p_journal_lines, p_allocations);
END;
$fn$;

REVOKE ALL ON FUNCTION public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb) TO authenticated, service_role;


-- ── edit_posted_journal ───────────────────────────────────────────────────────────────
ALTER FUNCTION public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid) RENAME TO edit_posted_journal__unguarded;
REVOKE ALL ON FUNCTION public.edit_posted_journal__unguarded(uuid, uuid, uuid, jsonb, text, text, date, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.edit_posted_journal__unguarded(uuid, uuid, uuid, jsonb, text, text, date, uuid) TO service_role;

CREATE FUNCTION public.edit_posted_journal(p_firm uuid, p_client uuid, p_entry_id uuid, p_lines jsonb, p_narration text DEFAULT NULL, p_reference_no text DEFAULT NULL, p_entry_date date DEFAULT NULL, p_actor uuid DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    -- (nothing to declare)
BEGIN
    PERFORM public.assert_caller_acts_for('edit_posted_journal', p_firm, p_client,
        '[["accounting","write","Manager"]]'::jsonb);
    PERFORM public.assert_caller_is_actor('edit_posted_journal', p_actor);
    RETURN public.edit_posted_journal__unguarded(p_firm, p_client, p_entry_id, p_lines, p_narration, p_reference_no, p_entry_date, p_actor);
END;
$fn$;

REVOKE ALL ON FUNCTION public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid) TO authenticated, service_role;


-- ── discard_posted_journal ───────────────────────────────────────────────────────────────
ALTER FUNCTION public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean) RENAME TO discard_posted_journal__unguarded;
REVOKE ALL ON FUNCTION public.discard_posted_journal__unguarded(uuid, uuid, uuid, uuid, boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.discard_posted_journal__unguarded(uuid, uuid, uuid, uuid, boolean) TO service_role;

CREATE FUNCTION public.discard_posted_journal(p_firm uuid, p_client uuid, p_entry_id uuid, p_actor uuid DEFAULT NULL, p_with_pair boolean DEFAULT false)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    -- (nothing to declare)
BEGIN
    PERFORM public.assert_caller_acts_for('discard_posted_journal', p_firm, p_client,
        '[["accounting","write","Manager"]]'::jsonb);
    PERFORM public.assert_caller_is_actor('discard_posted_journal', p_actor);
    RETURN public.discard_posted_journal__unguarded(p_firm, p_client, p_entry_id, p_actor, p_with_pair);
END;
$fn$;

REVOKE ALL ON FUNCTION public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean) TO authenticated, service_role;


-- ── replace_gstr2b_reconciliation ───────────────────────────────────────────────────────────────
ALTER FUNCTION public.replace_gstr2b_reconciliation(uuid, uuid, text, jsonb, jsonb) RENAME TO replace_gstr2b_reconciliation__unguarded;
REVOKE ALL ON FUNCTION public.replace_gstr2b_reconciliation__unguarded(uuid, uuid, text, jsonb, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.replace_gstr2b_reconciliation__unguarded(uuid, uuid, text, jsonb, jsonb) TO service_role;

CREATE FUNCTION public.replace_gstr2b_reconciliation(p_firm_id uuid, p_client_id uuid, p_period text, p_documents jsonb, p_header jsonb)
RETURNS TABLE (document_count INTEGER)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    -- (nothing to declare)
BEGIN
    PERFORM public.assert_caller_acts_for('replace_gstr2b_reconciliation', p_firm_id, p_client_id,
        '[["gst","compute","Executive"]]'::jsonb);
    RETURN QUERY SELECT * FROM public.replace_gstr2b_reconciliation__unguarded(p_firm_id, p_client_id, p_period, p_documents, p_header);
END;
$fn$;

REVOKE ALL ON FUNCTION public.replace_gstr2b_reconciliation(uuid, uuid, text, jsonb, jsonb) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.replace_gstr2b_reconciliation(uuid, uuid, text, jsonb, jsonb) TO authenticated, service_role;


-- ── record_fee_receipt_atomic ───────────────────────────────────────────────────────────────
ALTER FUNCTION public.record_fee_receipt_atomic(uuid, uuid, date, bigint, text, text, text) RENAME TO record_fee_receipt_atomic__unguarded;
REVOKE ALL ON FUNCTION public.record_fee_receipt_atomic__unguarded(uuid, uuid, date, bigint, text, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_fee_receipt_atomic__unguarded(uuid, uuid, date, bigint, text, text, text) TO service_role;

CREATE FUNCTION public.record_fee_receipt_atomic(p_firm_id uuid, p_invoice_id uuid, p_receipt_date date, p_amount_paise bigint, p_payment_mode text, p_reference_no text, p_notes text)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    v_client uuid;
BEGIN
    SELECT i.client_id INTO v_client
      FROM public.fee_invoices i WHERE i.id = p_invoice_id AND i.firm_id = p_firm_id;
    -- Fee economics are Partner-only (billing:write); an invoice that is not this firm's is refused by the
    -- function itself once the firm is known to be the caller's.
    PERFORM public.assert_caller_acts_for('record_fee_receipt_atomic', p_firm_id, v_client,
        '[["billing","write","Partner"]]'::jsonb);
    RETURN public.record_fee_receipt_atomic__unguarded(p_firm_id, p_invoice_id, p_receipt_date, p_amount_paise, p_payment_mode, p_reference_no, p_notes);
END;
$fn$;

REVOKE ALL ON FUNCTION public.record_fee_receipt_atomic(uuid, uuid, date, bigint, text, text, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.record_fee_receipt_atomic(uuid, uuid, date, bigint, text, text, text) TO authenticated, service_role;


-- ── increment_message_count ───────────────────────────────────────────────────────────────
ALTER FUNCTION public.increment_message_count(uuid) RENAME TO increment_message_count__unguarded;
REVOKE ALL ON FUNCTION public.increment_message_count__unguarded(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.increment_message_count__unguarded(uuid) TO service_role;

CREATE FUNCTION public.increment_message_count(conv_id uuid)
RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    v_firm uuid;
BEGIN
    SELECT c.firm_id INTO v_firm FROM public.ai_conversations c WHERE c.id = conv_id;
    IF v_firm IS NOT NULL THEN
        PERFORM public.assert_caller_acts_for('increment_message_count', v_firm, NULL, NULL);
    END IF;
    RETURN public.increment_message_count__unguarded(conv_id);
END;
$fn$;

REVOKE ALL ON FUNCTION public.increment_message_count(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.increment_message_count(uuid) TO authenticated, service_role;


-- ── get_cash_payments_above_threshold ───────────────────────────────────────────────────────────────
ALTER FUNCTION public.get_cash_payments_above_threshold(uuid, uuid, bigint) RENAME TO get_cash_payments_above_threshold__unguarded;
REVOKE ALL ON FUNCTION public.get_cash_payments_above_threshold__unguarded(uuid, uuid, bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_cash_payments_above_threshold__unguarded(uuid, uuid, bigint) TO service_role;

CREATE FUNCTION public.get_cash_payments_above_threshold(p_firm_id uuid, p_client_id uuid, p_threshold_paise bigint)
RETURNS TABLE (journal_entry_id uuid, narration text, amount_paise bigint, entry_date date, counterparty_account text, entry_count bigint)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    -- (nothing to declare)
BEGIN
    -- A read, so the caller's firm and their reach of the client are the whole of the check (no role tier).
    PERFORM public.assert_caller_acts_for('get_cash_payments_above_threshold', p_firm_id, p_client_id, NULL);
    RETURN QUERY SELECT * FROM public.get_cash_payments_above_threshold__unguarded(p_firm_id, p_client_id, p_threshold_paise);
END;
$fn$;

REVOKE ALL ON FUNCTION public.get_cash_payments_above_threshold(uuid, uuid, bigint) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.get_cash_payments_above_threshold(uuid, uuid, bigint) TO authenticated, service_role;


-- ── hub_client_worklist ───────────────────────────────────────────────────────────────
ALTER FUNCTION public.hub_client_worklist(uuid, text, uuid[]) RENAME TO hub_client_worklist__unguarded;
REVOKE ALL ON FUNCTION public.hub_client_worklist__unguarded(uuid, text, uuid[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.hub_client_worklist__unguarded(uuid, text, uuid[]) TO service_role;

CREATE FUNCTION public.hub_client_worklist(p_firm uuid, p_tile text, p_client_ids uuid[] DEFAULT NULL)
RETURNS TABLE (client_id uuid, signal bigint)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    v_ids uuid[];
BEGIN
    PERFORM public.assert_caller_acts_for('hub_client_worklist', p_firm, NULL, NULL);
    v_ids := p_client_ids;
    -- The function checks the FIRM and then filters by the client ids it is GIVEN. A signed-in caller who is not a
    -- Partner is narrowed to the clients they can reach, and never to the firm's internal practice client, whatever
    -- they passed (a NULL list means "all of them", which for them means all of THEIRS). The application's own
    -- caller already passes exactly that list, so for it nothing changes.
    IF auth.uid() IS NOT NULL AND COALESCE(public.get_my_role(), '') <> 'Partner' THEN
        v_ids := ARRAY(SELECT c.id FROM public.clients c
                        WHERE c.firm_id = p_firm
                          AND (p_client_ids IS NULL OR c.id = ANY (p_client_ids))
                          AND public.can_access_client(c.id::text)
                          AND c.id IS DISTINCT FROM public.my_internal_client_id());
    END IF;
    RETURN QUERY SELECT * FROM public.hub_client_worklist__unguarded(p_firm, p_tile, v_ids);
END;
$fn$;

REVOKE ALL ON FUNCTION public.hub_client_worklist(uuid, text, uuid[]) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.hub_client_worklist(uuid, text, uuid[]) TO authenticated, service_role;


-- ── is_client_fy_locked: nothing calls it and nothing depends on it, so a signed-in user has no use for it ───
-- (a yes/no about whether ANY firm's client has locked a year; the service role keeps it)
REVOKE ALL ON FUNCTION public.is_client_fy_locked(uuid, uuid, date) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.is_client_fy_locked(uuid, uuid, date) TO service_role;


-- ── the closing check: each function is the guarded wrapper, and the original is out of reach ───────────────
DO $$
BEGIN
    IF has_function_privilege('authenticated', 'public.is_client_fy_locked(uuid, uuid, date)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: is_client_fy_locked is still executable by a signed-in user'; END IF;
    -- numbered_document_atomic
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = 'public.numbered_document_atomic(text, jsonb, text, jsonb, text)'::regprocedure AND prosecdef) THEN
        RAISE EXCEPTION 'migration 486: numbered_document_atomic is not the SECURITY DEFINER wrapper'; END IF;
    IF NOT has_function_privilege('authenticated', 'public.numbered_document_atomic(text, jsonb, text, jsonb, text)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.numbered_document_atomic(text, jsonb, text, jsonb, text)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: numbered_document_atomic has the wrong grants'; END IF;
    IF has_function_privilege('authenticated', 'public.numbered_document_atomic__unguarded(text, jsonb, text, jsonb, text)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.numbered_document_atomic__unguarded(text, jsonb, text, jsonb, text)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: numbered_document_atomic__unguarded is still executable by a signed-in user'; END IF;
    -- settle_receipt_atomic
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = 'public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb)'::regprocedure AND prosecdef) THEN
        RAISE EXCEPTION 'migration 486: settle_receipt_atomic is not the SECURITY DEFINER wrapper'; END IF;
    IF NOT has_function_privilege('authenticated', 'public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: settle_receipt_atomic has the wrong grants'; END IF;
    IF has_function_privilege('authenticated', 'public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: settle_receipt_atomic__unguarded is still executable by a signed-in user'; END IF;
    -- edit_posted_journal
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = 'public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid)'::regprocedure AND prosecdef) THEN
        RAISE EXCEPTION 'migration 486: edit_posted_journal is not the SECURITY DEFINER wrapper'; END IF;
    IF NOT has_function_privilege('authenticated', 'public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: edit_posted_journal has the wrong grants'; END IF;
    IF has_function_privilege('authenticated', 'public.edit_posted_journal__unguarded(uuid, uuid, uuid, jsonb, text, text, date, uuid)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.edit_posted_journal__unguarded(uuid, uuid, uuid, jsonb, text, text, date, uuid)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: edit_posted_journal__unguarded is still executable by a signed-in user'; END IF;
    -- discard_posted_journal
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = 'public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean)'::regprocedure AND prosecdef) THEN
        RAISE EXCEPTION 'migration 486: discard_posted_journal is not the SECURITY DEFINER wrapper'; END IF;
    IF NOT has_function_privilege('authenticated', 'public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: discard_posted_journal has the wrong grants'; END IF;
    IF has_function_privilege('authenticated', 'public.discard_posted_journal__unguarded(uuid, uuid, uuid, uuid, boolean)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.discard_posted_journal__unguarded(uuid, uuid, uuid, uuid, boolean)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: discard_posted_journal__unguarded is still executable by a signed-in user'; END IF;
    -- replace_gstr2b_reconciliation
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = 'public.replace_gstr2b_reconciliation(uuid, uuid, text, jsonb, jsonb)'::regprocedure AND prosecdef) THEN
        RAISE EXCEPTION 'migration 486: replace_gstr2b_reconciliation is not the SECURITY DEFINER wrapper'; END IF;
    IF NOT has_function_privilege('authenticated', 'public.replace_gstr2b_reconciliation(uuid, uuid, text, jsonb, jsonb)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.replace_gstr2b_reconciliation(uuid, uuid, text, jsonb, jsonb)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: replace_gstr2b_reconciliation has the wrong grants'; END IF;
    IF has_function_privilege('authenticated', 'public.replace_gstr2b_reconciliation__unguarded(uuid, uuid, text, jsonb, jsonb)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.replace_gstr2b_reconciliation__unguarded(uuid, uuid, text, jsonb, jsonb)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: replace_gstr2b_reconciliation__unguarded is still executable by a signed-in user'; END IF;
    -- record_fee_receipt_atomic
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = 'public.record_fee_receipt_atomic(uuid, uuid, date, bigint, text, text, text)'::regprocedure AND prosecdef) THEN
        RAISE EXCEPTION 'migration 486: record_fee_receipt_atomic is not the SECURITY DEFINER wrapper'; END IF;
    IF NOT has_function_privilege('authenticated', 'public.record_fee_receipt_atomic(uuid, uuid, date, bigint, text, text, text)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.record_fee_receipt_atomic(uuid, uuid, date, bigint, text, text, text)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: record_fee_receipt_atomic has the wrong grants'; END IF;
    IF has_function_privilege('authenticated', 'public.record_fee_receipt_atomic__unguarded(uuid, uuid, date, bigint, text, text, text)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.record_fee_receipt_atomic__unguarded(uuid, uuid, date, bigint, text, text, text)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: record_fee_receipt_atomic__unguarded is still executable by a signed-in user'; END IF;
    -- increment_message_count
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = 'public.increment_message_count(uuid)'::regprocedure AND prosecdef) THEN
        RAISE EXCEPTION 'migration 486: increment_message_count is not the SECURITY DEFINER wrapper'; END IF;
    IF NOT has_function_privilege('authenticated', 'public.increment_message_count(uuid)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.increment_message_count(uuid)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: increment_message_count has the wrong grants'; END IF;
    IF has_function_privilege('authenticated', 'public.increment_message_count__unguarded(uuid)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.increment_message_count__unguarded(uuid)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: increment_message_count__unguarded is still executable by a signed-in user'; END IF;
    -- get_cash_payments_above_threshold
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = 'public.get_cash_payments_above_threshold(uuid, uuid, bigint)'::regprocedure AND prosecdef) THEN
        RAISE EXCEPTION 'migration 486: get_cash_payments_above_threshold is not the SECURITY DEFINER wrapper'; END IF;
    IF NOT has_function_privilege('authenticated', 'public.get_cash_payments_above_threshold(uuid, uuid, bigint)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.get_cash_payments_above_threshold(uuid, uuid, bigint)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: get_cash_payments_above_threshold has the wrong grants'; END IF;
    IF has_function_privilege('authenticated', 'public.get_cash_payments_above_threshold__unguarded(uuid, uuid, bigint)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.get_cash_payments_above_threshold__unguarded(uuid, uuid, bigint)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: get_cash_payments_above_threshold__unguarded is still executable by a signed-in user'; END IF;
    -- hub_client_worklist
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = 'public.hub_client_worklist(uuid, text, uuid[])'::regprocedure AND prosecdef) THEN
        RAISE EXCEPTION 'migration 486: hub_client_worklist is not the SECURITY DEFINER wrapper'; END IF;
    IF NOT has_function_privilege('authenticated', 'public.hub_client_worklist(uuid, text, uuid[])'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.hub_client_worklist(uuid, text, uuid[])'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: hub_client_worklist has the wrong grants'; END IF;
    IF has_function_privilege('authenticated', 'public.hub_client_worklist__unguarded(uuid, text, uuid[])'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.hub_client_worklist__unguarded(uuid, text, uuid[])'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 486: hub_client_worklist__unguarded is still executable by a signed-in user'; END IF;
END $$;
