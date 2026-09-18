-- 405 — A NIGHTLY SWEEP THAT EMAILS NOBODY MAY NOT SPEND THE CUSTOMER'S
--       REMINDER NUMBER, AND AN ABSENT SCOPE IS NOT "EVERY CLIENT".
--
-- Migration 077 added client_sales_invoices.last_reminded_at and
-- reminder_count with NO column comment, and nothing said what they counted.
-- Migration 106 then built the CUSTOMER-FACING reminder on top of them:
-- collections_service._dispatch_invoice_reminder writes both AFTER a send, and
-- email_service.send_payment_reminder_to_customer ESCALATES ITS TONE on the
-- number -- 1 is "friendly reminder", 2 is "Second reminder", and 3 or more is
--
--     "Final reminder: Invoice X overdue ... This is a final reminder that
--      Invoice X is significantly overdue."
--
-- The nightly sweep, services/collections_service.send_overdue_reminders,
-- writes the SAME two columns and sends nothing. jobs/scheduler.py's own header
-- calls it "internal reminder logging (no email)", so the intent was a log --
-- but the log consumed the number a real email would have used, and its
-- timeline entry is headed "Payment Reminder Sent", which is false.
--
-- MEASURED ON PRODUCTION, 18-09-2026, BEFORE WRITING THIS:
--     firms                                        2
--     firms with internal_client_id IS NULL        1
--     client_sales_invoices                    5,662
--     rows with reminder_count > 0                 2   (both reminder_count = 5)
--     invoice_deliveries WHERE kind = 'reminder'   0
--
-- Both flagged rows sit on the UNPROVISIONED firm and NEITHER is the practice's
-- own fee invoice -- they are a real client's customer invoices. So the next
-- genuine reminder on either would have opened as a FINAL DEMAND to a customer
-- who had never been contacted once.
--
-- WHY THEY WERE REACHED AT ALL. collections_service._open_invoices takes the
-- internal client id and applies it as `if internal_id:` -- so a firm whose
-- firms.internal_client_id is NULL (migration 074's own comment calls that an
-- "unprovisioned firm", a contemplated state) loses the client filter entirely
-- and the sweep runs over EVERY client's invoices. An absent scope read as no
-- scope, which is the shape domain/accounting/opening_documents records for
-- is_opening and domain/firm/identity records for a narrow select(): the
-- failure is silent and the wrong direction is the permissive one.
--
-- WHAT THIS MIGRATION DOES. It gives the sweep its OWN memory, so the two
-- meanings stop sharing one pair of columns. The Python half -- scoping the
-- sweep, renaming the timeline entry -- rides with it.

-- ---------------------------------------------------------------------------
-- 1. The sweep's own cadence memory.
-- ---------------------------------------------------------------------------
-- Nullable with no default, and a count defaulting to 0, matching the pair they
-- stand beside. A separate column rather than a flag on the existing pair: the
-- question "how many times did we EMAIL this customer" and the question "how
-- many times has the sweep flagged it internally" have different answers, and
-- one column cannot hold two. That is migration 278's reasoning applied to a
-- counter -- and the reason there is deliberately no "reminder_kind" column.
ALTER TABLE public.client_sales_invoices
    ADD COLUMN IF NOT EXISTS last_internal_followup_at timestamptz;
ALTER TABLE public.client_sales_invoices
    ADD COLUMN IF NOT EXISTS internal_followup_count   integer NOT NULL DEFAULT 0;

-- ---------------------------------------------------------------------------
-- 2. Say what all four columns mean, which 077 never did.
-- ---------------------------------------------------------------------------
COMMENT ON COLUMN public.client_sales_invoices.reminder_count IS
  'How many overdue-payment reminders were EMAILED to the customer. Written ONLY by '
  'collections_service._dispatch_invoice_reminder, after a successful send. '
  'email_service.send_payment_reminder_to_customer escalates its tone on this number '
  '(3+ reads as a final demand), so a path that sends nothing must never advance it. '
  'invoice_deliveries WHERE kind = ''reminder'' is the underlying evidence.';
COMMENT ON COLUMN public.client_sales_invoices.last_reminded_at IS
  'When the last reminder was EMAILED to the customer. Same single writer as reminder_count.';
COMMENT ON COLUMN public.client_sales_invoices.internal_followup_count IS
  'How many times the nightly collections sweep has flagged this invoice internally. '
  'Nothing was sent to anybody. Written only by collections_service.send_overdue_reminders, '
  'which is scoped to the firm''s OWN fee ledger (firms.internal_client_id).';
COMMENT ON COLUMN public.client_sales_invoices.last_internal_followup_at IS
  'When the nightly sweep last flagged this invoice. The sweep''s anti-spam gate reads '
  'this, NOT last_reminded_at -- reading the emailed column let a real send suppress an '
  'internal note and an internal note suppress a real send.';

-- ---------------------------------------------------------------------------
-- 3. Repair the rows the sweep mislabelled.
-- ---------------------------------------------------------------------------
-- DERIVED, NOT GUESSED. invoice_deliveries is the record of every send attempt
-- and migration 097 makes it immutable ("no DELETE ... immutable evidence of
-- every send attempt, whether successful or not"), so the number of reminders a
-- customer actually received is a COUNT over it, not an opinion. Everything
-- above that count was the sweep's, and moves.
--
-- Rows with no reminder delivery at all -- which today is every row in this
-- database -- therefore have an emailed count of exactly zero.
WITH emailed AS (
    SELECT i.id,
           count(d.id)      AS sends,
           max(d.sent_at)   AS last_send
      FROM public.client_sales_invoices i
      LEFT JOIN public.invoice_deliveries d
             ON d.invoice_id = i.id
            AND d.kind   = 'reminder'
            AND d.status = 'sent'
     WHERE coalesce(i.reminder_count, 0) > 0
        OR i.last_reminded_at IS NOT NULL
     GROUP BY i.id
)
UPDATE public.client_sales_invoices i
   SET reminder_count            = e.sends,
       last_reminded_at          = e.last_send,
       internal_followup_count   = greatest(coalesce(i.reminder_count, 0) - e.sends, 0),
       -- Only where NOTHING was emailed is the old timestamp unambiguously the
       -- sweep's. Where both happened, last_reminded_at is simply whichever
       -- wrote most recently and there is no way to tell them apart, so this is
       -- left NULL for the next sweep to set rather than guessed. The COUNT
       -- above is exact either way, which is the figure the tone reads.
       last_internal_followup_at = CASE WHEN e.sends = 0 THEN i.last_reminded_at END
  FROM emailed e
 WHERE e.id = i.id
   AND (i.reminder_count IS DISTINCT FROM e.sends
        OR i.last_reminded_at IS DISTINCT FROM e.last_send);

-- ---------------------------------------------------------------------------
-- 4. The sweep's own gate wants its own index.
-- ---------------------------------------------------------------------------
-- Mirrors 077's idx_client_sales_invoices_open, on the column the cadence gate
-- now actually reads.
CREATE INDEX IF NOT EXISTS idx_client_sales_invoices_internal_followup
  ON public.client_sales_invoices (firm_id, last_internal_followup_at)
  WHERE status IN ('issued', 'partially_paid');
