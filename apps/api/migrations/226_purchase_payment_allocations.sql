-- Migration 226: purchase_payment_allocations — AP mirror of receipt_allocations.
--
-- purchase_payments.purchase_bill_id has always been a single nullable FK (one
-- bill per payment, or NULL for an unlinked advance) — there was no way for ONE
-- vendor payment to settle MULTIPLE purchase bills, unlike the AR side which has
-- had a full N:M receipt_allocations bridge since migration 050. This adds that
-- bridge for AP, enabling multi-bill vendor payments (reached today from the
-- Bank Match Queue's multi-invoice bank allocation feature, and reusable by any
-- future multi-bill "Record Payment" UI).
--
-- purchase_payments.purchase_bill_id is left UNCHANGED and untouched by this
-- migration — existing single-bill payments keep using it exclusively. A new
-- multi-bill payment leaves it NULL and records its links here instead, exactly
-- mirroring how receipts.customer_id/receipt_allocations already coexist.
CREATE TABLE IF NOT EXISTS public.purchase_payment_allocations (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  purchase_payment_id   UUID NOT NULL REFERENCES public.purchase_payments(id) ON DELETE CASCADE,
  purchase_bill_id      UUID NOT NULL REFERENCES public.purchase_bills(id) ON DELETE CASCADE,
  allocated_paise       BIGINT NOT NULL DEFAULT 0,
  -- Reversal marker (mirrors receipt_allocations.is_voided, migration 215): a
  -- reversed payment's allocation rows are voided, not deleted, preserving
  -- audit history while excluding them from AP-relief calculations.
  is_voided             BOOLEAN NOT NULL DEFAULT false,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (purchase_payment_id, purchase_bill_id)
);

CREATE INDEX IF NOT EXISTS idx_purchase_payment_allocations_payment
  ON public.purchase_payment_allocations (purchase_payment_id);
CREATE INDEX IF NOT EXISTS idx_purchase_payment_allocations_bill
  ON public.purchase_payment_allocations (purchase_bill_id);

-- unallocated_paise mirrors receipts.unallocated_paise: the portion of a
-- payment not yet applied to any bill (a vendor advance), allocatable later.
ALTER TABLE public.purchase_payments
  ADD COLUMN IF NOT EXISTS unallocated_paise BIGINT NOT NULL DEFAULT 0;

ALTER TABLE public.purchase_payment_allocations ENABLE ROW LEVEL SECURITY;

-- Same firm+client isolation shape as receipt_allocations (migration 053): no
-- firm_id on this table, so the policy joins through the parent payment.
DROP POLICY IF EXISTS "firm_client_isolation" ON public.purchase_payment_allocations;
CREATE POLICY "firm_client_isolation" ON public.purchase_payment_allocations
    FOR ALL TO authenticated
    USING (
        purchase_payment_id IN (
            SELECT p.id FROM public.purchase_payments p
            WHERE p.firm_id = get_my_firm_id()
            AND p.client_id IN (
                SELECT id FROM public.clients WHERE firm_id = get_my_firm_id()
            )
        )
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON public.purchase_payment_allocations TO authenticated, service_role;
