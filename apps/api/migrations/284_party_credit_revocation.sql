-- PracticeSync — Migration 284: party_credit_ledger gains 'revocation'
--
-- WHY
--   Undoing a posted bank transaction has to put back everything that posting
--   it did. When a bank receipt settled MORE than a document's outstanding,
--   bank_posting_service._settle_doc granted the excess as a party credit
--   (migration 214). Nothing could ever take that credit back, so an Undo
--   would reverse the journal and un-settle the invoice while leaving the
--   customer holding a credit for money the books no longer say they paid.
--
--   The ledger is append-only by design, so a revocation is a NEW row with a
--   negative amount, not a deletion of the grant. That is the same shape the
--   'application' kind already uses (amount_paise is signed: +ve grant, -ve
--   consumption), and it keeps the balance a running sum of the ledger.
--
-- Additive and idempotent. No data changes: no existing row can be a
-- revocation, so widening the CHECK cannot invalidate anything already stored.
-- No financial figures move.

ALTER TABLE public.party_credit_ledger
    DROP CONSTRAINT IF EXISTS party_credit_ledger_kind_check;

ALTER TABLE public.party_credit_ledger
    ADD CONSTRAINT party_credit_ledger_kind_check
    CHECK (kind IN ('grant', 'application', 'revocation'));

COMMENT ON COLUMN public.party_credit_ledger.kind IS
  'grant = credit created (+ve amount_paise); application = credit consumed '
  'against a specific invoice/bill (-ve); revocation = credit withdrawn '
  'because the event that created it was undone (-ve). Balance is the running '
  'sum, so every kind is append-only and nothing is ever deleted.';
