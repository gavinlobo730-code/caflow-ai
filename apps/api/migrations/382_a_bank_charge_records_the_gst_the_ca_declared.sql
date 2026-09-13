-- 382 — A bank line that carries GST records the split that was POSTED.
--
-- WHAT WAS WRONG (BANK-24)
--     A CA marks a bank charge as carrying 18% GST in the posting drawer.
--     bank_posting_service splits the tax-inclusive amount and posts
--     Dr Expense / Dr GST Input / Cr Bank — a real input credit under CGST
--     Act s.16, sitting in the GST Input ledger.
--
--     GSTR-3B is built from DOCUMENTS: gst_return_service.gstr3b_from_books
--     assembles Table 4(A) out of purchase bills, purchase debit notes and
--     purchase credit notes, and Table 3.1(a) out of sales invoices and the
--     s.34 notes. A bank charge is none of those. So the credit the CA
--     explicitly declared never reached the return — and, because
--     _gl_gst_movements DOES read the GST Input account, the same charge
--     turned up on the other side of the books-vs-ledger reconciliation as an
--     unexplained ITC difference, every month, on a return about to be filed.
--
--     The money-IN direction is the same defect and the worse one:
--     charge_gst.build_inclusive_lines(is_credit=True) credits GST Output for
--     an outward supply received straight into the bank, so the liability is
--     on the ledger and the return declares none of it.
--
-- WHY A COLUMN AND NOT THE JOURNAL
--     The reconciliation above is only worth reading while its two sides are
--     derived independently — the same reason Table 4(B) is built from
--     documents and never from the movement on gst_input. Sourcing the bank
--     side out of journal_lines would make that slice compare the ledger with
--     itself and agree by construction. The bank TRANSACTION is the document:
--     it is what the CA acted on, it is what the drawer wrote the rate onto,
--     and it is independent of the journal the posting produced.
--
--     draft_gst_rate_bps (migration 322) cannot serve. It is the machine's
--     PROPOSAL, the caller may override it at the moment of posting
--     (bank_posting_service.post takes gst_rate_bps as an argument), and a
--     line posted with no draft at all carries NULL. What the return needs is
--     what was actually posted.
--
-- NULL MEANS "no GST was declared on this line", which is the state of every
-- row posted before this migration and of every ordinary two-leg post. It is
-- NOT the same as 0: a recorded 0 is the CA saying this charge carries no GST
-- (interest, a government levy), and both post identically, but only the
-- recorded 0 is an answer.
ALTER TABLE public.bank_transactions
  ADD COLUMN IF NOT EXISTS gst_rate_bps      INTEGER,
  ADD COLUMN IF NOT EXISTS gst_is_interstate BOOLEAN NOT NULL DEFAULT false;

-- The same five rates domain/banking/charge_gst.ALLOWED_RATES_BPS accepts, and
-- the same set migration 254 put on bank_matching_rules.suggested_gst_rate_bps.
-- Anything else is a typo, and a typo in a tax head becomes a wrong GSTR-3B.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.bank_transactions'::regclass
      AND conname  = 'bank_transactions_gst_rate_bps_check'
  ) THEN
    ALTER TABLE public.bank_transactions
      ADD CONSTRAINT bank_transactions_gst_rate_bps_check
      CHECK (gst_rate_bps IS NULL
             OR gst_rate_bps IN (0, 500, 1200, 1800, 2800));
  END IF;
END $$;

COMMENT ON COLUMN public.bank_transactions.gst_rate_bps IS
  'The GST rate the CA declared on THIS line, in basis points, as it was '
  'POSTED — not the draft proposal in draft_gst_rate_bps, which the caller '
  'may override. NULL means no GST was declared (every ordinary two-leg '
  'post); 0 means the CA declared that this amount carries none. '
  'gst_return_service reads a non-zero value as a document: money out is an '
  'inward supply and its tax is input credit (CGST Act s.16, GSTR-3B Table '
  '4(A)(5)); money in is an outward supply and its tax is output tax (s.9, '
  'Table 3.1(a)). Cleared when the posting is undone.';

COMMENT ON COLUMN public.bank_transactions.gst_is_interstate IS
  'Which head the declared GST sits in: false is CGST+SGST, true is IGST. '
  'IGST Act s.12(12) puts the place of supply for banking services at the '
  'location of the recipient on the supplier''s records, and an IFSC does not '
  'encode a state — so this is STATED by the CA (or by the matching rule''s '
  'suggested_is_interstate), never inferred. Meaningless where gst_rate_bps '
  'is NULL or 0.';

-- A line only counts as a GST document once it is POSTED, so the return's
-- fetch filters on posted_journal_id and this index carries that shape.
CREATE INDEX IF NOT EXISTS idx_bank_txn_gst_declared
  ON public.bank_transactions (client_id, transaction_date)
  WHERE gst_rate_bps IS NOT NULL AND posted_journal_id IS NOT NULL;
