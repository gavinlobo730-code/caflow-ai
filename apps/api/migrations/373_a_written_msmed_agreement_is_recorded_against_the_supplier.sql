-- The MSMED s.15 period agreed IN WRITING, against the supplier (PUR-15).
--
-- WHY THE DEFAULT IS FIFTEEN DAYS AND NOT FORTY-FIVE
--
-- s.15 of the MSMED Act 2006 requires a buyer to pay "on or before the date
-- agreed upon between him and the supplier IN WRITING, or, where there is no
-- agreement in this behalf, before the appointed day", with a proviso that
-- "in no case shall the period agreed upon between the supplier and the buyer
-- in writing exceed forty-five days". s.2(b) makes the appointed day the day
-- immediately following the expiry of FIFTEEN days from acceptance.
--
-- So fifteen is the rule and forty-five is the exception. Forty-five is the
-- number every article quotes, and applying it by default would give a month
-- of grace the Act does not -- understating the s.43B(h) disallowance, which
-- under-reports taxable income.
--
-- WHY IT IS A COLUMN AND WHY IT IS NOT credit_days
--
-- `vendors.credit_days` (migration 201) is a COMMERCIAL term: what the vendor
-- master says the payment period is. It is not evidence that anything was
-- agreed in writing, and s.15's proviso reaches only a written agreement.
-- Reading credit_days as the s.15 period would apply 30 days where the Act
-- gives 15, on every vendor carrying the default.
--
-- Whether a written agreement exists is a fact about a document nobody in this
-- product holds. So it is recorded, nullable, with no default, and a NULL
-- means "no written agreement recorded" -- which is the statutory default
-- rather than an absence of information. Same shape as vendors.msme_status,
-- which migration 303 added beside it for the same reason.
--
-- NOT CAPPED AT 45 IN THE CHECK, DELIBERATELY. A contract for sixty days is
-- not void; it is ineffective beyond forty-five. Storing what the contract
-- actually says and capping in domain/income_tax/section_43b_h.py -- which
-- SAYS it capped -- keeps the record true and the computation lawful. A CHECK
-- at 45 would force the CA to record a period their own contract does not say.

ALTER TABLE public.vendors
  ADD COLUMN IF NOT EXISTS msmed_agreement_days INTEGER;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conname = 'vendors_msmed_agreement_days_check') THEN
    ALTER TABLE public.vendors
      ADD CONSTRAINT vendors_msmed_agreement_days_check
      CHECK (msmed_agreement_days IS NULL OR msmed_agreement_days > 0);
  END IF;
END $$;

COMMENT ON COLUMN public.vendors.msmed_agreement_days IS
  'The payment period agreed with this supplier IN WRITING, in days, under the '
  'proviso to MSMED s.15. NULL = no written agreement recorded, so s.2(b)''s '
  'appointed day applies and the period is FIFTEEN days. A value above 45 is '
  'stored as recorded and CAPPED at 45 by the s.43B(h) engine, which says so: '
  'the proviso makes a longer period ineffective, not the contract void. NOT '
  'the same as credit_days, which is a commercial term and no evidence of a '
  'written agreement.';
