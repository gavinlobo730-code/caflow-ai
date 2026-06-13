-- 072_salary_slips_view.sql
-- The employee portal payslips tab queries `salary_slips`, but the real table
-- is `payroll_slips` (gross_paise/net_paise, period via run_id -> payroll_runs).
-- This view bridges the two so the portal list and the PDF download endpoint
-- (GET /api/payroll/salary-slips/{id}/pdf) share the same slip id.
--
-- All monetary values remain integer paise — no conversion to float.
-- security_invoker = true ensures the underlying payroll_slips/payroll_runs RLS
-- policies are evaluated against the querying end-user (anon + JWT), not the
-- view owner. See apps/api/SECURITY.md for the tenant-isolation model.

CREATE OR REPLACE VIEW public.salary_slips
WITH (security_invoker = true) AS
SELECT
  ps.id                                          AS id,
  ps.employee_id                                 AS employee_id,
  pr.firm_id                                     AS firm_id,
  pr.client_id                                   AS client_id,
  CAST(split_part(pr.month, '-', 2) AS INT)      AS month,   -- '2026-06' -> 6
  CAST(split_part(pr.month, '-', 1) AS INT)      AS year,    -- '2026-06' -> 2026
  ps.gross_paise                                 AS gross_salary_paise,
  ps.net_paise                                   AS net_salary_paise,
  ps.created_at                                  AS created_at
FROM public.payroll_slips ps
JOIN public.payroll_runs pr ON pr.id = ps.run_id;

GRANT SELECT ON public.salary_slips TO authenticated;
GRANT SELECT ON public.salary_slips TO anon;
