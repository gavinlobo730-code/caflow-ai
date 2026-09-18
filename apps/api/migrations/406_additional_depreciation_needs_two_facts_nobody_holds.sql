-- §32(1)(iia) additional depreciation needs TWO facts, and this product held
-- neither (IT-09).
--
-- WHAT WAS WRONG
--
-- `domain/income_tax/section_32.py` has implemented §32(1)(iia) since it was
-- written — 20% of the actual cost of new plant and machinery, halved by the
-- second proviso where the asset was put to use for less than 180 days, with
-- the third proviso's carry-forward named as a gap. `Addition` carries
-- `additional_depreciation_eligible` and the engine branches on it.
--
-- `services/section_32_service.py` passed `False`. Hardcoded, for every
-- addition, for every client. So the §32 screen rendered a headline row
-- labelled "Additional u/s 32(1)(iia)" that was structurally ₹0 — a nil
-- meaning "we cannot see it" presented as a nil meaning "there was none", on
-- a deduction worth a fifth of the cost of every new machine a manufacturer
-- buys.
--
-- TWO FACTS, AND THEY ARE ABOUT DIFFERENT THINGS
--
-- §32(1)(iia) reaches "any new machinery or plant ... acquired and installed
-- after the 31st day of March, 2005, BY AN ASSESSEE ENGAGED IN the business of
-- manufacture or production of any article or thing or in the business of
-- generation, transmission or distribution of power".
--
--   (a) WHO THE ASSESSEE IS. A fact about the client's business, true of every
--       asset they own or of none of them. `clients.section_32_1_iia_business`.
--   (b) WHAT THE ASSET IS. New machinery or plant, and not excluded by the
--       first proviso. A fact about one row.
--       `fixed_assets.additional_depreciation_eligible`.
--
-- One column asserting both would make a CA's tick on a lathe mean something
-- about the whole business, and would give a trading company's new forklift
-- the same answer as a factory's — the section reaches neither the company nor
-- the forklift, for two different reasons that a reader has to be able to tell
-- apart. It is the same split §80DD and §80U take, and the same reason
-- migration 372 kept Rule 43's use on the asset.
--
-- BOTH ARE NULLABLE WITH NO DEFAULT, AND A NULL IS NAMED RATHER THAN ASSUMED
--
-- Guessing is unsafe in both directions and the directions are not symmetric:
--
--   * assuming NOT eligible reproduces exactly the defect this closes — a
--     silent nil on a real deduction, invisible because the row renders ₹0
--     either way;
--   * assuming ELIGIBLE claims 20% of cost the assessee may not be entitled
--     to, which is a disallowance with §270A under-reporting penalty behind
--     it.
--
-- So NULL is reported as a GAP, per client and per asset, and neither is
-- back-filled. Nothing in these books can tell a manufacturer from a trader
-- (`clients.industry` is free text and `business_type` is the legal form), and
-- nothing can tell new plant from second-hand.
--
-- THE FIRST PROVISO'S FOUR EXCLUSIONS ARE NAMED, NOT COLUMNS
--
-- (A) plant used by any other person before its installation — second-hand;
-- (B) plant installed in office premises, residential accommodation or a guest
--     house;
-- (C) office appliances and road transport vehicles;
-- (D) plant whose whole actual cost is allowed as a deduction in one year.
--
-- Each is a fact about the asset, and four more columns would be four more
-- things to fill in for one answer. The asset-level tick asserts all four, and
-- the engine says so on every answer it allows — the Form 10-IA discipline
-- that `domain/income_tax/chapter_vi_a.py` takes with §80DD.

ALTER TABLE public.clients
  ADD COLUMN IF NOT EXISTS section_32_1_iia_business BOOLEAN;

COMMENT ON COLUMN public.clients.section_32_1_iia_business IS
  'IT Act s.32(1)(iia) (IT-09). TRUE where the assessee is engaged in the '
  'business of manufacture or production of any article or thing, or in the '
  'business of generation, transmission or distribution of power — the '
  'section''s own opening words. NULL means NOBODY HAS SAID, which is a third '
  'state and is reported as a gap: it is not FALSE. Never derived from '
  'clients.industry (free text) or business_type (the legal form), neither of '
  'which answers this question.';

ALTER TABLE public.fixed_assets
  ADD COLUMN IF NOT EXISTS additional_depreciation_eligible BOOLEAN;

COMMENT ON COLUMN public.fixed_assets.additional_depreciation_eligible IS
  'IT Act s.32(1)(iia) (IT-09). TRUE where this addition is NEW machinery or '
  'plant and the first proviso does not exclude it: not used by any other '
  'person before installation (A), not installed in office premises, '
  'residential accommodation or a guest house (B), not an office appliance or '
  'road transport vehicle (C), and not plant whose whole actual cost is '
  'allowed as a deduction in one year (D). The tick asserts all four and the '
  'engine says so. NULL means NOBODY HAS SAID and is reported as a gap, not '
  'read as FALSE — the hardcoded FALSE it replaces is the defect IT-09 '
  'records. Needs clients.section_32_1_iia_business as well: the section '
  'reaches an asset only where it also reaches the assessee.';

-- Only the eligible rows are ever scanned for the working, and the register is
-- already scoped by client and year before this is asked.
CREATE INDEX IF NOT EXISTS idx_fixed_assets_additional_depreciation
  ON public.fixed_assets (client_id, put_to_use_date)
  WHERE additional_depreciation_eligible IS TRUE AND deleted_at IS NULL;
