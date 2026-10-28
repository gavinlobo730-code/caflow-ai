-- Rollback of migration 558: gives `authenticated` back the write verbs production held on the seven tables on 28-10-2026.
-- (TRUNCATE is not given back: a platform default PostgREST does not expose.) The API's privileged writes work either side.
GRANT INSERT, UPDATE, DELETE ON public.receipts, public.receipt_allocations, public.purchase_payments,
    public.purchase_payment_allocations, public.debit_note_allocations, public.sales_debit_note_allocations,
    public.purchase_credit_note_allocations TO authenticated;
