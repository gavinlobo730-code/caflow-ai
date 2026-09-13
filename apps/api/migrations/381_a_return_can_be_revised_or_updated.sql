-- Migration 381: a return of income has THREE kinds, and this table held one.
-- IT-23, fourth limb.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- IT Act 1961 s. 139(1) is the ORIGINAL return, s. 139(5) the REVISED return
-- and s. 139(8A) the UPDATED return (ITR-U). `itr_filings` had no column
-- saying which — so a practice that revises a return, which is an ordinary
-- week's work, had nowhere to record it.
--
-- AND IT COULD NOT HAVE, whatever the code did: migration 319 declares
-- `UNIQUE (firm_id, client_id, financial_year, itr_form)` on this table, so a
-- second return for one client, one year and one form is REJECTED BY THE
-- DATABASE. The revised return has to sit beside the original, not replace
-- it — the original's acknowledgement number and date are fields ON the
-- revised return's own form, and the register has to show both.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS ADDS
-- ═══════════════════════════════════════════════════════════════════════════
-- `return_type`, defaulting to 'original', so every row that already exists
-- reads as what it is and no backfill is needed. `original_filing_id` is the
-- self-reference where the earlier return was prepared here, and
-- `original_acknowledgement_number` / `original_filing_date` are the two
-- fields the FORM carries — required on a revised or updated return and
-- recorded even where the original was filed outside this product, which is
-- the ordinary case for a client who arrives mid-year.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT REPLACES THE UNIQUE, AND WHAT DELIBERATELY DOES NOT
-- ═══════════════════════════════════════════════════════════════════════════
-- ONE ORIGINAL per (firm, client, financial year, form) — the old constraint
-- narrowed to the kind it was really about, as a partial unique index. Every
-- original that satisfies the old constraint satisfies this one, so nothing
-- existing is rejected.
--
-- NO uniqueness on the other two, and that is a decision rather than an
-- omission. s. 139(5) expressly allows a revised return to be revised again,
-- so a count there would be wrong. s. 139(8A) does bar a SECOND updated return
-- for an assessment year — but that bar is about a return FURNISHED, not a
-- draft being prepared, and a database constraint cannot see the difference.
-- `itr_workflow` warns instead, so a CA is told rather than blocked; a
-- constraint that refuses legitimate work is worse than a warning that is
-- occasionally unnecessary.
--
-- Additive. Idempotent. Reversible: 381_..._rollback.sql.

ALTER TABLE public.itr_filings
  -- s. 139(1) | s. 139(5) | s. 139(8A). The default is what every pre-381 row
  -- is, so there is no UPDATE and no window in which a row means nothing.
  ADD COLUMN IF NOT EXISTS return_type text NOT NULL DEFAULT 'original',

  -- The return this one supersedes, WHERE IT WAS PREPARED HERE. Nullable on
  -- purpose: a client who arrives mid-year has an original filed elsewhere,
  -- and refusing to record their revised return would be a rule about our own
  -- history rather than about the Act. ON DELETE SET NULL rather than CASCADE
  -- — deleting a draft original must not delete the revised return that
  -- succeeded it.
  ADD COLUMN IF NOT EXISTS original_filing_id uuid
      REFERENCES public.itr_filings(id) ON DELETE SET NULL,

  -- The two fields the FORM carries. Required by the application on a revised
  -- or updated return, not by a CHECK: the row is created in draft, and a
  -- NOT NULL here would make the column mandatory on every original too.
  ADD COLUMN IF NOT EXISTS original_acknowledgement_number text,
  ADD COLUMN IF NOT EXISTS original_filing_date date;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.itr_filings'::regclass
                   AND conname = 'itr_filings_return_type_check') THEN
    ALTER TABLE public.itr_filings
      ADD CONSTRAINT itr_filings_return_type_check
      CHECK (return_type IN ('original', 'revised', 'updated'));
  END IF;

  -- A return cannot supersede ITSELF. Cheap, and the shape a badly-written
  -- copy-and-edit would produce.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.itr_filings'::regclass
                   AND conname = 'itr_filings_original_is_not_self_check') THEN
    ALTER TABLE public.itr_filings
      ADD CONSTRAINT itr_filings_original_is_not_self_check
      CHECK (original_filing_id IS NULL OR original_filing_id <> id);
  END IF;
END $$;

-- The old constraint, narrowed to originals. Created BEFORE the drop so there
-- is no instant in which two originals could be written.
CREATE UNIQUE INDEX IF NOT EXISTS uq_itr_filings_one_original
    ON public.itr_filings (firm_id, client_id, financial_year, itr_form)
 WHERE return_type = 'original';

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint
             WHERE conrelid = 'public.itr_filings'::regclass
               AND conname = 'itr_filings_firm_id_client_id_financial_year_itr_form_key') THEN
    ALTER TABLE public.itr_filings
      DROP CONSTRAINT itr_filings_firm_id_client_id_financial_year_itr_form_key;
  END IF;
END $$;

-- The register is read per client and year, and a revised return is found by
-- what it supersedes.
CREATE INDEX IF NOT EXISTS idx_itr_filings_original
    ON public.itr_filings (original_filing_id)
 WHERE original_filing_id IS NOT NULL;

COMMENT ON COLUMN public.itr_filings.return_type IS
    'original (s. 139(1)), revised (s. 139(5)) or updated (s. 139(8A), '
    'ITR-U). Defaults to original, which is what every row written before '
    'migration 381 is. uq_itr_filings_one_original allows exactly one '
    'original per client, year and form and any number of the other two — '
    's. 139(5) allows a revised return to be revised again, and s. 139(8A)''s '
    'once-only bar is about a return FURNISHED, which a constraint cannot '
    'see. Migration 381 (IT-23).';
COMMENT ON COLUMN public.itr_filings.original_filing_id IS
    'The return this one supersedes, where it was prepared here. NULL where '
    'the original was filed outside this product — which is the ordinary case '
    'for a client who arrived mid-year, and why the two columns below carry '
    'the receipt details independently. Migration 381.';
COMMENT ON COLUMN public.itr_filings.original_acknowledgement_number IS
    'The earlier return''s receipt number, which s. 139(5) and the ITR-U '
    'utility both require ON THE FORM. Required by the application for a '
    'revised or updated return; nullable in the database because the row is '
    'created in draft. Migration 381.';
COMMENT ON COLUMN public.itr_filings.original_filing_date IS
    'The earlier return''s filing date, the second half of the receipt the '
    'form carries. Migration 381.';
