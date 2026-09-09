-- 348: the payee CLASS a section 195 surcharge keys on.
--
-- WHY
--   Part II of the First Schedule does not have one surcharge ladder. It gives
--   a different one to a foreign company, to an individual or HUF, to a firm
--   or LLP, to an AOP/BOI and to a co-operative society. domain/tds/
--   section_195.py modelled that as a BOOLEAN — `is_company`, whose only
--   production source was is_company_pan(), which returns True for any PAN
--   whose 4th character is not P or H.
--
--   So a foreign FIRM or LLP (4th character F), an AOP (A), a trust (T) and a
--   payee with NO PAN AT ALL were every one of them given the foreign-company
--   ladder and its 2%/5% bands, instead of the 10/15/25/37 ones. On a
--   Rs 2 crore royalty that is Rs 80,000 of surcharge where the other ladder
--   gives Rs 6,00,000.
--
--   The direction is what makes it serious. It UNDER-deducts, and an
--   under-deduction under s.195 disallows the WHOLE expenditure under
--   s.40(a)(i) — not the tax, the expense. And the no-PAN case is not an edge
--   case: a foreign supplier commonly has no Indian PAN, which is the very
--   situation s.206AA(7) and Rule 37BC exist to serve. is_company_pan's
--   docstring calls returning True for a missing PAN "the conservative higher
--   rate", and that is true for the resident s.194 series (1% vs 2%) and false
--   at this second call site, where the conservative ladder is the other one.
--
-- WHY A COLUMN AND NOT A DERIVATION
--   Because the PAN cannot answer it. A non-resident payee often has no Indian
--   PAN, and where one exists this repository only asserts what six letters
--   mean (P, H, C, F, A, B — see domain/tds/section_195.py::payee_class_from
--   _pan); T and J are deliberately unmapped. So the class is a fact ABOUT THE
--   SUPPLIER that a CA establishes and records, in the same family as
--   residential_status (migration 308), section_195_nature_of_income (309) and
--   msme_status. The derived value is a fallback, and the recorded one wins.
--
-- WHAT HAPPENS WITH NO VALUE
--   The engine REFUSES, naming the classes whose ladder it holds. It does not
--   fall back, because there is no safe fallback: the non-corporate ladder
--   over-deducts on a foreign company and the foreign-company ladder
--   under-deducts on everyone else. Two of the six classes — firm_llp and
--   co_operative — are refused even when RECORDED, because Part II's ladders
--   for them are not held in section_195_rates.py and will not be guessed at.
--   Adding them later is a pure data change.
--
-- BLAST RADIUS
--   NULL default, so nothing existing changes shape. What changes is that a
--   s.195 bill for a vendor with no class recorded now refuses instead of
--   silently withholding on the wrong ladder — which is the point, and is why
--   this migration ships in the same change as the vendor form's select. The
--   refusal has to have a remedy in the same release.
--
--   Production holds 11 vendors and none is recorded non-resident, so no live
--   bill path is affected today.

BEGIN;

ALTER TABLE public.vendors
  ADD COLUMN IF NOT EXISTS non_resident_payee_class TEXT;

-- The CHECK carries every class the engine names, INCLUDING the two it cannot
-- yet rate. Recording "firm or LLP" is a true statement about the supplier and
-- must be storable; whether this software can compute a surcharge for it is a
-- separate question, answered by section_195_rates.surcharge_by_class and
-- reported as a refusal rather than by refusing the vendor record.
ALTER TABLE public.vendors
  DROP CONSTRAINT IF EXISTS vendors_non_resident_payee_class_check;
ALTER TABLE public.vendors
  ADD CONSTRAINT vendors_non_resident_payee_class_check
  CHECK (non_resident_payee_class IS NULL OR non_resident_payee_class IN (
    'foreign_company', 'individual_huf', 'firm_llp',
    'aop_boi', 'co_operative', 'unknown'));

COMMENT ON COLUMN public.vendors.non_resident_payee_class IS
  'Part II First Schedule payee class, which decides the s.195 SURCHARGE '
  'ladder — a foreign company''s tops at 5%, an individual''s at 37%. NULL '
  'means nobody has established it, which is a third state and not a default: '
  'the engine refuses rather than picking a ladder. Overrides the class '
  'derived from the PAN''s 4th character, because a non-resident payee often '
  'has no Indian PAN at all. See migration 348 and domain/tds/section_195.py.';

COMMIT;
