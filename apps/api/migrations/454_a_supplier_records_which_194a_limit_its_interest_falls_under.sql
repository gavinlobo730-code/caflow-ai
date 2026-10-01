-- 454: which of section 194A(3)(i)'s limits a supplier's interest falls under.
--
-- WHY
--   domain/tds/section_rates.py held ONE threshold for s.194A, ₹10,000, and a
--   comment saying the Finance Act 2025 limits for a bank deposit (₹50,000) and
--   for a senior citizen's deposit (₹1,00,000) were "not modelled — payer type
--   isn't modelled, so the lowest applies" (TDS-30). That is the safe
--   direction, and it is wrong in the other direction too: a co-operative bank
--   or a post office withheld on a ₹30,000 deposit interest bill that the
--   section does not charge.
--
--   The limits hang on TWO facts and not one, and the finding's own wording
--   ("bank, senior citizen, other" as payee classes) would have under-deducted
--   on the commonest s.194A payment a practice sees. The senior-citizen limit
--   exists only INSIDE the first limb — where the PAYER is a bank, a
--   co-operative bank or a post office and the interest is on a deposit. A
--   company paying a pensioner interest on an unsecured loan withholds at
--   ₹10,000 whoever is paid. So the column is a three-answer CLASS (the
--   product of the two facts, the way Donation80G's four categories are), and
--   a payee's age alone is deliberately not an answer.
--
-- WHY A COLUMN AND NOT A DERIVATION
--   Because nothing else holds either fact: a senior citizen is an age, and
--   "interest on a deposit with a bank" is a fact about the instrument. The PAN
--   cannot say either. It is recorded on the SUPPLIER, in the same family as
--   residential_status (308), non_resident_payee_class (348) and msme_status.
--
-- WHAT HAPPENS WITH NO VALUE
--   NULL is "nobody said" and the engine takes the section's own ₹10,000 — the
--   lowest limit, which cannot under-deduct — exactly as every supplier did
--   before this column existed. NO BACKFILL, and no existing supplier's
--   withholding changes on the day this lands.
--
--   'ordinary' is a STATEMENT ("this is not a bank deposit"), not an absence.
--   It resolves to the same ₹10,000 and exists because PATCH /api/vendors
--   drops a null (`model_dump(exclude_none=True)`), so without a word for it a
--   CA who recorded the wrong class could never take it back.
--
-- WHAT THIS DOES NOT DO
--   It is not asked of any other section: a raising class recorded against a
--   section with a single limit is refused at the vendor door and, if it ever
--   reaches the engine, refused there too — a control that does nothing reads
--   as one that worked. And it is IGNORED for a financial year before 2025-26,
--   where the raised limits did not exist (section_rates.
--   SECTION_194A_CLASS_THRESHOLDS_FIRST_FY). Interest paid TO a bank, which
--   s.194A(3)(iii) exempts outright, is a reason to leave TDS off the supplier
--   and is not modelled here.
--
-- ADDITIVE AND IDEMPOTENT. One nullable column and its CHECK; nothing existing
-- is rewritten. Production holds no row with a value, so the CHECK cannot fail
-- against stored data; NOT VALID + VALIDATE is used anyway, matching 424 and
-- 427, because this runs unattended on merge and a pattern that is right
-- whether or not the table holds data is worth more than one that only happens
-- to be right today.

BEGIN;

ALTER TABLE public.vendors
  ADD COLUMN IF NOT EXISTS interest_threshold_class TEXT;

ALTER TABLE public.vendors
  DROP CONSTRAINT IF EXISTS vendors_interest_threshold_class_check;
ALTER TABLE public.vendors
  ADD CONSTRAINT vendors_interest_threshold_class_check
  CHECK (interest_threshold_class IS NULL OR interest_threshold_class IN (
    'ordinary', 'bank_deposit', 'bank_deposit_senior'))
  NOT VALID;
ALTER TABLE public.vendors
  VALIDATE CONSTRAINT vendors_interest_threshold_class_check;

COMMENT ON COLUMN public.vendors.interest_threshold_class IS
  'Which s.194A(3)(i) limit this supplier''s interest falls under: ordinary '
  '(any payer other than a bank, co-operative bank or post office, ₹10,000) | '
  'bank_deposit (interest on a deposit with one of those, ₹50,000) | '
  'bank_deposit_senior (the same, payee a senior citizen, ₹1,00,000). NULL '
  'means nobody said and takes ₹10,000, the lowest. The senior-citizen limit '
  'exists only inside the bank-deposit limb, so a payee''s age alone is not an '
  'answer. Ignored for a financial year before 2025-26. Migration 454; '
  'domain/tds/section_rates.py is the authority.';

COMMIT;
