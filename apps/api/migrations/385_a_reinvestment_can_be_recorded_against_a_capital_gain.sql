-- 385 — where the money went after the sale (IT-19).
--
-- WHAT WAS WRONG
--     `domain/income_tax/capital_gains_engine.py` computes the gain, the
--     holding period and the rate, and stops. Sections 54, 54B, 54EC and 54F
--     exempt that gain — wholly or in part — where the consideration is put
--     back into a new asset, and there was nowhere in this product to record
--     that it had been. A CA computing capital gains here got the tax on a
--     gain the client may not owe tax on at all, which on a house sale is
--     routinely the whole of it.
--
-- TWO THINGS ARE ADDED AND THEY ARE DIFFERENT IN KIND
--
--   1. `capital_gains.transferred_asset_nature` — a fact about the TRANSFER
--      that decides which section can even be reached. The register's
--      `asset_type` vocabulary is equity_shares / mutual_funds / property /
--      bonds / other, and 'property' cannot tell a residential house from a
--      plot: s.54 reaches ONLY a residential house, s.54F only an asset that
--      is NOT one, s.54B only agricultural land and s.54EC (from 01-04-2018)
--      only land or building. So the column is NULLABLE WITH NO DEFAULT and an
--      unrecorded nature is REFUSED AND NAMED rather than guessed — the same
--      shape as `vendors.msme_status` and `fixed_assets.rule_43_use`, and for
--      the same reason: guessing is unsafe in both directions. Guess
--      'residential_house' and s.54 exempts a gain the section does not reach;
--      guess otherwise and the client pays tax on a house sale that was
--      exempt.
--
--   2. `public.capital_gain_reinvestments` — one row per CLAIM, not per
--      transfer. One transfer can carry more than one: s.54EC bonds and a
--      s.54F house are not mutually exclusive on a sale of land, and s.54's
--      own proviso contemplates two houses. Each row records what was bought,
--      when, for how much, what went into the Capital Gains Accounts Scheme,
--      and the two eligibility facts no ledger holds.
--
-- WHY THE ELIGIBILITY FACTS LIVE ON THE ROW
--     `other_residential_houses_owned` is s.54F's own condition — the assessee
--     must not own more than one residential house other than the new one on
--     the date of transfer — and `agricultural_use_two_years` is s.54B's, that
--     the land was used for agricultural purposes in the two years immediately
--     preceding. Neither is derivable from anything this product holds. Both
--     are nullable with no default and both are REFUSED AND NAMED when unset.
--
-- WHAT IS DELIBERATELY NOT HERE
--     No `is_exempt` or `exemption_paise` column. The exemption is a function
--     of the gain, the section, the dates and the caps, all of which move:
--     the Finance Act 2023 capped the s.54 / s.54F cost at Rs 10 crore, and
--     the Finance Act 2018 narrowed s.54EC to land or building. A stored
--     figure would be right on the day it was written and silently wrong
--     afterwards — the same reason migration 278 made `outstanding_paise` a
--     generated column and the same reason `capital_gains.indexed_cost_paise`
--     is left NULL when the index was a fallback (IT-29).
--     `domain/income_tax/reinvestment_exemption.py` derives it on every read.
--
-- NO WRITE GRANT TO `authenticated`, following migration 164 on the parent
-- table: the exemption is computed server-side and the browser has no
-- legitimate write path. SELECT is granted and the row is assignment-scoped,
-- because migration 084's one-shot loop has never run again (see 370).

ALTER TABLE public.capital_gains
  ADD COLUMN IF NOT EXISTS transferred_asset_nature TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.capital_gains'::regclass
       AND conname = 'capital_gains_transferred_asset_nature_check'
  ) THEN
    ALTER TABLE public.capital_gains
      ADD CONSTRAINT capital_gains_transferred_asset_nature_check
      CHECK (transferred_asset_nature IS NULL OR transferred_asset_nature IN (
        'residential_house',   -- s.54 in; s.54F out
        'agricultural_land',   -- s.54B
        'land_or_building',    -- s.54EC from 01-04-2018; also s.54F
        'other'                -- s.54F only
      ));
  END IF;
END $$;

COMMENT ON COLUMN public.capital_gains.transferred_asset_nature IS
  'What was sold, in the vocabulary the s.54 family charges on — a fact the '
  'register''s asset_type cannot carry, since ''property'' covers both a '
  'residential house and a plot of land. NULL means NOT RECORDED and is '
  'refused by domain/income_tax/reinvestment_exemption.py rather than '
  'guessed: guessing wrong exempts a gain the section does not reach, or '
  'taxes a house sale that was exempt.';

CREATE TABLE IF NOT EXISTS public.capital_gain_reinvestments (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id             UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id           UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  capital_gain_id     UUID NOT NULL REFERENCES public.capital_gains(id) ON DELETE CASCADE,

  -- Which section the claim is under. Four values, no default: a claim that
  -- does not say which section it is under is not a claim.
  section             TEXT NOT NULL CHECK (section IN ('54', '54B', '54EC', '54F')),

  new_asset_description TEXT NOT NULL,
  -- s.54 and s.54F give three years to CONSTRUCT and two to PURCHASE, so the
  -- kind decides the deadline. s.54EC is neither — it is a subscription to
  -- bonds within six months.
  acquisition_kind    TEXT CHECK (acquisition_kind IN ('purchase', 'construction', 'bonds')),
  -- NULL while a construction is still running. The engine reports the
  -- deadline rather than refusing, because "not finished yet" is the ordinary
  -- state of a s.54 construction claim in the year of transfer.
  acquisition_date    DATE,
  cost_paise          BIGINT NOT NULL DEFAULT 0 CHECK (cost_paise >= 0),

  -- The Capital Gains Accounts Scheme. An amount deposited before the s.139(1)
  -- due date counts as utilised; s.54EC has no such route, since the section
  -- requires the bonds themselves within six months.
  cgas_deposit_paise  BIGINT NOT NULL DEFAULT 0 CHECK (cgas_deposit_paise >= 0),
  cgas_deposit_date   DATE,

  -- The two facts no ledger holds. NULL = not recorded, and refused.
  other_residential_houses_owned INTEGER CHECK (other_residential_houses_owned IS NULL
                                                OR other_residential_houses_owned >= 0),
  agricultural_use_two_years     BOOLEAN,

  -- Recorded, not enforced: transferring the new asset inside the lock-in
  -- withdraws the exemption in THAT year, which is a later return's problem.
  -- The engine reports it; nothing here recomputes an earlier year.
  new_asset_transferred_on DATE,

  notes               TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by          UUID REFERENCES public.users(id)
);

CREATE INDEX IF NOT EXISTS idx_cg_reinvestments_gain
  ON public.capital_gain_reinvestments (capital_gain_id);
CREATE INDEX IF NOT EXISTS idx_cg_reinvestments_client
  ON public.capital_gain_reinvestments (firm_id, client_id);

COMMENT ON TABLE public.capital_gain_reinvestments IS
  'One row per exemption CLAIM under s.54 / 54B / 54EC / 54F against one '
  'entry in the capital gains register. Several claims may sit against one '
  'transfer — s.54EC bonds and a s.54F house are not mutually exclusive on a '
  'sale of land. No exemption AMOUNT is stored: the caps and the sections '
  'themselves move by Finance Act, so it is derived on every read by '
  'domain/income_tax/reinvestment_exemption.py.';

ALTER TABLE public.capital_gain_reinvestments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_read_capital_gain_reinvestments"
  ON public.capital_gain_reinvestments;
CREATE POLICY "firm_staff_read_capital_gain_reinvestments"
  ON public.capital_gain_reinvestments
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id());

-- Migration 084's loop has never run again (see 370), so a table created now
-- carries only its firm-wide policy unless it says otherwise here.
DROP POLICY IF EXISTS "capital_gain_reinvestments_assignment_scope"
  ON public.capital_gain_reinvestments;
CREATE POLICY "capital_gain_reinvestments_assignment_scope"
  ON public.capital_gain_reinvestments AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

-- Read-only from the browser, exactly as migration 164 left the parent table.
GRANT SELECT ON public.capital_gain_reinvestments TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.capital_gain_reinvestments TO service_role;
