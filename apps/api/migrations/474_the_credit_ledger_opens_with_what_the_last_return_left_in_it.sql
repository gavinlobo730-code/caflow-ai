-- Migration 474 — a GSTR-3B sets off against the credit ledger's OPENING balance,
-- and a return remembers what it left behind (gst-06).
--
-- THE GAP
--   `compute_gstr3b` set off Table 6 against Table 4(C) of THIS return alone.
--   The electronic credit ledger is not that: it is a running balance, so a
--   client whose April closed with Rs 36,54,961.65 of IGST credit unspent
--   opens May holding it, and a month with Rs 1,00,000 of output tax pays that
--   out of the ledger and owes the cash ledger nothing. The return knew none
--   of it. It reported the residue ("carried forward", GST-06's first half)
--   and then never read it back, so May was computed as though April had not
--   happened and a Rs 1,00,000 liability was shown as a Rs 1,00,000 cash
--   payment — to a client holding thirty-six lakh of credit. That is money the
--   client pays out of the bank that the law does not ask of them, and under
--   Rule 88B(1) it is also the base late interest is charged on.
--
-- WHAT THIS ADDS, AND WHY IT IS TWO THINGS
--   1. `gstr3b_returns` records, per head, the credit the ledger OPENED the
--      return with and the credit it was left with, and the date the closing
--      figure is as of. The NEXT return's opening is the previous return's
--      closing, found by `credit_closing_as_of` being the day before the new
--      window starts — never by guessing which period "comes before", which
--      would be wrong across a switch between monthly and quarterly filing.
--   2. `gst_credit_ledger_openings` holds a balance a CA KEYS from the portal,
--      for one return window. It serves two purposes that are one fact: the
--      first period a client has here (no previous return exists) and a
--      correction where the portal's ledger differs from what the chain says
--      (a refund, an ITC-02 transfer, a return filed elsewhere). A recorded
--      figure wins over the chain, and the difference is reported rather than
--      absorbed.
--
-- NULL IS NOT ZERO, in both places. A return saved before this migration
-- carries NULL in every new column, which says "nobody recorded this", and a
-- client with no previous return and nothing keyed has an opening that is
-- NOT KNOWN rather than nil. The engine treats an unknown opening as nil for
-- the arithmetic (the direction that can only over-state cash, never leave a
-- tax unpaid) and SAYS it did.
--
-- ALL-OR-NONE. Four heads and a date that were recorded together are checked
-- as a set, so a row cannot carry an IGST closing and no CGST one and read as
-- complete.
--
-- NO BACKFILL. A return saved earlier did not record its opening or closing and
-- cannot be re-derived honestly: its closing depends on an opening nobody
-- stated. Filling zero in would assert the ledger was empty.
--
-- Additive and idempotent. Reversible:
-- 474_the_credit_ledger_opens_with_what_the_last_return_left_in_it_rollback.sql.

ALTER TABLE public.gstr3b_returns
  ADD COLUMN IF NOT EXISTS credit_opening_igst_paise BIGINT,
  ADD COLUMN IF NOT EXISTS credit_opening_cgst_paise BIGINT,
  ADD COLUMN IF NOT EXISTS credit_opening_sgst_paise BIGINT,
  ADD COLUMN IF NOT EXISTS credit_opening_cess_paise BIGINT,
  ADD COLUMN IF NOT EXISTS credit_closing_igst_paise BIGINT,
  ADD COLUMN IF NOT EXISTS credit_closing_cgst_paise BIGINT,
  ADD COLUMN IF NOT EXISTS credit_closing_sgst_paise BIGINT,
  ADD COLUMN IF NOT EXISTS credit_closing_cess_paise BIGINT,
  ADD COLUMN IF NOT EXISTS credit_closing_as_of DATE,
  ADD COLUMN IF NOT EXISTS credit_opening_source TEXT;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'gstr3b_returns_credit_closing_is_a_set') THEN
    ALTER TABLE public.gstr3b_returns
      ADD CONSTRAINT gstr3b_returns_credit_closing_is_a_set
      CHECK (num_nonnulls(credit_closing_igst_paise, credit_closing_cgst_paise,
                          credit_closing_sgst_paise, credit_closing_cess_paise,
                          credit_closing_as_of) IN (0, 5)) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'gstr3b_returns_credit_opening_is_a_set') THEN
    ALTER TABLE public.gstr3b_returns
      ADD CONSTRAINT gstr3b_returns_credit_opening_is_a_set
      CHECK (num_nonnulls(credit_opening_igst_paise, credit_opening_cgst_paise,
                          credit_opening_sgst_paise, credit_opening_cess_paise) IN (0, 4)) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'gstr3b_returns_credit_is_never_negative') THEN
    ALTER TABLE public.gstr3b_returns
      ADD CONSTRAINT gstr3b_returns_credit_is_never_negative
      CHECK (coalesce(credit_opening_igst_paise, 0) >= 0
         AND coalesce(credit_opening_cgst_paise, 0) >= 0
         AND coalesce(credit_opening_sgst_paise, 0) >= 0
         AND coalesce(credit_opening_cess_paise, 0) >= 0
         AND coalesce(credit_closing_igst_paise, 0) >= 0
         AND coalesce(credit_closing_cgst_paise, 0) >= 0
         AND coalesce(credit_closing_sgst_paise, 0) >= 0
         AND coalesce(credit_closing_cess_paise, 0) >= 0) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'gstr3b_returns_credit_opening_source_check') THEN
    ALTER TABLE public.gstr3b_returns
      ADD CONSTRAINT gstr3b_returns_credit_opening_source_check
      CHECK (credit_opening_source IS NULL
             OR credit_opening_source IN ('recorded', 'previous_return',
                                          'not_recorded', 'unreadable')) NOT VALID;
  END IF;
END $$;

-- Every existing row carries NULL in all ten columns, so each constraint
-- holds and validating them takes only a scan.
ALTER TABLE public.gstr3b_returns VALIDATE CONSTRAINT gstr3b_returns_credit_closing_is_a_set;
ALTER TABLE public.gstr3b_returns VALIDATE CONSTRAINT gstr3b_returns_credit_opening_is_a_set;
ALTER TABLE public.gstr3b_returns VALIDATE CONSTRAINT gstr3b_returns_credit_is_never_negative;
ALTER TABLE public.gstr3b_returns VALIDATE CONSTRAINT gstr3b_returns_credit_opening_source_check;

COMMENT ON COLUMN public.gstr3b_returns.credit_closing_as_of IS
  'gst-06. The last day of the return window the credit_closing_* figures are as '
  'of. The next return''s opening is the closing of the row whose value here is '
  'the day BEFORE the new window starts — an exact lookup, so a switch between '
  'monthly and quarterly filing cannot make the chain skip or repeat a period. '
  'NULL: this return was saved before closing balances were recorded.';
COMMENT ON COLUMN public.gstr3b_returns.credit_opening_source IS
  'gst-06. Where the opening balance the set-off ran against came from: recorded '
  '(a CA keyed the portal''s balance), previous_return (the chain), not_recorded '
  '(nobody has stated one — the set-off assumed the ledger held nothing) or '
  'unreadable (it could not be read at compute time). NULL: saved before this '
  'was recorded.';

-- Chain lookup: one row per (client, registration, window end).
CREATE INDEX IF NOT EXISTS idx_gstr3b_returns_credit_chain
  ON public.gstr3b_returns (client_id, gstin, credit_closing_as_of)
  WHERE credit_closing_as_of IS NOT NULL;

-- ── The balance a CA keys from the portal ──────────────────────────────────

CREATE TABLE IF NOT EXISTS public.gst_credit_ledger_openings (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id       UUID        NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id     UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  -- The registration the portal ledger belongs to: the electronic credit
  -- ledger is PER GSTIN, and a client may hold several (migration 390).
  gstin         TEXT        NOT NULL,
  -- The first day of the return window this is the OPENING balance of. A date
  -- rather than an MMYYYY key because the chain compares dates, and because a
  -- registration that changes frequency keeps the same ledger.
  window_start  DATE        NOT NULL,
  igst_paise    BIGINT      NOT NULL DEFAULT 0,
  cgst_paise    BIGINT      NOT NULL DEFAULT 0,
  sgst_paise    BIGINT      NOT NULL DEFAULT 0,
  cess_paise    BIGINT      NOT NULL DEFAULT 0,
  -- Where the CA read it: the portal's Electronic Credit Ledger on a date. Free
  -- text, optional, and the only provenance a keyed figure has.
  note          TEXT,
  recorded_by   UUID        REFERENCES public.users(id) ON DELETE SET NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT gst_credit_ledger_openings_never_negative
    CHECK (igst_paise >= 0 AND cgst_paise >= 0 AND sgst_paise >= 0 AND cess_paise >= 0),
  CONSTRAINT gst_credit_ledger_openings_one_per_window
    UNIQUE (client_id, gstin, window_start)
);

COMMENT ON TABLE public.gst_credit_ledger_openings IS
  'gst-06. The opening balance of the electronic credit ledger for one return '
  'window, as a CA read it off the portal. Serves the first period a client has '
  'here and any later period where the portal differs from the chain of saved '
  'returns; a recorded figure wins and the difference is reported. Posts nothing '
  'and files nothing — it is an INPUT to the GSTR-3B set-off '
  '(domain/gst/credit_ledger.py), never a ledger entry.';

CREATE INDEX IF NOT EXISTS idx_gst_credit_ledger_openings_client
  ON public.gst_credit_ledger_openings (firm_id, client_id, gstin, window_start);

ALTER TABLE public.gst_credit_ledger_openings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_isolation" ON public.gst_credit_ledger_openings;
CREATE POLICY "firm_isolation" ON public.gst_credit_ledger_openings
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "gst_credit_ledger_openings_assignment_scope" ON public.gst_credit_ledger_openings;
CREATE POLICY "gst_credit_ledger_openings_assignment_scope" ON public.gst_credit_ledger_openings
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT ON public.gst_credit_ledger_openings TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gst_credit_ledger_openings TO service_role;
