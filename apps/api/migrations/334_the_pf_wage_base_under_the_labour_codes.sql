-- Migration 334: store the §2(y) wage base and its add-back on every payslip.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- routers/payroll.py computed `pf_wages = basic + da`, which was EPF Act §6 and
-- was correct until 21 November 2025. On that day the four Labour Codes
-- commenced, the Code on Social Security 2020 subsumed the EPF Act 1952, and it
-- adopts the Code on Wages §2(y) definition of "wages" for computing provident
-- fund: all remuneration, less a listed set of exclusions, with a proviso
-- capping those exclusions at HALF of total remuneration and deeming the excess
-- to be wages.
--
-- Above the ₹15,000 ceiling this changes nothing — min(wages, 15000) makes the
-- add-back moot, and the old figure was already right. BELOW the ceiling it
-- under-stated. On a total of ₹28,000 split ₹10,000 basic / ₹18,000 HRA the
-- exclusions are 64% of total, the excess over half is ₹4,000, wages are
-- ₹14,000 rather than ₹10,000, and employee PF at 12% is ₹1,680 rather than
-- ₹1,200 — ₹480 a month short on EACH side, in somebody's own provident fund,
-- with §7Q interest and §14B damages accruing on the shortfall.
--
-- Verified 2026-09-04; see docs/compliance/04-mca-epfo-esic.md.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY COLUMNS AND NOT A RECOMPUTATION
-- ═══════════════════════════════════════════════════════════════════════════
-- Same reasoning as migrations 295 and 329, and it is the house rule: a figure
-- the ECR and the ledger must agree on is STORED, never recomputed later from
-- inputs that can move. Salary structures are effective-dated and editable; a
-- released payslip has to keep saying what it said. And the add-back cannot be
-- derived back out of pf_wages alone once it is gone — ₹14,000 of wages looks
-- identical whether it was ₹14,000 of basic or ₹10,000 plus a ₹4,000 add-back,
-- and only one of those is a thing a CA needs to explain to a client.
--
-- pf_wages_rule_applied is kept separately from a non-zero add-back because
-- they answer different questions: whether the PERIOD is governed by §2(y), and
-- whether the cap actually bit. The ordinary salary structure is governed and
-- adds back nothing, and conflating the two would hide that common case.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- BACKFILL: DELIBERATELY NONE
-- ═══════════════════════════════════════════════════════════════════════════
-- Existing rows keep NULL for the two amounts and FALSE for the flag. They are
-- not wrong and must not be rewritten:
--
--   * slips for months ending before 21-11-2025 were computed on the correct
--     rule for their period, and §2(y) does not reach them;
--   * slips for later months that were already released carry the figure the
--     employer actually remitted, and a payslip is a record of what happened.
--     Restating one silently would put the ledger, the ECR already filed and
--     the payslip in the employee's hand out of step with each other.
--
-- Correcting an under-remitted past month is a payroll decision with a
-- statutory consequence (§7Q interest, §14B damages, both computed by EPFO
-- itself under the revamped ECR), not a migration. It belongs to the CA.
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE public.payroll_slips
  ADD COLUMN IF NOT EXISTS pf_wages_paise          BIGINT,
  ADD COLUMN IF NOT EXISTS pf_wages_addback_paise  BIGINT,
  ADD COLUMN IF NOT EXISTS pf_wages_rule_applied   BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.payroll_slips.pf_wages_paise IS
  'Code on Wages s.2(y) wage base for PF, before the 15,000 ceiling. NULL on '
  'slips written before migration 334.';
COMMENT ON COLUMN public.payroll_slips.pf_wages_addback_paise IS
  'The excess of s.2(y) exclusions over 50% of total remuneration, deemed to be '
  'wages by the proviso. Zero where the cap did not bite.';
COMMENT ON COLUMN public.payroll_slips.pf_wages_rule_applied IS
  'Whether the payroll month ends on or after 21-11-2025, when the Labour Codes '
  'commenced. False does not mean the cap did not bite - it means s.2(y) did '
  'not govern the period at all.';
