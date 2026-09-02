-- 311: who claimed the nil, and whether Rule 37BB was completed.
--
-- WHY
--   The largest claim s.195 lets anyone make is that NOTHING is withheld: a
--   payment is business profits and the payee has no permanent establishment in
--   India, so it is not "chargeable under the provisions of this Act" and s.195
--   does not reach it -- GE India Technology Centre (P) Ltd v. CIT (2010) 327
--   ITR 456.
--
--   Migration 309 made that claim a BOOLEAN on the vendor. A tick box is enough
--   to compute with and not enough to defend: s.201(1) treats a deductor who
--   fails to deduct as an assessee in default, s.201(1A) charges interest, and
--   s.40(a)(i) disallows the whole expenditure. When that is questioned, "a box
--   was ticked" answers none of who, when, or on what evidence.
--
--   So the declaration gets the three things an audit trail needs, and the
--   remittance gets the Rule 37BB paperwork that should have accompanied it.
--
-- WHAT IS NOT HERE
--   Any workflow. Nothing blocks a bill on a missing 15CA, and nothing files
--   one -- Rule 37BB is a portal submission and CLAUDE.md's rule stands: never
--   auto-submit anything to any government portal. These columns RECORD what a
--   human did, so the gap between "money left" and "the form was filed" stops
--   being invisible.
--
-- NULLABLE THROUGHOUT
--   Every vendor predating this has no declaration date and no declarer, and
--   backfilling either would be inventing evidence. An unattributed declaration
--   is reported as a gap, not repaired.
--
-- Re-runnable, single transaction.

BEGIN;

-- 1. The declaration behind a nil ------------------------------------------

ALTER TABLE public.vendors
  ADD COLUMN IF NOT EXISTS no_pe_declaration_on date,
  ADD COLUMN IF NOT EXISTS no_pe_declaration_by uuid REFERENCES public.users(id),
  ADD COLUMN IF NOT EXISTS no_pe_declaration_ref text;

COMMENT ON COLUMN public.vendors.no_pe_declaration_on IS
    'Date the payee''s no-permanent-establishment declaration was obtained. '
    'The nil withholding it supports rests on s.195 reaching only a sum '
    'chargeable under the Act (GE India Technology Centre v. CIT), and '
    's.201(1)/(1A) put the consequence of getting that wrong on the DEDUCTOR — '
    'so an undated declaration is a claim with no evidence behind it. '
    'Migration 311.';

COMMENT ON COLUMN public.vendors.no_pe_declaration_ref IS
    'Where the declaration is filed — a document reference, letter number or '
    'storage path. Not validated: what a firm can produce on demand differs. '
    'Migration 311.';

-- 2. The Rule 37BB paperwork for the remittance -----------------------------
-- On the BILL, not the vendor: 15CA is per remittance, and a vendor paid four
-- times in a year needs four of them.

ALTER TABLE public.purchase_bills
  ADD COLUMN IF NOT EXISTS form_15ca_ack_no text,
  ADD COLUMN IF NOT EXISTS form_15ca_filed_on date,
  ADD COLUMN IF NOT EXISTS form_15cb_udin text;

COMMENT ON COLUMN public.purchase_bills.form_15ca_ack_no IS
    'Acknowledgement number of the Form 15CA filed for this remittance under '
    's.195(6) with Rule 37BB. RECORDED here, never filed from here — CLAUDE.md: '
    'never auto-submit to any government portal. NULL on every domestic bill. '
    'Migration 311.';

COMMENT ON COLUMN public.purchase_bills.form_15cb_udin IS
    'UDIN of the accountant''s certificate in Form 15CB, where Rule 37BB '
    'requires one. The UDIN is what makes the certificate traceable to the '
    'member who signed it. Migration 311.';

CREATE INDEX IF NOT EXISTS idx_purchase_bills_foreign_remittance
  ON public.purchase_bills (firm_id, client_id, bill_date)
  WHERE tds_section = '195';

COMMIT;
