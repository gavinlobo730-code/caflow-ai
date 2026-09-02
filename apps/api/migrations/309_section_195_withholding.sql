-- 309: what a section 195 withholding needs, on the vendor and on the bill.
--
-- WHY
--   Migration 308 recorded WHETHER a vendor is a non-resident, and the bill
--   path then refused to compute anything, because s.194C and its neighbours
--   charge only payments "to a resident" and s.195 -- which applies instead --
--   was not modelled. This is what s.195 needs.
--
-- THE FOUR FACTS, AND WHY EACH IS A HUMAN INPUT
--
--   section_195_nature_of_income. s.195 deducts "at the rates in force", and
--   those key on the NATURE of the income -- royalty, fees for technical
--   services, interest, capital gains, other sums -- not on the kind of work
--   done, which is where s.194C and s.194J key. No bill line says which it is.
--
--   no_pe_declaration_on_file. The most consequential value the nature column
--   can hold is 'business_profits_no_pe', which withholds NIL: s.195 reaches
--   only a sum "chargeable under the provisions of this Act", and business
--   profits of a non-resident with no permanent establishment here are not
--   chargeable -- GE India Technology Centre (P) Ltd v. CIT (2010) 327 ITR 456.
--   An ordinary import of goods is exactly that. Withholding nil is a large
--   claim and this is its evidence, so the engine refuses the nil without it.
--
--   trc_on_file / form_10f_on_file. s.90(2) gives the assessee the more
--   beneficial of the Act and the treaty; s.90(4) conditions that on a Tax
--   Residency Certificate, and Rule 21AB on Form 10F.
--
--   treaty_rate_bps. THE RATE ITSELF, read off the agreement by a human. This
--   software holds no DTAA table and is not going to: India has agreements
--   with over ninety countries, their royalty/FTS/interest articles differ,
--   MFN clauses need their own s.90(1) notification (AO v. Nestle SA, 2023),
--   and several agreements -- the UAE and Singapore among them -- have no fees
--   for technical services article at all. A wrong treaty rate too low
--   disallows the WHOLE expenditure under s.40(a)(i); too high takes money off
--   a supplier who can only recover it by filing an Indian return.
--
--   Where a TRC is held and no treaty rate is recorded, the engine REFUSES
--   rather than falling back to the Act rate -- the fallback would over-deduct
--   in precisely the case where somebody has already established a treaty
--   applies.
--
-- WHAT GOES ON THE BILL AND THE DEDUCTION
--   The surcharge and the cess, separately. s.195 withholds at the rates in
--   force INCLUDING both, unlike the resident 194 series which does not, and
--   Form 27Q's deductee annexure reports tax, surcharge and cess in their own
--   columns. Carrying only a total would make the return unassemblable and
--   a challan unreconcilable.
--
--   So on a s.195 bill, tds_paise is the TOTAL withheld and tds_rate_bps is
--   the BASE rate -- they no longer satisfy tds_paise = taxable * rate / 10000,
--   which holds for every resident-section bill. That is correct and is pinned
--   by a test; the base rate is what 27Q asks for.
--
-- Re-runnable: ADD COLUMN IF NOT EXISTS throughout, constraints added only if
-- absent, whole file in one transaction so a failure cannot leave a column
-- without its CHECK.

BEGIN;

-- 1. The vendor -------------------------------------------------------------

ALTER TABLE public.vendors
  ADD COLUMN IF NOT EXISTS section_195_nature_of_income text,
  ADD COLUMN IF NOT EXISTS trc_on_file boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS form_10f_on_file boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS no_pe_declaration_on_file boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS treaty_rate_bps integer;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'vendors_section_195_nature_check'
                      AND conrelid = 'public.vendors'::regclass) THEN
        ALTER TABLE public.vendors
          ADD CONSTRAINT vendors_section_195_nature_check
          CHECK (section_195_nature_of_income IS NULL
                 OR section_195_nature_of_income IN ('royalty', 'fees_for_technical_services', 'interest', 'interest_194lc', 'dividend', 'ltcg_112', 'ltcg_112a', 'stcg_111a', 'business_profits_no_pe', 'other_sums'));
    END IF;
END $$;

-- 0 to 10000 bps. A treaty rate is a percentage of the payment; anything above
-- 100% is a typo, and a NEGATIVE one would refund tax out of a withholding.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'vendors_treaty_rate_bps_check'
                      AND conrelid = 'public.vendors'::regclass) THEN
        ALTER TABLE public.vendors
          ADD CONSTRAINT vendors_treaty_rate_bps_check
          CHECK (treaty_rate_bps IS NULL
                 OR (treaty_rate_bps >= 0 AND treaty_rate_bps <= 10000));
    END IF;
END $$;

COMMENT ON COLUMN public.vendors.section_195_nature_of_income IS
    'Nature of income for s.195 withholding, which is what the rates in force '
    'key on. domain/tds/section_195_rates.ALL_NATURES generates this CHECK. '
    '''business_profits_no_pe'' withholds NIL (GE India Technology Centre v. '
    'CIT) and requires no_pe_declaration_on_file. Migration 309.';

COMMENT ON COLUMN public.vendors.treaty_rate_bps IS
    'The DTAA rate in basis points, read off the agreement by a human. This '
    'software holds no treaty table. s.90(2) then applies whichever of this '
    'and the Act rate is lower. NULL with trc_on_file true makes the engine '
    'REFUSE rather than fall back to the Act rate, which would over-deduct. '
    'Migration 309.';

COMMENT ON COLUMN public.vendors.no_pe_declaration_on_file IS
    'Evidence for a nil withholding on business profits: s.195 reaches only a '
    'sum chargeable under the Act, and a non-resident with no permanent '
    'establishment in India is not chargeable here. Migration 309.';

-- 2. The bill ---------------------------------------------------------------

ALTER TABLE public.purchase_bills
  ADD COLUMN IF NOT EXISTS tds_surcharge_paise bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tds_cess_paise bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tds_nature_of_income text;

COMMENT ON COLUMN public.purchase_bills.tds_surcharge_paise IS
    'Surcharge component of a s.195 withholding, Part II First Schedule. '
    'Always 0 on a resident-section bill, which deducts at the bare section '
    'rate. Included in tds_paise. Migration 309.';

COMMENT ON COLUMN public.purchase_bills.tds_cess_paise IS
    'Health and education cess component of a s.195 withholding. Always 0 on '
    'a resident-section bill. Included in tds_paise. Migration 309.';

COMMENT ON COLUMN public.purchase_bills.tds_nature_of_income IS
    'The nature of income the s.195 rate was resolved on, copied from the '
    'vendor AT THE TIME OF DEDUCTION so a later change to the vendor cannot '
    'rewrite what was withheld. NULL on a resident-section bill. Migration 309.';

-- 3. The deduction row 27Q is assembled from --------------------------------

ALTER TABLE public.tds_deductions
  ADD COLUMN IF NOT EXISTS surcharge_paise bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cess_paise bigint NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.tds_deductions.surcharge_paise IS
    'Form 27Q reports tax, surcharge and cess in separate columns of the '
    'deductee annexure. Included in tds_paise, which stays the total. '
    'Migration 309.';

COMMENT ON COLUMN public.tds_deductions.cess_paise IS
    'See surcharge_paise. Migration 309.';

COMMIT;
