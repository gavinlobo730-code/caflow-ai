-- Migration 172: fix the fee_receipts partial-payment bug -- R3.9b
-- unmediated-write audit.
--
-- apps/web/app/billing/page.tsx's "Record Receipt" flow (linked from
-- AccountingPanel as "Fee Billing") inserted directly into fee_receipts and
-- then unconditionally force-set the paired fee_invoices.status to 'Paid',
-- regardless of the amount entered -- a partial receipt (e.g. Rs 500 against
-- a Rs 50,000 invoice) marked the whole invoice fully paid. fee_invoices had
-- no running total of amount actually received at all, and fee_receipts had
-- zero backend Python reference anywhere, so no reporting surface ever saw
-- the receipt.
--
-- Fix: add paid_paise (mirrors the paid_paise pattern already used on
-- client_sales_invoices), backfill existing 'Paid' invoices on the
-- (reasonable, since nothing tracked partial payment before this migration)
-- assumption that historically 'Paid' meant fully paid, and add an atomic
-- RPC so the receipt insert + invoice update happen in one transaction (same
-- post_journal_atomic/settle_receipt_atomic pattern as migrations 152/160).
-- The accompanying backend change wires this RPC behind a new
-- POST /api/billing/fee-invoices/{id}/receipts endpoint and repoints the
-- frontend at it; this migration then closes the direct-write surface the
-- same way migrations 166/170/171 did.
--
-- Note: fee_invoices/fee_engagements/fee_receipts (this "Fee Billing" system)
-- and billing_schedules/client_sales_invoices (the "internal customer"
-- system behind /practice/billing, /practice/revenue, /practice/ar,
-- /practice/collections) appear to be two independently-built, overlapping
-- systems for the firm's own revenue. Both are live and feed real reporting
-- (fee_invoices -> analytics.py profitability_analytics; the other ->
-- ar_aging/collections_dashboard). Resolving that duplication is a product
-- decision, not attempted here -- this migration only fixes the reported
-- partial-payment bug on the system as it exists today.

ALTER TABLE public.fee_invoices ADD COLUMN IF NOT EXISTS paid_paise BIGINT NOT NULL DEFAULT 0;

UPDATE public.fee_invoices SET paid_paise = total_paise WHERE status = 'Paid' AND paid_paise = 0;

CREATE OR REPLACE FUNCTION public.record_fee_receipt_atomic(
    p_firm_id uuid,
    p_invoice_id uuid,
    p_receipt_date date,
    p_amount_paise bigint,
    p_payment_mode text,
    p_reference_no text,
    p_notes text
) RETURNS uuid
LANGUAGE plpgsql
SET search_path = public, pg_catalog
AS $$
DECLARE
  v_receipt_id uuid;
  v_total      bigint;
  v_paid       bigint;
  v_new_paid   bigint;
  v_status     text;
BEGIN
  IF p_amount_paise <= 0 THEN
    RAISE EXCEPTION 'Receipt amount must be positive.';
  END IF;

  SELECT total_paise, paid_paise, status INTO v_total, v_paid, v_status
    FROM public.fee_invoices
   WHERE id = p_invoice_id AND firm_id = p_firm_id
   FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Invoice % not found for this firm.', p_invoice_id;
  END IF;

  v_new_paid := v_paid + p_amount_paise;

  INSERT INTO public.fee_receipts
    (id, firm_id, invoice_id, receipt_date, amount_paise, payment_mode, reference_no, notes)
  VALUES
    (gen_random_uuid(), p_firm_id, p_invoice_id, p_receipt_date, p_amount_paise, p_payment_mode, p_reference_no, p_notes)
  RETURNING id INTO v_receipt_id;

  UPDATE public.fee_invoices
     SET paid_paise = v_new_paid,
         status = CASE WHEN v_new_paid >= v_total THEN 'Paid' ELSE v_status END,
         updated_at = now()
   WHERE id = p_invoice_id AND firm_id = p_firm_id;

  RETURN v_receipt_id;
END;
$$;

REVOKE INSERT, UPDATE, DELETE ON public.fee_receipts FROM authenticated;
REVOKE UPDATE ON public.fee_invoices FROM authenticated;

DROP POLICY IF EXISTS "fee_receipts_own_firm" ON public.fee_receipts;
CREATE POLICY "fee_receipts_own_firm" ON public.fee_receipts
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id());
