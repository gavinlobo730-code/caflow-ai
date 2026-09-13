-- Employer PF and ESI stop hiding inside Salaries Expense (PAY-25).
--
-- WHAT WAS WRONG
--
-- `phase2_journal_service._build_payroll_lines` posted ONE debit for the
-- employer's whole cost of employment: gross wages PLUS the employer's 12% PF,
-- EDLI, the EPF administrative charge and the employer's 3.25% ESI. Its own
-- docstring conceded the design and deferred the split.
--
-- Schedule III to the Companies Act 2013, Division I, Part II requires
-- "Employee Benefits Expense" to be presented as (a) salaries and wages,
-- (b) contribution to provident and other funds, (c) share based payments to
-- employees and (d) staff welfare expenses. One combined debit makes (b) NIL
-- on every payroll client's note and overstates (a) by exactly the employer's
-- contribution — a wrong disclosure, every month, in books this product
-- produces and a CA signs.
--
-- WHY A SEPARATE ACCOUNT AND NOT A REPORTING SPLIT
--
-- The split cannot be derived from the ledger after the fact: once posted, one
-- Salaries Expense debit carries no record of how much of it was contribution,
-- and a posted journal cannot be rewritten (migration 251). It has to be two
-- lines at the moment of posting or it is not recoverable at all.
--
-- WHAT THE ACCOUNT HOLDS
--
-- Employer PF (12%), EDLI (0.5%, EDLI 1976), the EPF administrative charge and
-- employer ESI (3.25%). The administrative CHARGE is strictly a fee to the
-- EPFO rather than a contribution to a fund; it is grouped here because it is
-- remitted on the same monthly challan, is universally presented with PF in
-- Indian statements, and a fourth account for 0.5% of PF wages would be
-- precision nobody asked for. Everything the EMPLOYEE bears — their own PF and
-- ESI, professional tax, s.192 tax, an advance recovered — stays inside gross
-- on the salaries line, because those are deductions FROM pay the employee
-- earned, not a cost on top of it.
--
-- THE SUBTYPE IS LOAD-BEARING. `domain/reporting/schedule_iii.py` buckets an
-- expense whose subtype contains "employee", "salary", "wages" or "staff" into
-- the Employee Benefits Expense caption. "Employee Benefits" therefore lands
-- this account beside 5002 Salaries Expense, so the CAPTION total on the P&L
-- is unchanged by this migration and only the note's sub-split moves. A
-- subtype like "Statutory" would silently relocate the whole employer
-- contribution to another caption.
--
-- THE NAME AVOIDS EVERY EXISTING ILIKE PATTERN. `_find_account` resolves
-- payroll accounts by name alone (no `system_account_key` for these), and its
-- patterns include `%Salaries Expense%`, `%Expense%`, `%PF Payable%` and
-- `%Purchase%`. "Contribution to Provident and Other Funds" matches none of
-- them, and `%Contribution to Provident%` matches nothing else — checked
-- against every pattern in the posting kernel.
--
-- Additive and idempotent: guarded by NOT EXISTS on the name and ON CONFLICT
-- on (firm_id, account_code), so a firm already using 5016 keeps its own
-- account and this does not abort. New firms receive it from
-- coa_seed_service.STANDARD_COA. Mirrors migration 174's 'Round Off' backfill
-- and migration 374's two cess ledgers.
--
-- NOTHING HISTORIC MOVES. Runs already finalised keep their single-line entry;
-- this only changes what the NEXT accrual posts.

INSERT INTO public.chart_of_accounts
  (firm_id, client_id, account_code, account_name, account_type, account_subtype,
   is_active, system_account_key)
-- NULL cast to uuid explicitly: a bare NULL in a SELECT list is typed text,
-- which mismatches the uuid client_id column (migration 174 hit this).
SELECT DISTINCT c.firm_id, NULL::uuid, '5016',
       'Contribution to Provident and Other Funds',
       'Expense', 'Employee Benefits', TRUE, NULL
FROM public.chart_of_accounts c
WHERE c.client_id IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM public.chart_of_accounts r
    WHERE r.firm_id = c.firm_id
      AND r.client_id IS NULL
      AND r.account_name ILIKE '%Contribution to Provident%'
  )
ON CONFLICT ON CONSTRAINT chart_of_accounts_firm_code_unique DO NOTHING;
