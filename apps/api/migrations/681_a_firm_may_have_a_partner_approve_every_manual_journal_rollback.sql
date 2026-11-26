-- Rollback of migration 681: drops the firm's manual-journal approval switch. The API reads a missing column as FALSE, so after this every
-- firm is back to "anyone who may write the books may post a manual journal", whatever it had chosen.
ALTER TABLE public.firms DROP COLUMN IF EXISTS manual_journals_need_approval;
