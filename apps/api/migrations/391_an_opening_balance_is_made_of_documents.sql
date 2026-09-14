-- 391 — AN OPENING BALANCE IS MADE OF DOCUMENTS (ACC-14)
--
-- WHAT WAS WRONG
--   `opening_balance_service._plan_opening` computes exactly three targets:
--   aggregate Trade Receivables (Σ customers.opening_balance_paise), aggregate
--   Trade Payables (Σ vendors.opening_balance_paise) and per-bank amounts. So a
--   CA migrating a live client from Tally gets a Trade Receivables TOTAL and no
--   per-party opening ageing at all — and ageing is the point. Every AR/AP
--   ageing screen and the Schedule III ageing note (MCA G.S.R. 207(E) of
--   24-03-2021, which ages from the DUE DATE of payment) read
--   `client_sales_invoices` / `purchase_bills`, so a balance carried as a
--   control-account total is invisible to all of them: on day one the whole
--   opening receivable shows as nil across every bucket.
--
--   Tally takes opening balances bill by bill with dates, which is exactly what
--   makes day-one ageing correct, and Zoho Books' migration wizard takes open
--   invoices and bills individually. This is the missing half.
--
-- WHAT THE FLAG IS, AND WHAT IT IS NOT
--   An opening document is a real row in the ordinary document table: the
--   customer, the OLD system's own document number, its own date and due date,
--   and what is still owed. Everything that already works on a document
--   therefore works on it unchanged — the ageing buckets, a receipt allocating
--   against it (`receipt_allocations` is an FK to this very table), the customer
--   statement, the collections queue, the bank match queue, the portal.
--
--   `is_opening` says ONE thing: the revenue and the tax on this document were
--   recognised and DECLARED IN THE OLD SYSTEM. It is therefore not a supply
--   this client's returns may declare again, not a bill whose credit this
--   client's Table 4(A) may claim again, not a bill whose 180 days Rule 37 may
--   run again, and not a document this product may print a TAX INVOICE for.
--   The readers that feed a statutory return exclude it, and
--   `tests/test_an_opening_balance_is_made_of_documents.py` states that as the
--   rule so a reader added later has to decide rather than inherit.
--
-- IT POSTS NO JOURNAL, AND THAT IS THE DESIGN
--   `customers.opening_balance_paise` and `vendors.opening_balance_paise` stay
--   the SINGLE source of the general ledger's opening AR and AP legs, exactly as
--   they are today — `opening_balance_service` is untouched by this migration.
--   An opening document is the BILL-WISE BREAKUP of that balance, not a second
--   posting of it. Posting one would put the same receivable into the ledger
--   twice, and making the documents the source instead would mean rewriting the
--   delta engine whose own header records the production incident where it
--   reversed ₹40.54 lakh of Trade Payables out of a live client's books.
--
--   The two therefore have to agree, and where they do not the difference is
--   NAMED rather than absorbed: `domain/accounting/opening_documents.reconcile`
--   is the comparison and the Opening Balances screen renders it. Silence there
--   would mean an ageing schedule that does not add up to its own control
--   account, which is worse than either figure alone.

BEGIN;

ALTER TABLE public.client_sales_invoices
  ADD COLUMN IF NOT EXISTS is_opening BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE public.purchase_bills
  ADD COLUMN IF NOT EXISTS is_opening BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN public.client_sales_invoices.is_opening IS
  'This invoice was raised in the system the client is migrating FROM: its '
  'revenue and its GST were recognised and declared there (ACC-14, migration '
  '391). It is carried here as the bill-wise breakup of '
  'customers.opening_balance_paise so day-one AR ageing and the Schedule III '
  'ageing note are right, and it POSTS NO JOURNAL — the aggregate opening leg '
  'already carries the receivable. Every reader that feeds a GST return, and '
  'the tax-invoice PDF, exclude it.';

COMMENT ON COLUMN public.purchase_bills.is_opening IS
  'This bill was received in the system the client is migrating FROM: its '
  'expense, its input tax credit and any TDS on it were dealt with there '
  '(ACC-14, migration 391). Carried here as the bill-wise breakup of '
  'vendors.opening_balance_paise so day-one AP ageing and the Schedule III '
  'payables note are right, and it POSTS NO JOURNAL. Excluded from the return '
  'build, the GSTR-2B reconciliation, the Rule 37 180-day report, the s.43B(h) '
  'computation and the TDS statement — each for its own reason, all of them '
  '"that was already done in the old system".';

-- The ageing reads are `outstanding_paise > 0` per client; the opening rows are
-- a small minority and are read alongside, so no partial index on the flag
-- earns its keep. These two support the OPENING screen's own read, which is
-- "every opening document for this client" and nothing else.
CREATE INDEX IF NOT EXISTS idx_client_sales_invoices_opening
  ON public.client_sales_invoices (client_id)
  WHERE is_opening AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_purchase_bills_opening
  ON public.purchase_bills (client_id)
  WHERE is_opening AND deleted_at IS NULL;

COMMIT;
