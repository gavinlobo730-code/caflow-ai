-- Migration 577 — issuing a sales invoice posts its ledger entry and marks the invoice issued in ONE transaction (POST-A-092).
--
-- WHAT IS WRONG TODAY
--   The issue route posts the invoice's journal entry first (through post_journal_atomic) and then, in a SEPARATE statement, marks the
--   invoice issued and links the entry. The order was chosen so a posting failure leaves a re-tryable draft, and it is right as far
--   as it goes. What it cannot do is survive a failure BETWEEN the two statements: a network blip between the API in Singapore and
--   the database in Mumbai, a restart, a timeout. Then the revenue and the output tax are in the ledger and the customer's balance,
--   while the invoice is still a draft that the invoice list, the receipts screen and GSTR-1 do not count. The retry is safe only
--   because the kernel reuses an entry that is already live under the same number and date (and, since the first half of POST-A-092,
--   only if it carries the same figures), and until somebody retries, nothing says the two disagree.
--   The same gap lets two simultaneous clicks on Issue both reach the stock and the timeline: the second finds the entry the first
--   posted, reuses it and flips the invoice again.
--
-- WHAT THIS DOES
--   public.issue_sales_invoice_atomic(p_invoice_id uuid, p_entry jsonb, p_lines jsonb, p_issued_at timestamptz) RETURNS uuid:
--     * asks who is calling (assert_caller_acts_for, accounting:write at Manager, the pair the issue route asks) and, for a caller with
--       no JWT (the API's privileged client), that the client in the payload is a client of the firm in the payload (migration 546's
--       question);
--     * LOCKS the invoice row (FOR UPDATE), which must belong to the payload's firm and client and still be a DRAFT with no journal
--       link: a second simultaneous issue waits on the lock, then finds an issued invoice and is refused (SQLSTATE 55000, "is not a
--       draft"); it neither posts nor flips anything;
--     * refuses an entry that is not this invoice's own: its reference must be the invoice's number, its date the invoice's date, its
--       source this invoice, its type Sales and it must be posted. The invoice row is the authority for all of them, so the function
--       cannot be used to post some other entry and mark an invoice issued on the strength of it;
--     * posts the entry by calling public.post_journal_atomic, which keeps every check it has (the closure, the audit actor,
--       the duplicate handling that returns the live entry already under the number and date), and then writes status = 'issued',
--       issued_at and journal_entry_id on the locked row. Both happen in the function's single transaction: a failure at any point
--       (the lines, the closure, the update) undoes the entry as well, which is the property this migration exists for.
--   EXECUTE is the server's alone (service_role), as migration 546 left the ledger functions: the API calls it through its privileged
--   client, after the route's own checks, carrying the posting person (services/ledger_door.py). The status trigger of migration 544
--   judges an UPDATE by current_user, which inside this SECURITY DEFINER function is the owner, so the write passes exactly as the
--   settlement written by settle_receipt_atomic does.
--
-- WHAT IT DOES NOT DO
--   * It does not recompute the entry's figures from the invoice: the lines are the route's, built from the draft as the route read it. A
--     member's own token can still change a draft's header between that read and the lock (migration 541 leaves a draft's particulars to
--     the API, and POST-A-335 asks the route to check the draft adds up to its lines BEFORE it issues); that window is unchanged by this
--     migration, which closes the one between the entry and the status.
--   * It decides nothing about WHETHER an invoice may be issued. The locked year, a filed return, the number's rules, the place of
--     supply, whether the draft adds up to its lines and the chart of accounts are all asked by the route (issue_readiness_service)
--     before this is called, and the closure is asked again by post_journal_atomic.
--   * It does not touch stock: the inventory movements and their cost-of-goods entry follow the issue as before and are reported on
--     the response (the stock half of POST-A-092 stays open and is recorded on its ledger line).
--   * It does not repair an invoice that an EARLIER issue stranded (a draft with a live entry): issuing it again now finishes it
--     (the duplicate handling returns the live entry and the invoice is marked issued with it). The API lists such invoices.
--
-- Reversible: 577_..._rollback.sql drops the function.

CREATE OR REPLACE FUNCTION public.issue_sales_invoice_atomic(p_invoice_id uuid, p_entry jsonb, p_lines jsonb, p_issued_at timestamptz)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    v_firm   uuid;
    v_client uuid;
    v_inv    record;
    v_entry  uuid;
    v_date   date;
    v_rows   integer;
BEGIN
    IF p_invoice_id IS NULL OR p_entry IS NULL OR p_entry = '{}'::jsonb OR p_lines IS NULL THEN
        RAISE EXCEPTION 'issue_sales_invoice_atomic: an invoice, its entry and its lines are all required';
    END IF;

    v_firm   := NULLIF(p_entry->>'firm_id', '')::uuid;
    v_client := NULLIF(p_entry->>'client_id', '')::uuid;

    PERFORM public.assert_caller_acts_for('issue_sales_invoice_atomic', v_firm, v_client,
        '[["accounting","write","Manager"]]'::jsonb);

    -- Migration 546's question for a caller with no JWT: the client in the payload belongs to the firm in the payload.
    IF auth.uid() IS NULL AND NOT EXISTS (
            SELECT 1 FROM public.clients c WHERE c.id = v_client AND c.firm_id = v_firm) THEN
        RAISE EXCEPTION 'issue_sales_invoice_atomic: client % is not a client of firm %', v_client, v_firm USING ERRCODE = '42501';
    END IF;

    -- THE LOCK. A second simultaneous issue of this invoice waits here, and then sees an issued invoice.
    SELECT i.id, i.invoice_no, i.invoice_date, i.status, i.journal_entry_id, i.deleted_at
      INTO v_inv
      FROM public.client_sales_invoices i
     WHERE i.id = p_invoice_id AND i.firm_id = v_firm AND i.client_id = v_client
       FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'issue_sales_invoice_atomic: % is not an invoice of this client', p_invoice_id USING ERRCODE = '42501';
    END IF;
    IF v_inv.deleted_at IS NOT NULL THEN
        RAISE EXCEPTION 'issue_sales_invoice_atomic: the invoice has been removed and is not a draft to issue' USING ERRCODE = '55000';
    END IF;
    IF v_inv.status IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION 'issue_sales_invoice_atomic: the invoice is % and not a draft', COALESCE(v_inv.status, 'unknown')
            USING ERRCODE = '55000';
    END IF;
    IF v_inv.journal_entry_id IS NOT NULL THEN
        RAISE EXCEPTION 'issue_sales_invoice_atomic: the draft is already linked to a ledger entry' USING ERRCODE = '55000';
    END IF;

    -- THE ENTRY MUST BE THIS INVOICE'S OWN. The invoice row decides what the entry is called, when it is dated and what it belongs to.
    BEGIN
        v_date := NULLIF(p_entry->>'entry_date', '')::date;
    EXCEPTION WHEN others THEN
        v_date := NULL;
    END;
    IF p_entry->>'reference_no' IS DISTINCT FROM v_inv.invoice_no
       OR v_date IS DISTINCT FROM v_inv.invoice_date
       OR p_entry->>'source_id' IS DISTINCT FROM p_invoice_id::text
       OR p_entry->>'source_type' IS DISTINCT FROM 'sales_invoice'
       OR p_entry->>'entry_type' IS DISTINCT FROM 'Sales'
       OR COALESCE((p_entry->>'is_posted')::boolean, false) IS NOT TRUE THEN
        RAISE EXCEPTION 'issue_sales_invoice_atomic: the entry is not the posted Sales entry of this invoice (number, date, source and type must be its own)'
            USING ERRCODE = '42501';
    END IF;

    v_entry := public.post_journal_atomic(p_entry, p_lines);
    IF v_entry IS NULL THEN
        RAISE EXCEPTION 'issue_sales_invoice_atomic: the ledger entry was not posted';
    END IF;
    -- The entry the posting returned must BE this invoice's: its duplicate handling returns whatever live entry sits under the same firm,
    -- client, reference and date, and the unique index does not look at the entry's type or source, so a different document numbered the
    -- same on the same day could be handed back. Marking the invoice issued against it would link the invoice to another document's entry.
    IF NOT EXISTS (
            SELECT 1 FROM public.journal_entries e
             WHERE e.id = v_entry AND e.firm_id = v_firm AND e.client_id = v_client
               AND e.entry_type = 'Sales' AND e.source_type = 'sales_invoice' AND e.source_id = p_invoice_id
               AND e.is_posted AND e.deleted_at IS NULL AND NOT COALESCE(e.is_reversed, false)) THEN
        RAISE EXCEPTION 'issue_sales_invoice_atomic: the ledger entry under this invoice''s number and date is not this invoice''s own posted Sales entry'
            USING ERRCODE = '42501';
    END IF;

    UPDATE public.client_sales_invoices
       SET status = 'issued', issued_at = COALESCE(p_issued_at, now()), journal_entry_id = v_entry
     WHERE id = p_invoice_id AND firm_id = v_firm AND client_id = v_client AND status = 'draft';
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    IF v_rows <> 1 THEN
        RAISE EXCEPTION 'issue_sales_invoice_atomic: the invoice could not be marked issued' USING ERRCODE = '55000';
    END IF;

    RETURN v_entry;
END;
$fn$;

REVOKE ALL ON FUNCTION public.issue_sales_invoice_atomic(uuid, jsonb, jsonb, timestamptz) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.issue_sales_invoice_atomic(uuid, jsonb, jsonb, timestamptz) TO service_role;

DO $$
DECLARE
    v_fn regprocedure := 'public.issue_sales_invoice_atomic(uuid, jsonb, jsonb, timestamptz)'::regprocedure;
BEGIN
    IF has_function_privilege('authenticated', v_fn, 'EXECUTE') OR has_function_privilege('anon', v_fn, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 577: % is executable by a signed-in user', v_fn; END IF;
    IF NOT has_function_privilege('service_role', v_fn, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 577: % is not executable by the service role', v_fn; END IF;
    IF position('FOR UPDATE' IN upper(pg_get_functiondef(v_fn))) = 0
       OR position('post_journal_atomic' IN pg_get_functiondef(v_fn)) = 0
       OR position('assert_caller_acts_for' IN pg_get_functiondef(v_fn)) = 0 THEN
        RAISE EXCEPTION 'migration 577: % lost its lock, its call to the ledger or its caller check', v_fn; END IF;
END
$$;
