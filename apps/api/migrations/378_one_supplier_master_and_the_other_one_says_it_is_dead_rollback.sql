-- Rollback for 378.
--
-- Dropping the column loses every credit limit recorded against a vendor since
-- 378 ran. Nothing computes from it — no bill is blocked or flagged by it — so
-- the loss is of a recorded fact rather than of a control, but it is a fact a
-- CA typed and cannot be rebuilt from the ledger. Export
-- vendors(id, credit_limit_paise) WHERE credit_limit_paise IS NOT NULL first.
--
-- The comments go back to nothing rather than to their previous text: neither
-- table carried one before 378. Removing the suppliers comment removes the
-- warning, not the retirement — the screen still reads vendors, so a reader
-- who then writes to public.suppliers writes to a table nothing reads, which
-- is the state PUR-16 was about.

ALTER TABLE public.vendors
  DROP CONSTRAINT IF EXISTS vendors_credit_limit_paise_check;

ALTER TABLE public.vendors
  DROP COLUMN IF EXISTS credit_limit_paise;

COMMENT ON TABLE public.suppliers IS NULL;
