-- Rollback of migration 533. RE-OPENS the hole it closed: a posting dated inside a closed year is accepted again by
-- post_journal_atomic and settle_receipt_atomic, and post_journal_atomic loses its role-pair check.

DROP FUNCTION IF EXISTS public.post_journal_atomic(jsonb, jsonb);
ALTER FUNCTION public.post_journal_atomic__unguarded(jsonb, jsonb) RENAME TO post_journal_atomic;
REVOKE ALL ON FUNCTION public.post_journal_atomic(jsonb, jsonb) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO authenticated, service_role;

-- migration 486's wrapper, verbatim (derived from that file by script, not retyped)
CREATE OR REPLACE FUNCTION public.settle_receipt_atomic(p_receipt jsonb, p_journal_entry jsonb, p_journal_lines jsonb, p_allocations jsonb)
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
