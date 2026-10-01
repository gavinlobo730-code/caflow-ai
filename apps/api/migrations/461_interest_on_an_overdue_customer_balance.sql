-- accounting-22 — interest on an overdue customer balance, and a record of what has
-- already been charged.
--
-- WHAT WAS MISSING
--     The product computes STATUTORY interest in many places (TDS s.201(1A), GST
--     s.50, advance tax s.234A-C) and could not compute the COMMERCIAL interest a
--     client charges its own customer on an overdue balance — a TallyPrime
--     feature CAs use for exactly the clients who charge it, and who otherwise
--     work it out in Excel for every overdue customer.
--
-- WHAT THIS ADDS
--     * three columns on `customers` — the TERMS: an annual rate, a grace
--       period, and which date the clock starts from;
--     * `late_interest_charges` — one row per overdue invoice per period that a
--       DRAFT interest invoice has been prepared for.
--
-- THE TERMS ARE NULLABLE AND NULL IS NOT ZERO
--     `late_interest_rate_bps` has no default and no backfill: a client that
--     does not charge interest has not stated a rate, and a stated 0 is a
--     different fact ("interest is waived, by agreement") from "nobody recorded
--     one". A customer with no rate gets NO FIGURE and the preview says so; it is
--     never read as 0% with an `or 0`. The rate is an ANNUAL percentage in basis
--     points (1800 = 18% a year) and is capped at 100%, which no commercial term
--     reaches and a unit slip (typing 18 for 18%, or 1800 for 18) very easily
--     does.
--
-- WHY A SECOND TABLE: INTEREST ACCRUES CONTINUOUSLY AND IS BILLED IN PIECES
--     Without a record, the second month's preview recomputes from the due date
--     and charges the first month AGAIN. `late_interest_charges` holds, per
--     overdue invoice, the period [period_from, period_to] a draft already
--     covers, so the next preview starts where the last one stopped. A charge
--     STANDS only while the draft it produced does (not deleted, not cancelled):
--     that is derived at read time from the invoice's own status rather than
--     stored here, so the PREVIEW offers a deleted or cancelled draft's days
--     again with no write to forget.
--
--     The unique index on (sales_invoice_id, period_to) is the concurrency
--     backstop: two clicks on "Prepare draft" in the same instant cannot both
--     claim the same invoice up to the same date.
--
--     A DEAD CLAIM STILL HOLDS ITS KEY, AND THE INDEX IS DELIBERATELY NOT PARTIAL.
--     The index covers every row, and it cannot read a draft's status (that is
--     on another table), so a cancelled draft's claim — which keeps its pointer
--     — and a hard-deleted draft's claim — whose pointer is nulled and whose
--     row is KEPT — both go on occupying the key. `late_interest_service.
--     prepare_drafts` therefore removes the dead claim that is in the way, by
--     its own id, between making the new draft and recording the new claim. A
--     predicate on the pointer (`WHERE interest_invoice_id IS NOT NULL`) would
--     free the hard-deleted case and not the cancelled one, which is two
--     mechanisms for one rule; one place that knows what "stands" means is the
--     service's `_charge_rows`.
--
-- NOTHING IS POSTED. A charge row is a memorandum of what a DRAFT was prepared
-- for. The draft is an ordinary draft sales invoice created through the sales
-- engine (routers/sales_invoices.create_invoice), which posts no journal until
-- somebody issues it.
--
-- ADDITIVE AND IDEMPOTENT.

ALTER TABLE public.customers
  ADD COLUMN IF NOT EXISTS late_interest_rate_bps   INTEGER,
  ADD COLUMN IF NOT EXISTS late_interest_grace_days INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS late_interest_from       TEXT    NOT NULL DEFAULT 'due_date';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'customers_late_interest_rate_bps_check') THEN
    ALTER TABLE public.customers
      ADD CONSTRAINT customers_late_interest_rate_bps_check
      CHECK (late_interest_rate_bps IS NULL
             OR late_interest_rate_bps BETWEEN 0 AND 10000);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'customers_late_interest_grace_days_check') THEN
    ALTER TABLE public.customers
      ADD CONSTRAINT customers_late_interest_grace_days_check
      CHECK (late_interest_grace_days BETWEEN 0 AND 365);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'customers_late_interest_from_check') THEN
    ALTER TABLE public.customers
      ADD CONSTRAINT customers_late_interest_from_check
      CHECK (late_interest_from IN ('due_date', 'invoice_date'));
  END IF;
END $$;

COMMENT ON COLUMN public.customers.late_interest_rate_bps IS
  'accounting-22. The ANNUAL rate this client charges THIS customer on an overdue '
  'balance, in basis points (1800 = 18% a year), capped at 100%. A COMMERCIAL '
  'term, not a statutory one. NULL means nobody has stated one and no interest '
  'is computed; 0 is a real answer ("waived") and is why there is no default. '
  'See domain/sales/late_interest.py for the day-count convention.';
COMMENT ON COLUMN public.customers.late_interest_grace_days IS
  'Days after the start date before interest begins (0 = none). Only meaningful '
  'when late_interest_rate_bps is set.';
COMMENT ON COLUMN public.customers.late_interest_from IS
  'Which date the interest clock starts from: due_date (the default; falls back '
  'to the invoice date for an invoice with none, and the answer says so) or '
  'invoice_date.';

CREATE TABLE IF NOT EXISTS public.late_interest_charges (
  id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id               UUID        NOT NULL REFERENCES public.firms(id)     ON DELETE CASCADE,
  client_id             UUID        NOT NULL REFERENCES public.clients(id)   ON DELETE CASCADE,
  customer_id           UUID        NOT NULL REFERENCES public.customers(id) ON DELETE CASCADE,
  -- The OVERDUE invoice the interest was computed on.
  sales_invoice_id      UUID        NOT NULL REFERENCES public.client_sales_invoices(id) ON DELETE CASCADE,
  -- The DRAFT invoice the interest was put on. NULL only if that draft was
  -- hard-deleted, which releases the period for the preview; the row is kept
  -- and holds its key until the same period is taken up again (see the header).
  interest_invoice_id   UUID        REFERENCES public.client_sales_invoices(id) ON DELETE SET NULL,
  -- Interest was charged for the days after period_from up to and including
  -- period_to: `days` of them. The next period starts the day after period_to.
  period_from           DATE        NOT NULL,
  period_to             DATE        NOT NULL,
  days                  INTEGER     NOT NULL,
  -- WHAT THE FIGURE WAS COMPUTED FROM, kept so a draft can be explained years
  -- later without re-deriving anything from a balance that has since moved.
  outstanding_paise     BIGINT      NOT NULL,
  rate_bps              INTEGER     NOT NULL,
  grace_days            INTEGER     NOT NULL DEFAULT 0,
  day_count             TEXT        NOT NULL DEFAULT 'actual/365',
  interest_paise        BIGINT      NOT NULL,
  created_by            UUID        REFERENCES public.users(id) ON DELETE SET NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT late_interest_charges_period_ordered CHECK (period_to > period_from),
  CONSTRAINT late_interest_charges_days_positive  CHECK (days > 0),
  CONSTRAINT late_interest_charges_amounts_non_negative
    CHECK (outstanding_paise >= 0 AND interest_paise >= 0),
  CONSTRAINT late_interest_charges_rate_range CHECK (rate_bps BETWEEN 0 AND 10000)
);

COMMENT ON TABLE public.late_interest_charges IS
  'accounting-22. A memorandum of the interest a DRAFT sales invoice was prepared for: '
  'per overdue invoice, the period covered. Posts nothing. A charge stands only '
  'while the draft it produced does — derived at read time from that invoice''s '
  'own status (services/late_interest_service.py), so a deleted or cancelled draft '
  'makes the preview offer its days again. The unique index covers every row, so '
  'the service removes the dead claim in the way when the same period is taken up '
  'again.';

-- One claim per overdue invoice up to a date: the concurrency backstop for two
-- clicks on "Prepare draft" in the same instant.
CREATE UNIQUE INDEX IF NOT EXISTS uq_late_interest_charges_invoice_period_to
  ON public.late_interest_charges (sales_invoice_id, period_to);

CREATE INDEX IF NOT EXISTS idx_late_interest_charges_client_customer
  ON public.late_interest_charges (client_id, customer_id);
CREATE INDEX IF NOT EXISTS idx_late_interest_charges_interest_invoice
  ON public.late_interest_charges (interest_invoice_id);

ALTER TABLE public.late_interest_charges ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_isolation" ON public.late_interest_charges;
CREATE POLICY "firm_isolation" ON public.late_interest_charges
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "late_interest_charges_assignment_scope" ON public.late_interest_charges;
CREATE POLICY "late_interest_charges_assignment_scope" ON public.late_interest_charges
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT ON public.late_interest_charges TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.late_interest_charges TO service_role;
