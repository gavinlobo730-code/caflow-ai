-- 420 — A CLIENT'S OWN (PRIMARY) REGISTRATION CAN BE COMPOSITION TOO (GST-25)
--
-- WHAT WAS WRONG
--   Migration 390 (GST-20) gave an ADDITIONAL registration a `registration_type`
--   — composition, ISD, TDS deductor and so on — but the PRIMARY registration,
--   the one `clients.gstin` names, has none: `domain/gst/registrations.
--   primary_of()` hardcodes it to `'regular'`. There was never a column to read
--   anything else from. That is backwards for the common case: a composition
--   dealer is typically a SMALL business with exactly one GST registration,
--   which is its primary, so the client the whole GST-25 build exists for could
--   never actually be marked one.
--
-- WHY IT IS A SEPARATE COLUMN, NOT A REPURPOSED ONE
--   `gst_filing_frequency` already exists on `clients` (migration 001) for
--   exactly the same shape of reason — the primary needs its own copy of a fact
--   `client_gst_registrations` also carries for the additional ones — and this
--   follows it rather than inventing a second pattern.
--
-- WHY `gst_registration_type` DEFAULTS TO 'regular' AND `composition_category`
-- DOES NOT DEFAULT AT ALL
--   Every client recorded before this migration was, by construction, already
--   being treated as an ordinary GSTR-1/GSTR-3B filer — that is what
--   `primary_of()` assumed unconditionally — so `DEFAULT 'regular'` states a
--   fact already true of every row rather than guessing one. WHICH of the three
--   s.10 rates a composition dealer pays is a different kind of fact: it
--   depends on the nature of the dealer's own business (manufacturer/trader,
--   restaurant, or another service provider), which no existing column records
--   and which this migration must not guess at either extreme — defaulting to
--   the lowest rate under-charges, defaulting to the highest over-charges. NULL
--   is a named gap (`domain/gst/composition.py`), the same discipline
--   `vendors.msme_status` and `fixed_assets.rule_43_use` already follow.
--
-- WHY BOTH TABLES GET IT
--   `client_gst_registrations` already has `registration_type` but never had a
--   composition CATEGORY either — an additional registration can be a
--   composition dealer too (a depot registered separately that elected s.10 in
--   its own state), and the category is a fact about THAT registration's
--   business, not the client's as a whole.

BEGIN;

ALTER TABLE public.clients
  ADD COLUMN IF NOT EXISTS gst_registration_type TEXT NOT NULL DEFAULT 'regular'
    CHECK (gst_registration_type IN (
      'regular', 'composition', 'casual_taxable_person',
      'input_service_distributor', 'sez_unit', 'sez_developer',
      'tds_deductor', 'tcs_collector', 'non_resident_taxable_person'));

ALTER TABLE public.clients
  ADD COLUMN IF NOT EXISTS composition_category TEXT
    CHECK (composition_category IS NULL OR composition_category IN (
      'manufacturer_trader', 'restaurant', 'other_services'));

ALTER TABLE public.client_gst_registrations
  ADD COLUMN IF NOT EXISTS composition_category TEXT
    CHECK (composition_category IS NULL OR composition_category IN (
      'manufacturer_trader', 'restaurant', 'other_services'));

COMMENT ON COLUMN public.clients.gst_registration_type IS
  'What the PRIMARY registration (clients.gstin) is under CGST Act s.25 — the '
  'mirror of client_gst_registrations.registration_type for the one '
  'registration that lives on this table rather than in that one. Read by '
  'domain/gst/registrations.primary_of(). GST-25, migration 420.';

COMMENT ON COLUMN public.clients.composition_category IS
  'Which s.10 rate this composition dealer pays — NULL means unrecorded, not '
  '"the lowest rate": manufacturer/trader (1%), restaurant (5%, first proviso '
  'to s.10(1)) and other service provider (6%, s.10(2A)) are different rates '
  'on the same turnover and neither direction of guessing is safe. Meaningless '
  'unless gst_registration_type = ''composition''; not CHECKed against it '
  'because the door that records the type and the door that records the '
  'category may be filled in on different visits. domain/gst/composition.py '
  'is the authority. GST-25, migration 420.';

COMMENT ON COLUMN public.client_gst_registrations.composition_category IS
  'The same fact as clients.composition_category, for an ADDITIONAL '
  'registration whose own registration_type is ''composition'' rather than '
  'the client''s primary. GST-25, migration 420.';

COMMIT;
