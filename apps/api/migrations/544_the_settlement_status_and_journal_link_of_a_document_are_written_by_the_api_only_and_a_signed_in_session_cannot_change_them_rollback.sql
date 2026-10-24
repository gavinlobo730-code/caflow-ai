-- Rollback of migration 544: drops the six settlement triggers and the function. THIS RE-OPENS: a member who holds the tier can again
-- change the settlement, status and journal link of an invoice, bill or note over PostgREST (mark an invoice paid, set its paid
-- amount, cancel it, issue a draft, point it at another journal entry). The triggers are dropped inside one block, so the table locks
-- are taken in one round trip.
-- THE QUICK STOP. DROP TRIGGER needs ACCESS EXCLUSIVE, which any in-flight SELECT on one of the six tables makes this file retry (thirty
-- attempts over fifteen seconds, then it fails and can be run again). If the trigger itself is what has to go in an incident,
-- `ALTER TABLE public.<table> DISABLE TRIGGER a_documents_settlement_is_written_by_the_api_only` takes only SHARE ROW EXCLUSIVE (readers
-- keep reading) and stops it at once; this file is the permanent undo.
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
        RAISE EXCEPTION 'rollback of migration 544: could not lock the six document header tables in 15 seconds; run it again';
      END IF;
      PERFORM pg_sleep(0.5);
    END;
  END LOOP;

  DROP TRIGGER IF EXISTS a_documents_settlement_is_written_by_the_api_only ON public.client_sales_invoices;
  DROP TRIGGER IF EXISTS a_documents_settlement_is_written_by_the_api_only ON public.purchase_bills;
  DROP TRIGGER IF EXISTS a_documents_settlement_is_written_by_the_api_only ON public.credit_notes;
  DROP TRIGGER IF EXISTS a_documents_settlement_is_written_by_the_api_only ON public.debit_notes;
  DROP TRIGGER IF EXISTS a_documents_settlement_is_written_by_the_api_only ON public.purchase_credit_notes;
  DROP TRIGGER IF EXISTS a_documents_settlement_is_written_by_the_api_only ON public.sales_debit_notes;
END $apply$;

DROP FUNCTION IF EXISTS public.refuse_a_signed_in_change_of_a_documents_settlement();
