-- Rollback of migration 670: the 'Not Required' state goes. An obligation recorded as not required goes back to 'Not Started' (the
-- state `mark_required_again` puts it in), so the narrower check can be restored; the reason stays in its notes and in the audit log,
-- and its due date says again whether it is late.

BEGIN;

UPDATE public.compliance_records SET status = 'Not Started', updated_at = now() WHERE status = 'Not Required';

ALTER TABLE public.compliance_records DROP CONSTRAINT IF EXISTS compliance_records_status_check;
ALTER TABLE public.compliance_records ADD CONSTRAINT compliance_records_status_check
    CHECK (status IN ('Not Started','Awaiting Documents','In Progress','Ready For Review',
                      'Ready To File','Filed','Completed','Overdue'));

COMMIT;
