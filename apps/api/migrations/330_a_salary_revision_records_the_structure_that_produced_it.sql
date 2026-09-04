-- Migration 330: a salary revision records the structure it came from, and the
-- structure's own columns stop saying "% of CTC".
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING
-- ═══════════════════════════════════════════════════════════════════════════
-- public.salary_structures has existed since migration 054 and NO RUN HAS EVER
-- READ IT. A CA could create "Junior — 40/20", see it in the list, and nothing
-- would ever apply it: every employee's basic, HRA and DA are keyed in one by
-- one on the employee master.
--
-- Applying one now writes a payroll_salary_revisions row (migration 300) rather
-- than linking the employee to the structure, and this column records which
-- structure produced the revision.
--
-- WHY A REVISION AND NOT A LIVE LINK
--   The run already reads revisions — _salary_in_force takes the latest one
--   effective on or before the month — so a structure applied from 1 October
--   starts in October and does not restate September, which is posted to the
--   general ledger.
--
--   A live salary_structure_id on the employee would mean editing a structure
--   silently restates every employee on it, including months already in the
--   ledger. Re-applying is an explicit act instead; this column says which
--   structure a revision came from, without making the structure able to reach
--   back and change it.
--
-- NULLABLE, and most rows will stay NULL: a revision keyed in by hand did not
-- come from a structure, and saying so is the honest answer.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- AND THE COMMENTS THAT SAY "% of CTC", WHICH CANNOT BE WHAT THEY MEAN
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 054 comments basic_percent, hra_percent, da_percent, lta_percent
-- and special_percent as percentages "of CTC".
--
-- Read literally with an Indian CTC — which includes the employer's provident
-- fund — the definition is CIRCULAR: the employer's PF is 12% of basic, and
-- basic would be a percentage of a total that includes it. There is no fixed
-- point for arbitrary rates, and nothing in the schema says which of the two
-- readings a CA meant.
--
-- So a structure is applied to a stated MONTHLY GROSS — the figure the employee
-- is told, and the one every downstream computation in this system already
-- starts from. The caller names it; nothing is inferred. The comments are
-- corrected here so the next reader is not misled by them.
--
-- special_percent gets a comment of its own because it CANNOT be honoured
-- alongside a fixed medical_paise:
--
--     gross = gross × (basic + hra + da + lta + special) / 100 + medical
--
-- holds only when the percentages fall short of 100 by exactly medical/gross,
-- which differs per employee. Special allowance is therefore the REMAINDER in
-- paise, which also makes the heads sum to the gross exactly with nothing lost
-- to rounding.
--
-- Comments only for that half — no column is altered, nothing is recomputed,
-- and no stored figure changes.

BEGIN;

ALTER TABLE public.payroll_salary_revisions
  ADD COLUMN IF NOT EXISTS source_structure_id uuid
    REFERENCES public.salary_structures(id) ON DELETE SET NULL;

COMMENT ON COLUMN public.payroll_salary_revisions.source_structure_id IS
    'The salary_structures row this revision was derived from, or NULL when it '
    'was keyed in by hand. Provenance only: the structure cannot reach back and '
    'change a revision, because editing one would otherwise silently restate '
    'every employee on it — including months already posted to the general '
    'ledger. ON DELETE SET NULL, because deleting a template must not delete '
    'somebody''s pay history. Migration 330.';

CREATE INDEX IF NOT EXISTS payroll_salary_revisions_structure_idx
  ON public.payroll_salary_revisions (source_structure_id)
  WHERE source_structure_id IS NOT NULL;

COMMENT ON COLUMN public.salary_structures.basic_percent IS
    'Percentage of MONTHLY GROSS. Migration 054 said "% of CTC", which cannot '
    'be what it means: an Indian CTC includes the employer''s PF, itself 12% of '
    'basic, so basic as a percentage of CTC is circular. The gross is named by '
    'the caller when the structure is applied — nothing infers it.';

COMMENT ON COLUMN public.salary_structures.hra_percent IS
    'Percentage of MONTHLY GROSS — see basic_percent. NOTE the asymmetry: '
    'payroll_employees.hra_percent and payroll_salary_revisions.hra_percent are '
    'percentages of BASIC, so applying a structure converts, and reports the '
    'difference where NUMERIC(5,2) cannot express the result exactly.';

COMMENT ON COLUMN public.salary_structures.da_percent IS
    'Percentage of MONTHLY GROSS — see basic_percent and the asymmetry note on '
    'hra_percent.';

COMMENT ON COLUMN public.salary_structures.lta_percent IS
    'Percentage of MONTHLY GROSS — see basic_percent. Stored on the employee as '
    'an absolute lta_paise, so no conversion is needed.';

COMMENT ON COLUMN public.salary_structures.special_percent IS
    'NOT USED when a structure is applied, and it cannot be: medical_paise is a '
    'fixed rupee amount, so gross = gross x (basic+hra+da+lta+special)/100 + '
    'medical holds only when the percentages fall short of 100 by exactly '
    'medical/gross — which differs per employee. Special allowance is the '
    'REMAINDER in paise, which also makes the heads sum to the gross exactly '
    'with nothing lost to rounding.';

COMMENT ON COLUMN public.salary_structures.medical_paise IS
    'A fixed monthly amount in paise, not a percentage — which is why '
    'special_percent cannot be honoured. See its comment.';

COMMIT;
