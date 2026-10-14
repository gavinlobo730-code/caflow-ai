-- Migration 487 — a Reviewer can no longer write the accounting documents or the bank tables
-- (security_privacy-34, found by the role-by-table access matrix; ledger POST-B-005, first slice of three).
--
-- THE HOLE
--   Thirteen tables carry a firm policy and an assignment scope and NO write-tier policy, so a Reviewer assigned to
--   a client inserted, updated and deleted that client's invoices, bills, receipts, payments, credit and debit notes,
--   service-catalogue items, bank accounts and bank transactions straight over PostgREST with their own sign-in. The
--   API never lets a Reviewer near them: every route that writes these tables asks `accounting:write` (Manager and
--   above) or `banking:write` (Executive and above), and `invoice:write` (Executive) for the one reminder counter.
--   A read-only audit of every writer of the thirteen tables (routers, services, domain, jobs, the browser and the
--   database's own functions) found NO code path that writes any of them legitimately as a Reviewer, and no read
--   that writes (a page load, a report, a preview) under the caller's sign-in.
--
-- WHAT THIS DOES
--   RESTRICTIVE per-command policies (so they AND with the firm and assignment rules and can only narrow), each
--   asking `my_permission(resource, action, floor)`, the function the route's own `rbac()` resolves through, so a
--   per-person grant or denial in the access grid counts here too. A command passes if ANY of its pairs does, and the
--   pairs are exactly the ones the table's writing routes ask, because a refused UPDATE or DELETE affects zero rows
--   with no error and several handlers then index the empty result and answer 500:
--
--     client_sales_invoices   INSERT, DELETE  accounting:write (Manager)
--                             UPDATE          accounting:write (Manager) OR banking:write (Executive: a bank post settles
--                                             an invoice) OR invoice:write (Executive: the reminder counter)
--     purchase_bills          INSERT, DELETE  accounting:write;  UPDATE  accounting:write OR banking:write
--     receipts, receipt_allocations, purchase_payments, purchase_payment_allocations
--                             INSERT, DELETE  accounting:write OR banking:write (a bank match-multi inserts
--                                             foreign-currency receipts and payments directly and compensates on failure)
--                             UPDATE          accounting:write (a reversal is Partner, which the Manager floor covers)
--     credit_notes, debit_notes, purchase_credit_notes, sales_debit_notes, service_catalogue
--                             INSERT, UPDATE, DELETE  accounting:write (Manager)
--     bank_accounts, bank_transactions
--                             INSERT, UPDATE, DELETE  banking:write (Executive)
--
-- WHAT CHANGES FOR AN EXECUTIVE, AND WHY THAT IS SAFE
--   Before this, an Executive could write the Manager-only tables (the five note and catalogue tables, and the
--   inserts and deletes of invoices, bills, receipts and payments) straight over PostgREST although the API refuses
--   them. Those cells close with the Reviewer's, and the reviewed access expectation is updated for them in the same
--   commit. Nothing the application does is affected: the audit found no writer that runs as an Executive on these
--   tables outside `banking:write` and `invoice:write`, which are in the pairs above, and the browser has no direct
--   write to any of the thirteen.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * The database functions that write these tables as their owner (settle_receipt_atomic, numbered_document_atomic)
--     bypass these policies by design; migration 486 makes them ask who is calling.
--   * SELECT is untouched. The other 26 tables of the same class (tax returns and filings, year end, company filings,
--     health, onboarding and the rest) are the next two slices.
--   * No function, grant, table or row changes. No backfill.
--
-- Idempotent: DROP POLICY IF EXISTS before each CREATE, and the closing check fails the migration (and so the deploy)
-- if any policy is missing. Reversible: 487_..._rollback.sql drops them again, which RE-OPENS the hole.

-- ── client_sales_invoices ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "client_sales_invoices_write_tier_insert" ON public.client_sales_invoices;
CREATE POLICY "client_sales_invoices_write_tier_insert" ON public.client_sales_invoices
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "client_sales_invoices_write_tier_update" ON public.client_sales_invoices;
CREATE POLICY "client_sales_invoices_write_tier_update" ON public.client_sales_invoices
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING ((public.my_permission('accounting', 'write', 'Manager')
          OR public.my_permission('banking', 'write', 'Executive')
          OR public.my_permission('invoice', 'write', 'Executive')))
  WITH CHECK ((public.my_permission('accounting', 'write', 'Manager')
          OR public.my_permission('banking', 'write', 'Executive')
          OR public.my_permission('invoice', 'write', 'Executive')));

DROP POLICY IF EXISTS "client_sales_invoices_write_tier_delete" ON public.client_sales_invoices;
CREATE POLICY "client_sales_invoices_write_tier_delete" ON public.client_sales_invoices
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'));

-- ── purchase_bills ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "purchase_bills_write_tier_insert" ON public.purchase_bills;
CREATE POLICY "purchase_bills_write_tier_insert" ON public.purchase_bills
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "purchase_bills_write_tier_update" ON public.purchase_bills;
CREATE POLICY "purchase_bills_write_tier_update" ON public.purchase_bills
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING ((public.my_permission('accounting', 'write', 'Manager')
          OR public.my_permission('banking', 'write', 'Executive')))
  WITH CHECK ((public.my_permission('accounting', 'write', 'Manager')
          OR public.my_permission('banking', 'write', 'Executive')));

DROP POLICY IF EXISTS "purchase_bills_write_tier_delete" ON public.purchase_bills;
CREATE POLICY "purchase_bills_write_tier_delete" ON public.purchase_bills
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'));

-- ── receipts ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "receipts_write_tier_insert" ON public.receipts;
CREATE POLICY "receipts_write_tier_insert" ON public.receipts
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK ((public.my_permission('accounting', 'write', 'Manager')
          OR public.my_permission('banking', 'write', 'Executive')));

DROP POLICY IF EXISTS "receipts_write_tier_update" ON public.receipts;
CREATE POLICY "receipts_write_tier_update" ON public.receipts
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'))
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "receipts_write_tier_delete" ON public.receipts;
CREATE POLICY "receipts_write_tier_delete" ON public.receipts
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING ((public.my_permission('accounting', 'write', 'Manager')
          OR public.my_permission('banking', 'write', 'Executive')));

-- ── receipt_allocations ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "receipt_allocations_write_tier_insert" ON public.receipt_allocations;
CREATE POLICY "receipt_allocations_write_tier_insert" ON public.receipt_allocations
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK ((public.my_permission('accounting', 'write', 'Manager')
          OR public.my_permission('banking', 'write', 'Executive')));

DROP POLICY IF EXISTS "receipt_allocations_write_tier_update" ON public.receipt_allocations;
CREATE POLICY "receipt_allocations_write_tier_update" ON public.receipt_allocations
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'))
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "receipt_allocations_write_tier_delete" ON public.receipt_allocations;
CREATE POLICY "receipt_allocations_write_tier_delete" ON public.receipt_allocations
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING ((public.my_permission('accounting', 'write', 'Manager')
          OR public.my_permission('banking', 'write', 'Executive')));

-- ── purchase_payments ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "purchase_payments_write_tier_insert" ON public.purchase_payments;
CREATE POLICY "purchase_payments_write_tier_insert" ON public.purchase_payments
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK ((public.my_permission('accounting', 'write', 'Manager')
          OR public.my_permission('banking', 'write', 'Executive')));

DROP POLICY IF EXISTS "purchase_payments_write_tier_update" ON public.purchase_payments;
CREATE POLICY "purchase_payments_write_tier_update" ON public.purchase_payments
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'))
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "purchase_payments_write_tier_delete" ON public.purchase_payments;
CREATE POLICY "purchase_payments_write_tier_delete" ON public.purchase_payments
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING ((public.my_permission('accounting', 'write', 'Manager')
          OR public.my_permission('banking', 'write', 'Executive')));

-- ── purchase_payment_allocations ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "purchase_payment_allocations_write_tier_insert" ON public.purchase_payment_allocations;
CREATE POLICY "purchase_payment_allocations_write_tier_insert" ON public.purchase_payment_allocations
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK ((public.my_permission('accounting', 'write', 'Manager')
          OR public.my_permission('banking', 'write', 'Executive')));

DROP POLICY IF EXISTS "purchase_payment_allocations_write_tier_update" ON public.purchase_payment_allocations;
CREATE POLICY "purchase_payment_allocations_write_tier_update" ON public.purchase_payment_allocations
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'))
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "purchase_payment_allocations_write_tier_delete" ON public.purchase_payment_allocations;
CREATE POLICY "purchase_payment_allocations_write_tier_delete" ON public.purchase_payment_allocations
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING ((public.my_permission('accounting', 'write', 'Manager')
          OR public.my_permission('banking', 'write', 'Executive')));

-- ── credit_notes ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "credit_notes_write_tier_insert" ON public.credit_notes;
CREATE POLICY "credit_notes_write_tier_insert" ON public.credit_notes
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "credit_notes_write_tier_update" ON public.credit_notes;
CREATE POLICY "credit_notes_write_tier_update" ON public.credit_notes
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'))
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "credit_notes_write_tier_delete" ON public.credit_notes;
CREATE POLICY "credit_notes_write_tier_delete" ON public.credit_notes
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'));

-- ── debit_notes ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "debit_notes_write_tier_insert" ON public.debit_notes;
CREATE POLICY "debit_notes_write_tier_insert" ON public.debit_notes
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "debit_notes_write_tier_update" ON public.debit_notes;
CREATE POLICY "debit_notes_write_tier_update" ON public.debit_notes
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'))
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "debit_notes_write_tier_delete" ON public.debit_notes;
CREATE POLICY "debit_notes_write_tier_delete" ON public.debit_notes
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'));

-- ── purchase_credit_notes ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "purchase_credit_notes_write_tier_insert" ON public.purchase_credit_notes;
CREATE POLICY "purchase_credit_notes_write_tier_insert" ON public.purchase_credit_notes
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "purchase_credit_notes_write_tier_update" ON public.purchase_credit_notes;
CREATE POLICY "purchase_credit_notes_write_tier_update" ON public.purchase_credit_notes
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'))
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "purchase_credit_notes_write_tier_delete" ON public.purchase_credit_notes;
CREATE POLICY "purchase_credit_notes_write_tier_delete" ON public.purchase_credit_notes
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'));

-- ── sales_debit_notes ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "sales_debit_notes_write_tier_insert" ON public.sales_debit_notes;
CREATE POLICY "sales_debit_notes_write_tier_insert" ON public.sales_debit_notes
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "sales_debit_notes_write_tier_update" ON public.sales_debit_notes;
CREATE POLICY "sales_debit_notes_write_tier_update" ON public.sales_debit_notes
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'))
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "sales_debit_notes_write_tier_delete" ON public.sales_debit_notes;
CREATE POLICY "sales_debit_notes_write_tier_delete" ON public.sales_debit_notes
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'));

-- ── service_catalogue ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "service_catalogue_write_tier_insert" ON public.service_catalogue;
CREATE POLICY "service_catalogue_write_tier_insert" ON public.service_catalogue
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "service_catalogue_write_tier_update" ON public.service_catalogue;
CREATE POLICY "service_catalogue_write_tier_update" ON public.service_catalogue
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'))
  WITH CHECK (public.my_permission('accounting', 'write', 'Manager'));

DROP POLICY IF EXISTS "service_catalogue_write_tier_delete" ON public.service_catalogue;
CREATE POLICY "service_catalogue_write_tier_delete" ON public.service_catalogue
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('accounting', 'write', 'Manager'));

-- ── bank_accounts ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "bank_accounts_write_tier_insert" ON public.bank_accounts;
CREATE POLICY "bank_accounts_write_tier_insert" ON public.bank_accounts
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('banking', 'write', 'Executive'));

DROP POLICY IF EXISTS "bank_accounts_write_tier_update" ON public.bank_accounts;
CREATE POLICY "bank_accounts_write_tier_update" ON public.bank_accounts
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('banking', 'write', 'Executive'))
  WITH CHECK (public.my_permission('banking', 'write', 'Executive'));

DROP POLICY IF EXISTS "bank_accounts_write_tier_delete" ON public.bank_accounts;
CREATE POLICY "bank_accounts_write_tier_delete" ON public.bank_accounts
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('banking', 'write', 'Executive'));

-- ── bank_transactions ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "bank_transactions_write_tier_insert" ON public.bank_transactions;
CREATE POLICY "bank_transactions_write_tier_insert" ON public.bank_transactions
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('banking', 'write', 'Executive'));

DROP POLICY IF EXISTS "bank_transactions_write_tier_update" ON public.bank_transactions;
CREATE POLICY "bank_transactions_write_tier_update" ON public.bank_transactions
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('banking', 'write', 'Executive'))
  WITH CHECK (public.my_permission('banking', 'write', 'Executive'));

DROP POLICY IF EXISTS "bank_transactions_write_tier_delete" ON public.bank_transactions;
CREATE POLICY "bank_transactions_write_tier_delete" ON public.bank_transactions
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('banking', 'write', 'Executive'));

-- ── the closing check: all 39 policies exist and every one is RESTRICTIVE ───────────────────────
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n
    FROM pg_policies
   WHERE schemaname = 'public'
     AND permissive = 'RESTRICTIVE'
     AND policyname IN (
       'client_sales_invoices_write_tier_insert',
       'client_sales_invoices_write_tier_update',
       'client_sales_invoices_write_tier_delete',
       'purchase_bills_write_tier_insert',
       'purchase_bills_write_tier_update',
       'purchase_bills_write_tier_delete',
       'receipts_write_tier_insert',
       'receipts_write_tier_update',
       'receipts_write_tier_delete',
       'receipt_allocations_write_tier_insert',
       'receipt_allocations_write_tier_update',
       'receipt_allocations_write_tier_delete',
       'purchase_payments_write_tier_insert',
       'purchase_payments_write_tier_update',
       'purchase_payments_write_tier_delete',
       'purchase_payment_allocations_write_tier_insert',
       'purchase_payment_allocations_write_tier_update',
       'purchase_payment_allocations_write_tier_delete',
       'credit_notes_write_tier_insert',
       'credit_notes_write_tier_update',
       'credit_notes_write_tier_delete',
       'debit_notes_write_tier_insert',
       'debit_notes_write_tier_update',
       'debit_notes_write_tier_delete',
       'purchase_credit_notes_write_tier_insert',
       'purchase_credit_notes_write_tier_update',
       'purchase_credit_notes_write_tier_delete',
       'sales_debit_notes_write_tier_insert',
       'sales_debit_notes_write_tier_update',
       'sales_debit_notes_write_tier_delete',
       'service_catalogue_write_tier_insert',
       'service_catalogue_write_tier_update',
       'service_catalogue_write_tier_delete',
       'bank_accounts_write_tier_insert',
       'bank_accounts_write_tier_update',
       'bank_accounts_write_tier_delete',
       'bank_transactions_write_tier_insert',
       'bank_transactions_write_tier_update',
       'bank_transactions_write_tier_delete');
  IF n <> 39 THEN
    RAISE EXCEPTION 'migration 487: expected 39 restrictive policies, found %', n;
  END IF;
END $$;
