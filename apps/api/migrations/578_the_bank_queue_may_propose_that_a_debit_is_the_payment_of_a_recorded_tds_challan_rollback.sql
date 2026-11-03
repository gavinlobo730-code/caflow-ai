-- Rollback of migration 578: the bank queue goes back to four proposal sources.
-- A draft whose source is 'challan' is a PROPOSAL (nothing was posted by it), so it is cleared, together with the columns that go with it
-- (the source and the grade are NULL together by migration 322's pair check), and the line is left to be re-proposed. A line already PASSED
-- from a challan proposal keeps its draft columns as history; they are cleared too, which loses nothing the journal does not hold.
SELECT set_config('lock_timeout', '15s', true);

UPDATE public.bank_transactions
   SET draft_source = NULL, draft_grade = NULL, draft_label = NULL, draft_reason = NULL,
       draft_account_id = NULL, draft_entity_type = NULL, draft_entity_id = NULL, drafted_at = NULL
 WHERE draft_source = 'challan';

ALTER TABLE public.bank_transactions DROP CONSTRAINT IF EXISTS bank_transactions_draft_source_check;
ALTER TABLE public.bank_transactions ADD CONSTRAINT bank_transactions_draft_source_check
  CHECK (draft_source IS NULL OR draft_source IN ('rule', 'document', 'history', 'transfer'));

COMMENT ON COLUMN public.bank_transactions.draft_source IS
  'Where the proposal came from: rule (a human wrote it), document (an open '
  'invoice/bill/receipt/payment with this amount), history (how this payee was '
  'coded before), transfer (the counterpart line on another own account). '
  'NULL = nothing defensible to propose. Written only by bank_entry_service.redraft.';
