-- 312: a foreign remittance that withheld NOTHING is still a remittance.
--
-- WHY
--   services/tds_register_service wrote a register row only when tax was
--   actually deducted. So a payment to a non-resident that withheld NIL --
--   because the income is business profits and the payee has no permanent
--   establishment in India, or because the treaty has no article for it --
--   left no row at all.
--
--   Those are the two remittances an assessing officer is most likely to ask
--   about. Both rest on a CLAIM, and the register Form 27Q is assembled from
--   had no record that the payment happened.
--
--   It also disabled the two controls built for exactly this case: the
--   missing-Form-15CA gap and the undated-no-PE-declaration gap are computed
--   after that early return, so on a nil remittance they could never fire.
--   Rule 37BB wants Form 15CA whether or not tax was deducted -- Part D of the
--   form exists for a remittance that is not taxable.
--
--   Found by driving a client with four overseas suppliers through a year:
--   two of the four booked, posted and paid with nothing in the register.
--
-- WHY A REASON COLUMN AND NOT AN FVU REMARK CODE
--   Form 27Q's deductee annexure carries a reason-for-non-deduction code, and
--   this migration does NOT invent one. The codes are a published list with
--   meanings attached, and guessing which applies to an Article 7 nil would
--   put a wrong code in a filed return. What is stored is the ENGINE's own
--   basis -- 'not_chargeable', 'treaty', 'act', '206aa_floor' -- plus the
--   sentence it resolved on. Mapping that to the FVU code is a human step,
--   like the treaty rate before it.
--
-- Re-runnable, single transaction.

BEGIN;

ALTER TABLE public.purchase_bills
  ADD COLUMN IF NOT EXISTS tds_basis text;

COMMENT ON COLUMN public.purchase_bills.tds_basis IS
    'How the s.195 withholding was arrived at: not_chargeable / treaty / act / '
    '206aa_floor, from domain/tds/section_195.Section195Resolution.basis. '
    'NULL on a resident-section bill, which has only one basis. Persisted so a '
    'nil can be told apart from an absence months later. Migration 312.';

ALTER TABLE public.tds_deductions
  ADD COLUMN IF NOT EXISTS non_deduction_reason text;

COMMENT ON COLUMN public.tds_deductions.non_deduction_reason IS
    'Why nothing was withheld on a remittance that still belongs on Form 27Q — '
    'the engine''s own sentence, citing the provision. NOT an FVU remark code: '
    'those are a published list and guessing one would put a wrong code in a '
    'filed return, so mapping this to a code is a human step. NULL wherever '
    'tax was actually deducted. Migration 312.';

-- Assembling 27Q for a quarter now has to find the nil rows too, and they are
-- the ones with no tds_paise to sort by.
CREATE INDEX IF NOT EXISTS idx_tds_deductions_nil_remittances
  ON public.tds_deductions (firm_id, client_id, transaction_date)
  WHERE tds_paise = 0;

COMMIT;
