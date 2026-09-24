-- SALES-25 (b) — a customer credit limit.
--
-- WHAT WAS MISSING
--     `vendors.credit_limit_paise` has existed since migration 378 and its own
--     column comment says RECORDED, NOT ENFORCED, because nothing reads one.
--     `customers` had no such column at all, so a CA raising the eleventh
--     invoice to a customer who has not paid for the first ten had nothing on
--     screen saying so. Every product in this tier has this; TallyPrime has had
--     it since before GST.
--
-- IT IS NOT STATUTORY AND NOTHING HERE PRETENDS IT IS. A credit limit is a
-- commercial term between the client and their customer. No Act, no rule, no
-- return. It changes no figure: the invoice, its tax and its journal are
-- identical whether the limit is breached or not.
--
-- WARN BY DEFAULT, BLOCK ONLY IF THE FIRM ASKS.
--     `invoice_settings.credit_limit_blocks` is NOT NULL DEFAULT false, so the
--     day this lands nothing refuses anything for anybody. A block stops a CA
--     recording a supply that has already happened — and a supply that cannot
--     be recorded here gets recorded somewhere else, which is worse than an
--     unheeded warning. A firm that wants the harder control opts in, once, on
--     their own settings screen.
--
-- NULLABLE WITH NO DEFAULT, AND NULL IS NOT ZERO.
--     ZERO is a real and useful answer — "this customer is cash only, no credit
--     at all" — so a default of 0 would silently put every existing customer on
--     the strictest possible terms, and an `or 0` in the reader would do the
--     same thing invisibly. NULL means nobody has set one, which is what is
--     true of every customer in the database today. `domain/sales/credit_limit`
--     answers `not_set` for it and offers no opinion.
--
-- NO BACKFILL for the same reason, and none is possible: what a client extends
-- to their own customer is a fact about a conversation no ledger holds.

ALTER TABLE public.customers
  ADD COLUMN IF NOT EXISTS credit_limit_paise BIGINT;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'customers_credit_limit_paise_check') THEN
    ALTER TABLE public.customers
      ADD CONSTRAINT customers_credit_limit_paise_check
      CHECK (credit_limit_paise IS NULL OR credit_limit_paise >= 0);
  END IF;
END $$;

COMMENT ON COLUMN public.customers.credit_limit_paise IS
  'What this client will let this customer owe at once, integer paise. '
  'A commercial term, not a statutory one. NULL means nobody has set a limit '
  'and nothing is assessed; ZERO means no credit at all, which is a real '
  'answer and is why there is no default. Enforced as a WARNING unless the '
  'firm sets invoice_settings.credit_limit_blocks — see '
  'domain/sales/credit_limit.py, which is the one place the comparison lives.';

ALTER TABLE public.invoice_settings
  ADD COLUMN IF NOT EXISTS credit_limit_blocks BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.invoice_settings.credit_limit_blocks IS
  'When true, an invoice that would take a customer past their recorded credit '
  'limit is REFUSED with a 422 rather than warned about. Default false, and '
  'deliberately: a block stops a CA recording a supply that has already '
  'happened, and a supply that cannot be recorded here gets recorded '
  'somewhere else. An OPENING document is never blocked whatever this says '
  '(ACC-14 — refusing one would make a migration impossible).';
