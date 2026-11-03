-- Migration 578 — the bank queue may propose that a debit is the payment of a recorded TDS challan (POST-A-272).
--
-- WHAT IS WRONG TODAY
--   A recorded TDS challan can be tied to the ledger entry that paid it (migration 568, tied by hand from the Challans tab or the Match
--   dialog), but nothing OFFERS the bank line that paid it. The tax leaves the bank on a statement line, the queue proposes that line
--   from a rule, a document, a transfer or the account's history, and none of them knows a challan: so the line waits for the CA to
--   code it TDS Payable by hand, and the challan waits to be tied to the entry that coding makes.
--
-- WHAT THIS DOES
--   Widens bank_transactions_draft_source_check (migration 322) from ('rule','document','history','transfer') to also admit 'challan':
--   a debit whose amount is the total of exactly one recorded, untied challan paid within a week of the line (domain/banking/entry.py,
--   from_challan). The proposal is always PROPOSED, never READY, so "Pass N ready" never reaches it; passing it posts the line on the
--   ledger the challan's section clears (TDS Payable, or TDS Payable - Salary) through the ordinary bank posting and then ties the
--   challan to the entry through the challan's own door. Nothing is posted from the challan, which would debit the liability twice.
--   The entry-state trigger (migration 322) reads draft_grade and not draft_source, so it needs no change and its Python twin stays as it is.
--
-- WHAT IT DOES NOT DO
--   No column is added, no row is rewritten and no figure moves. Existing drafts keep the source they have. The CHECK is replaced inside
--   this migration's transaction, under a lock timeout, so a busy table makes it fail in words and retry, not wait unseen.
--
-- Reversible: 578_..._rollback.sql clears every draft whose source is 'challan' (a proposal; nothing was posted by it) and restores the
-- four-word check.

SELECT set_config('lock_timeout', '15s', true);

ALTER TABLE public.bank_transactions DROP CONSTRAINT IF EXISTS bank_transactions_draft_source_check;
ALTER TABLE public.bank_transactions ADD CONSTRAINT bank_transactions_draft_source_check
  CHECK (draft_source IS NULL OR draft_source IN ('rule', 'document', 'history', 'transfer', 'challan'));

COMMENT ON COLUMN public.bank_transactions.draft_source IS
  'Where the proposal came from: rule (a human wrote it), document (an open '
  'invoice/bill/receipt/payment with this amount), history (how this payee was '
  'coded before), transfer (the counterpart line on another own account), challan '
  '(a debit equal to the total of exactly one recorded TDS challan not yet tied to the '
  'ledger; always proposed, never ready). NULL = nothing defensible to propose. '
  'Written only by bank_entry_service.redraft.';

DO $$
DECLARE
    v_def text;
BEGIN
    SELECT pg_get_constraintdef(oid) INTO v_def
      FROM pg_constraint
     WHERE conrelid = 'public.bank_transactions'::regclass AND conname = 'bank_transactions_draft_source_check';
    IF v_def IS NULL THEN
        RAISE EXCEPTION 'migration 578: bank_transactions_draft_source_check is missing'; END IF;
    IF position('''challan''' IN v_def) = 0 OR position('''rule''' IN v_def) = 0 OR position('''document''' IN v_def) = 0
       OR position('''history''' IN v_def) = 0 OR position('''transfer''' IN v_def) = 0 THEN
        RAISE EXCEPTION 'migration 578: the draft source check does not admit all five sources: %', v_def; END IF;
END
$$;
