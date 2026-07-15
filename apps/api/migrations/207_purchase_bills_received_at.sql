-- Migration 207 — purchase_bills.received_at / cancelled_at
--
-- routers/purchase_bills.py's receive_purchase_bill() has always written
-- received_at on draft -> received, and the frontend (PurchaseBillViewDrawer.tsx)
-- has always displayed it ("Received at", falling back to "—" when absent) —
-- but the column itself was never created, so every Receive attempt failed
-- with PGRST204 ("Could not find the 'received_at' column of 'purchase_bills'
-- in the schema cache"). cancel_purchase_bill() has the identical gap for
-- cancelled_at (write-only today, no frontend reader yet, but the very next
-- Cancel attempt would hit the same PGRST204). Purely additive; existing
-- rows get NULL.

ALTER TABLE public.purchase_bills
    ADD COLUMN IF NOT EXISTS received_at timestamptz,
    ADD COLUMN IF NOT EXISTS cancelled_at timestamptz;
