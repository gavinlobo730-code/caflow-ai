-- Rollback of migration 563: gives `authenticated` back the write verbs production held on the twelve document tables on 29-10-2026.
-- (TRUNCATE is not given back: a platform default PostgREST does not expose.) The API's privileged writes work either side.
GRANT INSERT, UPDATE, DELETE ON public.client_sales_invoices, public.client_sales_invoice_lines, public.purchase_bills,
    public.purchase_bill_lines, public.credit_notes, public.credit_note_lines, public.debit_notes, public.debit_note_lines,
    public.purchase_credit_notes, public.purchase_credit_note_lines, public.sales_debit_notes, public.sales_debit_note_lines
    TO authenticated;
