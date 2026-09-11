-- Migration 362: the ITC reversal register holds PERMANENT reversals too.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (INV-06)
-- ═══════════════════════════════════════════════════════════════════════════
-- A CA writes off ₹2,00,000 of damaged stock and ticks "reverse ITC". The GL
-- gets it: `domain/inventory_service.post_stock_writeoff_journal_entry` posts
-- Dr Write-off / Cr GST Input, citing CGST Act §17(5)(h). GSTR-3B Table 4(B)(1)
-- gets NOTHING, because 4(B)(1) is derived from cancelled bills and blocked
-- credit on bill lines, and this register REFUSED a permanent ground:
--
--     CHECK (reason_code IN ('rule_37','rule_37a','section_16_2b',
--                            'section_16_2c','other'))
--
-- with the comment "a permanent reversal (Rule 38/42/43, §17(5)) is Table
-- 4(B)(1) and is derived from the documents, not registered". That is true of
-- a cancelled purchase. It is NOT true of a stock write-off: there is no
-- document to derive it from — the supply happened, the credit was taken, and
-- what changed is that the goods were destroyed.
--
-- So the prepared return claims credit the books have already given back. The
-- books-vs-ledger comparator in gst_return_service flags it as a permanent
-- unexplained difference, which is the symptom rather than the fix, and the
-- electronic credit reversal statement at the portal is designed to surface
-- exactly this mismatch.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY `reclaimable` IS GENERATED AND NOT A FLAG SOMEBODY SETS
-- ═══════════════════════════════════════════════════════════════════════════
-- Whether credit can come back is a property of the GROUND, not a decision:
-- Rule 37 credit returns when the supplier is paid (Rule 37(4)); §17(5)(h)
-- credit never returns at all. A boolean anybody could set is a boolean that
-- can disagree with the reason beside it, and the disagreement would show up
-- as credit re-availed on a return where the Act forbids it.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- AND A PERMANENT REVERSAL CANNOT BE RECLAIMED — ENFORCED ON THE TABLE
-- ═══════════════════════════════════════════════════════════════════════════
-- `record_reclaim` will refuse one too, but the register is written by a
-- service that could grow a second caller, and re-availing a §17(5) reversal
-- is claiming credit the Act permanently denies. A CHECK cannot express it
-- (it needs the parent row), so it is a trigger. Same reasoning as migration
-- 360: the rule belongs to the table, not to whoever happens to be writing.

BEGIN;

ALTER TABLE public.itc_reversal_register
  DROP CONSTRAINT IF EXISTS itc_reversal_register_reason_code_check;

ALTER TABLE public.itc_reversal_register
  ADD CONSTRAINT itc_reversal_register_reason_code_check
  CHECK (reason_code IN (
      -- Reclaimable — Table 4(B)(2), released into 4(D)(1) when the condition
      -- that caused them is met.
      'rule_37', 'rule_37a', 'section_16_2b', 'section_16_2c', 'other',
      -- Permanent — Table 4(B)(1), "absolute in nature and not reclaimable"
      -- (Circular 170/02/2022-GST). Never reach 4(D)(1).
      'section_17_5_h', 'section_17_5_other', 'rule_38', 'rule_42', 'rule_43'
  ));

ALTER TABLE public.itc_reversal_register
  ADD COLUMN IF NOT EXISTS reclaimable boolean
  GENERATED ALWAYS AS (
      reason_code IN ('rule_37', 'rule_37a', 'section_16_2b',
                      'section_16_2c', 'other')
  ) STORED;

COMMENT ON COLUMN public.itc_reversal_register.reclaimable IS
    'Whether the credit can ever come back — Table 4(B)(2) when true, 4(B)(1) '
    'when false. GENERATED from reason_code because it is a property of the '
    'GROUND and not a decision: Rule 37 credit returns when the supplier is '
    'paid, section 17(5)(h) credit never returns. Migration 362 (INV-06).';

CREATE OR REPLACE FUNCTION public.assert_reclaim_releases_a_reclaimable_reversal()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
DECLARE
    v_reason text;
BEGIN
    IF NEW.kind <> 'reclaim' OR NEW.reverses_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT reason_code INTO v_reason
      FROM public.itc_reversal_register
     WHERE id = NEW.reverses_id;

    IF v_reason IS NOT NULL AND v_reason NOT IN (
        'rule_37', 'rule_37a', 'section_16_2b', 'section_16_2c', 'other') THEN
        RAISE EXCEPTION
            'a % reversal is permanent — its credit cannot be reclaimed in '
            'Table 4(D)(1)', v_reason
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END $$;

COMMENT ON FUNCTION public.assert_reclaim_releases_a_reclaimable_reversal() IS
    'A Table 4(D)(1) reclaim may only release a reclaimable reversal. Claiming '
    'back a section 17(5) reversal is claiming credit the Act permanently '
    'denies. Migration 362 (INV-06).';

DROP TRIGGER IF EXISTS itc_reclaim_releases_a_reclaimable_reversal
  ON public.itc_reversal_register;
CREATE TRIGGER itc_reclaim_releases_a_reclaimable_reversal
    BEFORE INSERT OR UPDATE ON public.itc_reversal_register
    FOR EACH ROW
    EXECUTE FUNCTION public.assert_reclaim_releases_a_reclaimable_reversal();

COMMIT;
