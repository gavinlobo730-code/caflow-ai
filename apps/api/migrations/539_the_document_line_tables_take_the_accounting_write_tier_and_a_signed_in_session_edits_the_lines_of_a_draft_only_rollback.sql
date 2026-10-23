-- Rollback of migration 539: drops the draft-only triggers and the accounting write-tier policies on the eight document line tables.
-- THIS RE-OPENS: a Reviewer, or an Executive the grid has not granted accounting:write, can again write the lines of any document
-- of a client they are assigned to over PostgREST, and a signed-in session can again edit the lines of an issued document.
-- Like the migration, it drops everything inside one block so the table locks (ACCESS EXCLUSIVE, held to commit) are taken in
-- one round trip.
SELECT set_config('lock_timeout', '15s', true);

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['client_sales_invoice_lines', 'purchase_bill_lines', 'credit_note_lines', 'debit_note_lines', 'purchase_credit_note_lines', 'sales_debit_note_lines'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I', 'a_document_that_is_not_a_draft_keeps_its_lines', t);
  END LOOP;
  FOREACH t IN ARRAY ARRAY['client_sales_invoice_lines', 'purchase_bill_lines', 'credit_note_lines', 'debit_note_lines', 'purchase_credit_note_lines', 'sales_debit_note_lines', 'recurring_invoice_template_lines', 'recurring_purchase_bill_template_lines'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_write_tier_insert', t);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_write_tier_update', t);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_write_tier_delete', t);
  END LOOP;
END $$;

DROP FUNCTION IF EXISTS public.refuse_a_signed_in_edit_of_lines_of_a_non_draft_document();
