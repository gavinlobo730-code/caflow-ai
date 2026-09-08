-- A receipt and a vendor payment record WHICH account the money moved through.
--
-- WHAT WAS WRONG (ACC-02, ACC-03, SALES-08)
--
-- Every receipt and every vendor payment posted its cash leg to ONE firm-wide
-- ledger, found by `_find_account(db, firm_id, client_id, "%Bank%",
-- system_key="bank")` — a name pattern and a firm-scoped key, with no client
-- filter and no reference to anything the CA chose. Three consequences, and
-- they are separate bugs that happen to share a line:
--
--   * A CASH receipt debited Bank. `payment_mode` has always been captured and
--     stored — the UI offers bank / cash / cheque / upi / neft / rtgs — and it
--     was never once consulted when choosing a GL account. "1001 Cash in Hand"
--     and "1002 Petty Cash" are seeded into every chart of accounts and no
--     automatic flow has ever posted to either. A firm's Cash in Hand balance
--     is zero no matter how much cash the client has taken.
--   * A client with THREE bank accounts had every receipt and payment land in
--     the same ledger, so no individual bank's book balance is right and none
--     of them reconciles. `bank_accounts.coa_account_id` exists and holds the
--     per-bank ledger; `opening_balance_service` already posts each bank's
--     opening balance into it, and `bank_posting_service` already resolves it
--     for statement lines. Only these two paths ignored it.
--   * `ReceiptIn.bank_account_id` was already ACCEPTED BY THE API and then
--     silently dropped — it is absent from the payload dict the service
--     builds, so a caller that supplied it got no error and no effect.
--
-- WHY A COLUMN AND NOT A LOOKUP AT POST TIME
--
-- The account the money moved through is a FACT ABOUT THE TRANSACTION, not a
-- derivable one. `payment_mode = 'cheque'` does not say which bank; a client
-- with two current accounts banks at both. Deriving it later from the client's
-- "main" account would post a plausible number to the wrong sub-ledger, which
-- is the failure this closes rather than one to reintroduce a level down.
--
-- NULLABLE, AND NOTHING IS BACKFILLED. Every existing receipt and payment
-- posted to the generic Bank ledger and its journal says so. Re-pointing the
-- column without moving the posted journal lines would make the document and
-- the ledger disagree — the exact class of defect migration 338 exists to
-- prevent. A NULL here means "recorded before this was captured", the resolver
-- treats it as such, and the CA is shown the list rather than having history
-- rewritten underneath them.

ALTER TABLE public.receipts
  ADD COLUMN IF NOT EXISTS bank_account_id UUID
    REFERENCES public.bank_accounts(id) ON DELETE SET NULL;

ALTER TABLE public.purchase_payments
  ADD COLUMN IF NOT EXISTS bank_account_id UUID
    REFERENCES public.bank_accounts(id) ON DELETE SET NULL;

COMMENT ON COLUMN public.receipts.bank_account_id IS
  'Which bank account the money was received into. NULL means either a cash '
  'receipt (see payment_mode) or a receipt recorded before migration 342 — the '
  'resolver in domain/accounting/payment_account.py tells those apart and says '
  'which ledger it used and why.';
COMMENT ON COLUMN public.purchase_payments.bank_account_id IS
  'Which bank account the money was paid from. NULL as for receipts.';

-- The resolver reads these per document; the register reads them per account.
CREATE INDEX IF NOT EXISTS idx_receipts_bank_account
  ON public.receipts (bank_account_id) WHERE bank_account_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_purchase_payments_bank_account
  ON public.purchase_payments (bank_account_id) WHERE bank_account_id IS NOT NULL;


-- ── BANK-02: an overdraft is not an asset ───────────────────────────────────
--
-- bank_accounts.account_type has allowed 'Current', 'Savings', 'Cash Credit'
-- and 'Overdraft' since migration 054, and the form offers all four. But
-- `_ensure_bank_ledger` hardcoded `account_type = 'Asset', account_subtype =
-- 'Bank'` for the ledger it creates, and the manual picker filtered on
-- `account_type = 'Asset'` — so a Cash Credit or Overdraft account, which is
-- MONEY OWED TO THE BANK, was given an asset ledger and could not be pointed at
-- a liability one either. The bank account's own account_type was read nowhere
-- in the banking backend.
--
-- A drawn overdraft then appears on the balance sheet as a NEGATIVE ASSET
-- instead of a short-term borrowing. Schedule III has no such line: Division I
-- puts "loans repayable on demand from banks" under Current Liabilities →
-- Short-term borrowings, and a negative cash-and-equivalents figure both
-- understates borrowings and misstates liquidity.
--
-- Existing ledgers are RE-CLASSIFIED here rather than left, because unlike the
-- receipts above this is not a fact about a past transaction — it is a standing
-- misclassification of an account, and every balance sheet drawn while it
-- stands is wrong. The journal lines do not move; only the account's type does,
-- which is exactly what a re-classification is.

UPDATE public.chart_of_accounts coa
   SET account_type    = 'Liability',
       account_subtype = 'Bank Overdraft'
  FROM public.bank_accounts ba
 WHERE ba.coa_account_id = coa.id
   AND ba.account_type IN ('Cash Credit', 'Overdraft')
   AND coa.account_type = 'Asset';

-- 'Bank Overdraft' IS THE NAME THAT WORKS, AND IT WAS CHECKED RATHER THAN
-- CHOSEN. domain/reporting/schedule_iii.py's bs_bucket() substring-scans the
-- SUBTYPE, and the vocabulary is enforced nowhere (see the warning at the head
-- of coa_seed_service.STANDARD_COA). Run against it:
--
--     Liability / 'Bank OD'         -> Other Current Liabilities   WRONG
--     Liability / 'Cash Credit'     -> Other Current Liabilities   WRONG
--     Liability / 'Bank Overdraft'  -> Short Term Borrowings       correct
--
-- The branch matches the literal "overdraft", so the obvious abbreviation and
-- the bank account's own type name BOTH miss it and land the balance in a
-- caption Schedule III does not put borrowings in. Both bank types therefore
-- map to the one subtype that hits the branch; a Cash Credit account is a
-- loan repayable on demand exactly as an overdraft is, so one caption is also
-- the right answer rather than a convenience.
--
-- tests/test_an_overdraft_is_not_an_asset.py pins this to bs_bucket, so a later
-- edit to either the name or the branch fails rather than silently re-buckets.
