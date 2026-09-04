-- Rollback for migration 334.
--
-- Dropping these loses the working behind a stored PF figure, not the figure
-- itself: pf_employee_paise and pf_employer_paise are unaffected, so no
-- remittance or ledger entry changes. What is lost is the ability to explain
-- WHY a base differed from basic + DA on any slip written while 334 was live.
ALTER TABLE public.payroll_slips
  DROP COLUMN IF EXISTS pf_wages_paise,
  DROP COLUMN IF EXISTS pf_wages_addback_paise,
  DROP COLUMN IF EXISTS pf_wages_rule_applied;
