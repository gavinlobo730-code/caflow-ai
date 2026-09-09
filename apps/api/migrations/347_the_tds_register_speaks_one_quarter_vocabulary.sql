-- ============================================================================
-- 347 — the TDS register speaks the same quarter vocabulary as the rest of TDS
--
-- WHAT WAS WRONG
--     public.tds_deductions.quarter has held a COMPOUND string since migration
--     014 — 'Q3 2025-26', the quarter and the financial year in one column,
--     which is what that migration's own comment documents. Its three sibling
--     tables do not:
--
--         tds_returns       financial_year TEXT NOT NULL,
--                           quarter TEXT NOT NULL CHECK (quarter IN ('Q1'..'Q4'))
--         tds_challans      same
--         tds_certificates  financial_year NOT NULL, quarter TEXT (nullable —
--                           a Form 16 is annual and has none)
--
--     So every reader written against the schema's own convention missed the
--     register entirely. apps/web/app/tds/returns/page.tsx filters
--     .eq("financial_year", fy).eq("quarter", "Q3"); routers/tds_workspace.py's
--     list_deductions filters .eq("quarter", quarter) from the same vocabulary.
--     Against a register holding 'Q3 2025-26' in `quarter` and NULL in
--     `financial_year` — migration 263 added that column and nothing ever wrote
--     it — both filters match nothing, and the "Prepare a Return" screen
--     reports "No TDS deductions found" whatever the books contain (TDS-03).
--
--     The failure is silent in exactly the way a wrong column name is not:
--     PostgREST answers 200 with an empty array. There is no error to see.
--
-- WHY NORMALISE RATHER THAN TEACH THE READERS THE COMPOUND FORM
--     Three tables against one, and the one is the odd table out. `quarter` and
--     `financial_year` are two facts; holding them in one string means every
--     join to a challan or a return has to parse it, and a challan is joined to
--     a deduction on precisely (financial_year, quarter). Migration 263's own
--     header records that financial_year "was designed in and never created;
--     the reader and the writer were both written against it" — this finishes
--     that job rather than starting a second convention.
--
-- WHAT THIS DOES
--     1. Backfills financial_year for every row that lacks one: from the FY
--        embedded in the compound quarter where there is one, otherwise from
--        transaction_date (NOT NULL on this table since 014), which is the same
--        derivation migration 263's backfill used.
--     2. Rewrites quarter to its bare form.
--     3. Adds the CHECK the siblings carry, so the compound form cannot come
--        back. Nullable is still allowed: form26as_service reads rows it did
--        not write, and 263 chose nullable for that reason.
--
-- BLAST RADIUS
--     Production holds ZERO rows in all four TDS tables (checked 2026-09-09),
--     so the backfill is defensive — it exists so this migration also does the
--     right thing on a developer database that has data, per 263's posture.
--
-- Re-runnable, and the whole file in one transaction so a failure cannot leave
-- the rows rewritten but the constraint unadded.
-- ============================================================================

BEGIN;

-- 1. financial_year, where it is missing.
--    'Q3 2025-26' → '2025-26'. Anything else (already bare, or junk) falls
--    through to the date, which is always right and never null.
UPDATE public.tds_deductions
   SET financial_year = CASE
         WHEN quarter ~ '^Q[1-4] [0-9]{4}-[0-9]{2}$' THEN substring(quarter FROM 4)
         -- The FY runs 1 April to 31 March, so shifting the date back three
         -- months lands it in the calendar year the FY STARTED in — which is
         -- the whole of the arithmetic, and reads as such. Same derivation
         -- migration 263's own backfill used.
         ELSE to_char(transaction_date - INTERVAL '3 months', 'YYYY') || '-'
              || to_char(transaction_date - INTERVAL '3 months'
                                          + INTERVAL '1 year', 'YY')
       END
 WHERE financial_year IS NULL OR btrim(financial_year) = '';

-- 2. quarter, to its bare form. A row whose quarter is already 'Q3' is left
--    alone; a row with something unrecognisable is set to NULL rather than
--    guessed at, because the CHECK below would otherwise refuse the whole
--    migration over one bad string and NULL is a value the column allows.
UPDATE public.tds_deductions
   SET quarter = CASE
         WHEN quarter ~ '^Q[1-4]$'                     THEN quarter
         WHEN quarter ~ '^Q[1-4] [0-9]{4}-[0-9]{2}$'   THEN left(quarter, 2)
         ELSE NULL
       END
 WHERE quarter IS NOT NULL;

-- 3. The constraint its three siblings carry.
ALTER TABLE public.tds_deductions
  DROP CONSTRAINT IF EXISTS tds_deductions_quarter_check;
ALTER TABLE public.tds_deductions
  ADD CONSTRAINT tds_deductions_quarter_check
  CHECK (quarter IS NULL OR quarter IN ('Q1','Q2','Q3','Q4'));

COMMENT ON COLUMN public.tds_deductions.quarter IS
  'The quarter of the financial year, ''Q1''..''Q4'' — Q1 Apr-Jun through Q4 '
  'Jan-Mar. The YEAR lives in financial_year, as it does on tds_returns, '
  'tds_challans and tds_certificates. This column held ''Q3 2025-26'' until '
  'migration 347; see that file for why.';

COMMIT;
