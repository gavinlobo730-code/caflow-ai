-- Rollback of migration 495: drops the three read-tier policies. THIS RE-OPENS THE HOLE — every assigned Manager,
-- Executive and Reviewer can again read the fees of their clients, and every member of the firm can read every fee
-- receipt. Only for a database that must be put back exactly as it was before 495.

DROP POLICY IF EXISTS "fee_engagements_read_tier" ON public.fee_engagements;
DROP POLICY IF EXISTS "fee_invoices_read_tier" ON public.fee_invoices;
DROP POLICY IF EXISTS "fee_receipts_read_tier" ON public.fee_receipts;
