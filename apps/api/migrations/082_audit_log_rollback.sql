-- Rollback for 082_audit_log.sql
-- Drops the triggers/function and (optionally) the table. The DROP TABLE is left
-- commented because audit history is valuable and was pre-existing out-of-band;
-- uncomment only if you intend to discard the audit trail.

DROP TRIGGER IF EXISTS trg_audit_log_no_update ON public.audit_log;
DROP TRIGGER IF EXISTS trg_audit_log_no_delete ON public.audit_log;
DROP FUNCTION IF EXISTS public.audit_log_block_mutation();
DROP POLICY IF EXISTS "audit_log_partner_read" ON public.audit_log;
-- DROP TABLE IF EXISTS public.audit_log;
