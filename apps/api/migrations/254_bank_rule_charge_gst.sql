-- Migration 254: let a bank matching rule carry the GST treatment of a charge.
--
-- WHY THIS EXISTS
-- A bank charge arrives with its GST already inside the number. ₹590 debited at
-- 18% is ₹500 of charge and ₹90 of input tax credit under s.16 of the CGST Act,
-- 2017 — a bank charge is an input service received in the course or furtherance
-- of business. Booking the gross ₹590 to Bank Charges, which is what the posting
-- engine did before, threw that credit away every single month.
--
-- Splitting it needs two facts the statement does not contain:
--
--   the RATE          banking services are 18% (Notification 11/2017-CTR), but
--                     some bank debits carry no GST at all — interest, certain
--                     government levies — and 0 is a real answer, not a missing
--                     one.
--   the PLACE         s.12(12) of the IGST Act, 2017 puts the place of supply
--   OF SUPPLY         for banking services at the location of the RECIPIENT on
--                     the supplier's records. An account with a branch in the
--                     client's own state is intra-state (CGST + SGST); a bank
--                     registered elsewhere supplying the same service is
--                     inter-state (IGST).
--
-- Neither is inferable. An IFSC does not encode a state, and guessing the tax
-- head on a statutory credit is exactly what this codebase refuses to do. But
-- both are constant per bank, so they belong on the RULE — stated once by the CA
-- when the rule is set up, rather than re-typed on every ₹590 charge.
--
-- SUGGESTIONS ONLY
-- Same contract as every other column on this table: a rule proposes, a human
-- disposes. Nothing here auto-posts. The values ride into the posting drawer as
-- a prefill that the CA can see and change before confirming.

BEGIN;

ALTER TABLE public.bank_matching_rules
  ADD COLUMN IF NOT EXISTS suggested_gst_rate_bps   INTEGER,
  ADD COLUMN IF NOT EXISTS suggested_is_interstate  BOOLEAN NOT NULL DEFAULT false;

-- Basis points, and a CLOSED vocabulary. A typo in a tax head becomes a wrong
-- GSTR-3B, so "whatever the caller sent" is not acceptable here. NULL means the
-- rule says nothing about GST (the charge is posted gross, as before); 0 means
-- the rule positively states the charge carries none. Mirrors
-- domain/banking/charge_gst.ALLOWED_RATES_BPS — keep the two in step.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.bank_matching_rules'::regclass
      AND conname  = 'bank_matching_rules_gst_rate_bps_check'
  ) THEN
    ALTER TABLE public.bank_matching_rules
      ADD CONSTRAINT bank_matching_rules_gst_rate_bps_check
      CHECK (suggested_gst_rate_bps IS NULL
             OR suggested_gst_rate_bps IN (0, 500, 1200, 1800, 2800));
  END IF;
END $$;

-- A GST rate with nothing to code the taxable value TO is not a usable
-- suggestion: the posting engine needs an expense account for the ex-tax amount
-- and would refuse at post time. Catch it when the rule is written instead —
-- the same reasoning that put a category CHECK on bank_transactions.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.bank_matching_rules'::regclass
      AND conname  = 'bank_matching_rules_gst_needs_account_check'
  ) THEN
    ALTER TABLE public.bank_matching_rules
      ADD CONSTRAINT bank_matching_rules_gst_needs_account_check
      CHECK (suggested_gst_rate_bps IS NULL OR suggested_account_id IS NOT NULL);
  END IF;
END $$;

COMMENT ON COLUMN public.bank_matching_rules.suggested_gst_rate_bps IS
  'GST rate in basis points carried INSIDE a bank charge (1800 = 18%). NULL = the '
  'rule says nothing about GST; 0 = the rule states the charge carries none. '
  'Suggestion only — the CA confirms it in the posting drawer. CGST Act s.16.';
COMMENT ON COLUMN public.bank_matching_rules.suggested_is_interstate IS
  'true when this bank''s supply is inter-state for the client (IGST rather than '
  'CGST+SGST). IGST Act s.12(12): place of supply for banking services is the '
  'recipient''s location. Not inferred — an IFSC does not encode a state.';

COMMIT;
