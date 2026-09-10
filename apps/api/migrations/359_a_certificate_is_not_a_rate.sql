-- Migration 359: the §197 lower-deduction certificate, which is four facts.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING (PUR-07 ≡ TDS-13)
-- ═══════════════════════════════════════════════════════════════════════════
-- A transport contractor or an advertising agency produces a certificate under
-- §197 allowing deduction at 0.5% instead of 2%. There was nowhere to record
-- it. `vendors` has no certificate column of any kind (migration 049 and every
-- later ALTER — 201, 303, 308, 309, 311), and `resolve_tds` took no certificate
-- parameter, so a certificate holder was always withheld at the full section
-- rate. The CA's only options were to turn TDS off on the vendor — losing the
-- register row, the 26Q deductee line and the challan — or to accept the
-- over-deduction and let the vendor claim a refund.
--
-- `tds_deductions.is_lower_deduction` and `.lower_deduction_cert` have existed
-- since migration 037 and nothing has ever written to them, so Form 26Q's own
-- lower-deduction fields were permanently blank — and the FVU requires the
-- certificate number wherever a below-normal rate is used.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY A TABLE AND NOT A COLUMN ON vendors
-- ═══════════════════════════════════════════════════════════════════════════
-- §197(1) lets the Assessing Officer certify a lower rate, or no deduction at
-- all, and Rule 28AA(4) requires the certificate to be issued for a SPECIFIED
-- AMOUNT and a SPECIFIED PERIOD. So a certificate is four facts and not one:
--
--     the rate, the certificate NUMBER, the period it is valid for, and the
--     amount up to which it applies.
--
-- A bare percentage on the vendor cannot express any of them, which is exactly
-- why PUR-06 deleted `vendors.tds_rate_bps` from the vendor form rather than
-- honouring it: a CA typed 1%, saw "1.0%" in the list, and every bill deducted
-- 2%. And one vendor may hold several — a different certificate per section,
-- and a fresh one each year, since Rule 28AA(4) caps validity at the financial
-- year.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IS DELIBERATELY NOT STORED: HOW MUCH OF THE CEILING IS USED UP
-- ═══════════════════════════════════════════════════════════════════════════
-- The obvious fifth column is `consumed_paise`. It is not here, because it is
-- DERIVABLE from the documents that consumed it — the sums credited or paid to
-- that vendor under that section inside the validity window — and a stored
-- copy of a derived figure drifts the moment a bill is edited, cancelled or
-- soft-deleted. services/vendor_tds.py already reads exactly those documents to
-- compute the §194C-style FY aggregate; the certificate's headroom falls out of
-- the same pass.
--
-- The ceiling is NOT NULL on purpose. A TRACES certificate always carries an
-- amount, and a certificate with no ceiling is one that can never be exhausted
-- — which is the failure this whole table exists to prevent, moved one level
-- down where it is harder to see.

BEGIN;

CREATE TABLE IF NOT EXISTS public.tds_lower_deduction_certificates (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         uuid NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    client_id       uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    vendor_id       uuid NOT NULL REFERENCES public.vendors(id) ON DELETE CASCADE,
    -- The section the certificate is issued UNDER, in this codebase's own
    -- vocabulary ("194C", "194J", "195"). §197(1) lists the provisions it
    -- reaches and domain/tds/lower_deduction.py holds that list — §194Q, for
    -- one, is not among them.
    section         text NOT NULL,
    certificate_no  text NOT NULL,
    -- 0 is a real and common value: §197(1) allows "no deduction of tax".
    rate_bps        integer NOT NULL,
    valid_from      date NOT NULL,
    valid_to        date NOT NULL,
    -- Rule 28AA(4): the amount up to which the certificate applies. This is a
    -- ceiling on the SUM CREDITED OR PAID, not on the tax.
    ceiling_paise   bigint NOT NULL,
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    created_by      uuid REFERENCES public.users(id),
    CONSTRAINT tds_ldc_rate_is_a_reduction
        CHECK (rate_bps >= 0 AND rate_bps <= 10000),
    CONSTRAINT tds_ldc_period_is_a_period
        CHECK (valid_to >= valid_from),
    CONSTRAINT tds_ldc_ceiling_is_positive
        CHECK (ceiling_paise > 0)
);

COMMENT ON TABLE public.tds_lower_deduction_certificates IS
    'IT Act §197 lower-deduction (or nil-deduction) certificates, per vendor '
    'per section. Rule 28AA(4) makes a certificate an AMOUNT and a PERIOD as '
    'well as a rate, so all four are held. How much of the ceiling is used up '
    'is NOT stored — it is derived from the documents inside the window by '
    'services/vendor_tds.py. Migration 359.';
COMMENT ON COLUMN public.tds_lower_deduction_certificates.rate_bps IS
    'Basis points, so 0.5% is 50 and a NIL certificate is 0 — §197(1) allows '
    'deduction at a lower rate OR no deduction at all.';
COMMENT ON COLUMN public.tds_lower_deduction_certificates.ceiling_paise IS
    'Rule 28AA(4): the amount up to which the certificate applies — a ceiling '
    'on the sum credited or paid, not on the tax. Beyond it the section rate '
    'resumes on the excess.';

-- One certificate number per vendor per section. The same number may not be
-- entered twice; two DIFFERENT numbers covering the same date are a real
-- possibility (a fresh certificate superseding one not yet expired) and are
-- REFUSED at read time by domain/tds/lower_deduction.py rather than by a
-- constraint here, because refusing the write would stop a CA recording a
-- certificate they actually hold.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tds_ldc_vendor_section_no
    ON public.tds_lower_deduction_certificates (firm_id, vendor_id, section, certificate_no);

CREATE INDEX IF NOT EXISTS idx_tds_ldc_lookup
    ON public.tds_lower_deduction_certificates (firm_id, client_id, vendor_id, section, valid_from, valid_to);

ALTER TABLE public.tds_lower_deduction_certificates ENABLE ROW LEVEL SECURITY;

-- Firm isolation plus role-guarded writes, in the shape migrations 260/261
-- established and 357 last used: the frontend reaches ~83 tables over PostgREST
-- where rbac() never runs, so a table's write policy is the only check on that
-- path. A certificate lowers what is withheld from a real supplier — an
-- invented one under-deducts and makes the deductor an assessee in default
-- under §201(1) — so it is Executive+ to write and Manager+ to delete.
DO $$
BEGIN
  EXECUTE 'DROP POLICY IF EXISTS firm_tds_ldc ON public.tds_lower_deduction_certificates';
  EXECUTE 'CREATE POLICY firm_tds_ldc ON public.tds_lower_deduction_certificates '
          'FOR ALL TO authenticated '
          'USING (firm_id = public.get_my_firm_id()) '
          'WITH CHECK (firm_id = public.get_my_firm_id())';

  EXECUTE 'DROP POLICY IF EXISTS tds_ldc_role_insert ON public.tds_lower_deduction_certificates';
  EXECUTE 'CREATE POLICY tds_ldc_role_insert ON public.tds_lower_deduction_certificates '
          'AS RESTRICTIVE FOR INSERT WITH CHECK (public.my_role_at_least(''Executive''))';

  EXECUTE 'DROP POLICY IF EXISTS tds_ldc_role_update ON public.tds_lower_deduction_certificates';
  EXECUTE 'CREATE POLICY tds_ldc_role_update ON public.tds_lower_deduction_certificates '
          'AS RESTRICTIVE FOR UPDATE USING (public.my_role_at_least(''Executive'')) '
          'WITH CHECK (public.my_role_at_least(''Executive''))';

  EXECUTE 'DROP POLICY IF EXISTS tds_ldc_role_delete ON public.tds_lower_deduction_certificates';
  EXECUTE 'CREATE POLICY tds_ldc_role_delete ON public.tds_lower_deduction_certificates '
          'AS RESTRICTIVE FOR DELETE USING (public.my_role_at_least(''Manager''))';

  EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.tds_lower_deduction_certificates TO authenticated';
END $$;

-- ── What the DOCUMENT records, so the register does not have to re-derive it ──
--
-- One column each, not two. `is_lower_deduction` on tds_deductions is exactly
-- "a certificate number is present", so storing both would be storing one fact
-- twice — and the two would eventually disagree.
--
-- Stored rather than re-derived at register time for the same reason
-- tds_rate_bps and tds_basis are: the register must say what WAS withheld, and
-- by the time it runs the ceiling may have been consumed by a later document,
-- so re-asking the engine would answer a different question.

ALTER TABLE public.purchase_bills
    ADD COLUMN IF NOT EXISTS tds_certificate_no text;
ALTER TABLE public.purchase_payments
    ADD COLUMN IF NOT EXISTS tds_certificate_no text;

COMMENT ON COLUMN public.purchase_bills.tds_certificate_no IS
    'The IT Act §197 certificate applied to this deduction, where one was. '
    'NULL where the section rate applied. Form 26Q''s deductee annexure '
    'requires the number wherever a below-normal rate is used, which is why it '
    'travels with the document rather than being looked up at filing time. '
    'Migration 359.';
COMMENT ON COLUMN public.purchase_payments.tds_certificate_no IS
    'As purchase_bills.tds_certificate_no — §194 and §195 charge at credit or '
    'payment whichever is earlier, so an advance can be certified too.';

COMMIT;
