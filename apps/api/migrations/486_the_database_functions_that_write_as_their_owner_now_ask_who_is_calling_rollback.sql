


DROP FUNCTION IF EXISTS public.hub_client_worklist(uuid, text, uuid[]);
ALTER FUNCTION public.hub_client_worklist__unguarded(uuid, text, uuid[]) RENAME TO hub_client_worklist;
GRANT EXECUTE ON FUNCTION public.hub_client_worklist(uuid, text, uuid[]) TO authenticated, service_role;

DROP FUNCTION IF EXISTS public.get_cash_payments_above_threshold(uuid, uuid, bigint);
ALTER FUNCTION public.get_cash_payments_above_threshold__unguarded(uuid, uuid, bigint) RENAME TO get_cash_payments_above_threshold;
GRANT EXECUTE ON FUNCTION public.get_cash_payments_above_threshold(uuid, uuid, bigint) TO authenticated, service_role;

DROP FUNCTION IF EXISTS public.increment_message_count(uuid);
ALTER FUNCTION public.increment_message_count__unguarded(uuid) RENAME TO increment_message_count;
GRANT EXECUTE ON FUNCTION public.increment_message_count(uuid) TO authenticated, service_role;

DROP FUNCTION IF EXISTS public.record_fee_receipt_atomic(uuid, uuid, date, bigint, text, text, text);
ALTER FUNCTION public.record_fee_receipt_atomic__unguarded(uuid, uuid, date, bigint, text, text, text) RENAME TO record_fee_receipt_atomic;
GRANT EXECUTE ON FUNCTION public.record_fee_receipt_atomic(uuid, uuid, date, bigint, text, text, text) TO authenticated, service_role;

DROP FUNCTION IF EXISTS public.replace_gstr2b_reconciliation(uuid, uuid, text, jsonb, jsonb);
ALTER FUNCTION public.replace_gstr2b_reconciliation__unguarded(uuid, uuid, text, jsonb, jsonb) RENAME TO replace_gstr2b_reconciliation;
GRANT EXECUTE ON FUNCTION public.replace_gstr2b_reconciliation(uuid, uuid, text, jsonb, jsonb) TO authenticated, service_role;

DROP FUNCTION IF EXISTS public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean);
ALTER FUNCTION public.discard_posted_journal__unguarded(uuid, uuid, uuid, uuid, boolean) RENAME TO discard_posted_journal;
GRANT EXECUTE ON FUNCTION public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean) TO authenticated, service_role;

DROP FUNCTION IF EXISTS public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid);
ALTER FUNCTION public.edit_posted_journal__unguarded(uuid, uuid, uuid, jsonb, text, text, date, uuid) RENAME TO edit_posted_journal;
GRANT EXECUTE ON FUNCTION public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid) TO authenticated, service_role;

DROP FUNCTION IF EXISTS public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb);
ALTER FUNCTION public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb) RENAME TO settle_receipt_atomic;
GRANT EXECUTE ON FUNCTION public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb) TO authenticated, service_role;

DROP FUNCTION IF EXISTS public.numbered_document_atomic(text, jsonb, text, jsonb, text);
ALTER FUNCTION public.numbered_document_atomic__unguarded(text, jsonb, text, jsonb, text) RENAME TO numbered_document_atomic;
GRANT EXECUTE ON FUNCTION public.numbered_document_atomic(text, jsonb, text, jsonb, text) TO authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.is_client_fy_locked(uuid, uuid, date) TO authenticated;
DROP FUNCTION IF EXISTS public.assert_caller_is_actor(text, uuid);
DROP FUNCTION IF EXISTS public.assert_caller_acts_for(text, uuid, uuid, jsonb);
