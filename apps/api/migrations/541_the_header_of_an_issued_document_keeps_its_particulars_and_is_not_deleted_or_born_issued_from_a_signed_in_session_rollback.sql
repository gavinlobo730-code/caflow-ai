-- Rollback of migration 541: drops the six header triggers and the function. THIS RE-OPENS: a member who holds the tier can again change
-- the amounts, tax, party, number and dates of an issued invoice, bill or note, delete one, insert one already issued, soft-delete one and
-- move one back to a draft over PostgREST. The triggers are dropped inside one block, so the table locks are taken in one round trip.
SELECT set_config('lock_timeout', '15s', true);

DO $apply$
DECLARE
  v_try integer := 0;
BEGIN
  -- all six tables at once, without queueing, retried for up to 15 seconds (the same shape as the migration's block)
  LOOP
    BEGIN
      LOCK TABLE public.client_sales_invoices, public.purchase_bills, public.credit_notes, public.debit_notes, public.purchase_credit_notes, public.sales_debit_notes IN ACCESS EXCLUSIVE MODE NOWAIT;
      EXIT;
    EXCEPTION WHEN lock_not_available THEN
      v_try := v_try + 1;
      IF v_try >= 30 THEN
        RAISE EXCEPTION 'rollback of migration 541: could not lock the six document header tables in 15 seconds; run it again';
      END IF;
      PERFORM pg_sleep(0.5);
    END;
  END LOOP;

  DROP TRIGGER IF EXISTS a_document_that_is_not_a_draft_keeps_its_particulars ON public.client_sales_invoices;
  DROP TRIGGER IF EXISTS a_document_that_is_not_a_draft_keeps_its_particulars ON public.purchase_bills;
  DROP TRIGGER IF EXISTS a_document_that_is_not_a_draft_keeps_its_particulars ON public.credit_notes;
  DROP TRIGGER IF EXISTS a_document_that_is_not_a_draft_keeps_its_particulars ON public.debit_notes;
  DROP TRIGGER IF EXISTS a_document_that_is_not_a_draft_keeps_its_particulars ON public.purchase_credit_notes;
  DROP TRIGGER IF EXISTS a_document_that_is_not_a_draft_keeps_its_particulars ON public.sales_debit_notes;
END $apply$;

DROP FUNCTION IF EXISTS public.refuse_a_signed_in_edit_of_a_document_that_is_not_a_draft();
