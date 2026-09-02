-- 308: a vendor's residential status, and the two identifiers Form 27Q needs.
--
-- WHY
--   tds_deductions.return_type was written '26Q' unconditionally, because
--   nothing in this schema recorded whether a vendor was a resident. 26Q is
--   the right statement for non-salary payments to RESIDENTS (Rule 31A(4)(a));
--   a payment to a non-resident belongs in 27Q under Rule 31A(4)(b).
--
--   And it is not only the form. Sections 193, 194, 194A, 194C, 194D, 194G,
--   194H, 194I, 194J, 194K, 194LA and 194Q all charge, in their own words,
--   payments "to a resident" — so for a non-resident payee they do not apply
--   at all and section 195 does, at the rates in force under Part II of the
--   First Schedule, with surcharge and cess, subject to the DTAA under s.90(2).
--   domain/tds/residency.py carries the citations and is the authority.
--
-- WHAT IS DELIBERATELY NOT HERE
--   Any section 195 rate. Nature of income x treaty country x surcharge band
--   cannot be written from memory (CLAUDE.md), and a wrong s.195 deduction
--   disallows the whole expenditure under s.40(a)(i). The code refuses and
--   names the gap; adding the rates is a human step.
--
-- NULL IS NOT "RESIDENT", AND IT IS ALSO NOT msme_status
--   Every row predating this migration is NULL, and NULL is treated as
--   resident for COMPUTATION — 26Q at the section rate, which is correct for
--   the domestic vendors this platform serves and is not worth blocking every
--   bill of every client over. That is the opposite of migration 303's
--   msme_status, where an unclassified vendor may not be defaulted into
--   "Others" because s.43B(h) makes the classification change taxable income.
--   The difference is what the default costs, not a change of principle.
--   The silence is what is fixed: the register reports which vendors it
--   assumed resident.
--
-- Re-runnable: ADD COLUMN IF NOT EXISTS throughout, constraints added only if
-- absent, and the whole file in one transaction so a failure cannot leave a
-- column added without its CHECK.

BEGIN;

-- ── 1. The vendor's residential status ──────────────────────────────────────

ALTER TABLE public.vendors
  ADD COLUMN IF NOT EXISTS residential_status text,
  ADD COLUMN IF NOT EXISTS country_of_residence text,
  ADD COLUMN IF NOT EXISTS tax_identification_number text;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'vendors_residential_status_check'
                      AND conrelid = 'public.vendors'::regclass) THEN
        ALTER TABLE public.vendors
          ADD CONSTRAINT vendors_residential_status_check
          CHECK (residential_status IS NULL
                 OR residential_status IN ('resident', 'non_resident'));
    END IF;
END $$;

-- ISO 3166-1 alpha-2, which is what the 27Q country field takes. Two upper
-- case letters or nothing — a free-text "United Arab Emirates" in a column the
-- return reads as a code is a rejected FVU file, discovered at filing.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'vendors_country_of_residence_check'
                      AND conrelid = 'public.vendors'::regclass) THEN
        ALTER TABLE public.vendors
          ADD CONSTRAINT vendors_country_of_residence_check
          CHECK (country_of_residence IS NULL
                 OR country_of_residence ~ '^[A-Z]{2}$');
    END IF;
END $$;

COMMENT ON COLUMN public.vendors.residential_status IS
    'IT Act residential status of the PAYEE, which decides both the charging '
    'section and the quarterly statement. NULL means nobody has classified '
    'this vendor and is treated as resident for computation (26Q at the '
    'section rate) while being reported as a gap — unlike msme_status, which '
    'has no safe default. ''non_resident'' takes the payment out of s.194C and '
    'its neighbours entirely (they charge only payments "to a resident") and '
    'into s.195, whose rate this software does not compute. '
    'domain/tds/residency.py is the authority. Migration 308.';

COMMENT ON COLUMN public.vendors.country_of_residence IS
    'ISO 3166-1 alpha-2 country code of a non-resident payee, reported on Form '
    '27Q and one of the six particulars Rule 37BC requires before the s.206AA '
    '20% floor can be relieved. Migration 308.';

COMMENT ON COLUMN public.vendors.tax_identification_number IS
    'The payee''s tax identification number in its country of residence. '
    'Required on 27Q where the deductee has no PAN, and part of the Rule 37BC '
    'relief from the s.206AA floor. Migration 308.';

-- ── 2. The same two identifiers on the deduction row ────────────────────────
-- Copied onto the deduction rather than joined at filing time, for the reason
-- deductee_name and deductee_pan already are on this table: the return states
-- what was true WHEN THE TAX WAS DEDUCTED. A vendor that later changes its TIN
-- must not silently rewrite a quarter that has already been filed.

ALTER TABLE public.tds_deductions
  ADD COLUMN IF NOT EXISTS country_of_residence text,
  ADD COLUMN IF NOT EXISTS deductee_tin text;

COMMENT ON COLUMN public.tds_deductions.country_of_residence IS
    'ISO 3166-1 alpha-2 country of the deductee, as at the deduction date. '
    'Populated for 27Q rows; NULL on a 26Q row, where the form does not ask. '
    'Migration 308.';

COMMENT ON COLUMN public.tds_deductions.deductee_tin IS
    'The deductee''s foreign tax identification number, as at the deduction '
    'date. 27Q requires it where the deductee has no PAN. Migration 308.';

-- Assembling 27Q for a quarter reads exactly the non-26Q rows. Without this it
-- is a sequential scan of every deduction the firm has ever recorded.
CREATE INDEX IF NOT EXISTS idx_tds_deductions_return_type
  ON public.tds_deductions (firm_id, client_id, return_type, transaction_date);

COMMIT;
