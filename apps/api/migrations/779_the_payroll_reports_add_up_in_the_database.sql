-- 779: the two payroll reports that add up a year's payslips add them up in the database (POST-A-536).
--
-- WHAT WAS WRONG
--   `GET /api/payroll/reports/year-end` answered one row per employee and `GET /api/payroll/runs` one row per run, and each
--   read every payslip of the year to do it (in pages since POST-A-535, so the figures were whole). That is rows in proportion
--   to the payroll, which the reporting rule forbids: a firm-wide year of a hundred clients is tens of requests one after another.
--
-- WHAT THIS ADDS
--   Two functions that return the SUMS, one JSON document each (a document, not a row set, so the database's thousand-row
--   answer cap cannot cut it short). They are SECURITY INVOKER and callable by the API's privileged client alone: a signed-in
--   session holds no privilege on the payroll tables (migration 549) and none on these functions. The run ids the caller may be
--   answered for are given (the route narrows them to the caller's clients first); the firm is asked of the runs, so a run id of
--   another firm adds nothing.
--
--   The Python path in services/payroll_report_service.py is kept for mock mode and for a database without these functions, and
--   tests/test_779_the_payroll_reports_add_up_in_the_database_pg.py runs the same payslips through both and compares them.
--
-- Additive: two functions. Rollback: 779_..._rollback.sql.

CREATE OR REPLACE FUNCTION public.payroll_run_summaries(p_firm uuid, p_run_ids uuid[])
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
  SELECT COALESCE(jsonb_agg(t ORDER BY t.run_id), '[]'::jsonb)
  FROM (
    SELECT s.run_id::text                                                   AS run_id,
           count(*)::bigint                                                 AS slip_count,
           COALESCE(sum(s.gross_paise), 0)::bigint                          AS gross_paise,
           COALESCE(sum(s.net_paise), 0)::bigint                            AS net_paise,
           COALESCE(sum(s.tds_paise), 0)::bigint                            AS tds_paise,
           COALESCE(sum(s.pf_employee_paise), 0)::bigint                    AS pf_employee_paise,
           COALESCE(sum(s.pf_employer_paise), 0)::bigint                    AS pf_employer_paise,
           COALESCE(sum(s.esi_employee_paise), 0)::bigint                   AS esi_employee_paise,
           COALESCE(sum(s.esi_employer_paise), 0)::bigint                   AS esi_employer_paise,
           -- What the slip CARRIED, never a re-derived ceiling test (the module docstring of the service says why).
           count(*) FILTER (WHERE COALESCE(s.pf_employee_paise, 0) > 0)::bigint AS pf_count,
           count(*) FILTER (WHERE COALESCE(s.esi_employee_paise, 0) > 0
                               OR COALESCE(s.esi_employer_paise, 0) > 0)::bigint AS esi_count
    FROM public.payroll_slips s
    JOIN public.payroll_runs r ON r.id = s.run_id
    WHERE r.firm_id = p_firm
      AND s.run_id = ANY (p_run_ids)
    GROUP BY s.run_id
  ) t
$$;

CREATE OR REPLACE FUNCTION public.payroll_year_end_totals(p_firm uuid, p_run_ids uuid[])
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
  SELECT COALESCE(jsonb_agg(t ORDER BY t.employee_id), '[]'::jsonb)
  FROM (
    SELECT s.employee_id::text                                              AS employee_id,
           (e.id IS NOT NULL)                                               AS has_employee,
           e.name, e.pan, e.designation, e.department,
           count(*)::bigint                                                 AS months,
           COALESCE(sum(s.gross_paise), 0)::bigint                          AS gross_paise,
           COALESCE(sum(s.net_paise), 0)::bigint                            AS net_paise,
           COALESCE(sum(s.tds_paise), 0)::bigint                            AS tds_paise,
           COALESCE(sum(s.pt_paise), 0)::bigint                             AS pt_paise,
           COALESCE(sum(s.pf_employee_paise), 0)::bigint                    AS pf_employee_paise,
           COALESCE(sum(s.esi_employee_paise), 0)::bigint                   AS esi_employee_paise
    FROM public.payroll_slips s
    JOIN public.payroll_runs r ON r.id = s.run_id
    LEFT JOIN public.payroll_employees e ON e.id = s.employee_id
    WHERE r.firm_id = p_firm
      AND s.run_id = ANY (p_run_ids)
    GROUP BY s.employee_id, e.id, e.name, e.pan, e.designation, e.department
  ) t
$$;

REVOKE ALL ON FUNCTION public.payroll_run_summaries(uuid, uuid[]) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.payroll_year_end_totals(uuid, uuid[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.payroll_run_summaries(uuid, uuid[]) TO service_role;
GRANT EXECUTE ON FUNCTION public.payroll_year_end_totals(uuid, uuid[]) TO service_role;

COMMENT ON FUNCTION public.payroll_run_summaries(uuid, uuid[]) IS
  'The five figures per payroll run the statutory table shows, summed here and returned as one JSON document (POST-A-536). Service role only.';
COMMENT ON FUNCTION public.payroll_year_end_totals(uuid, uuid[]) IS
  'The year-end pay report, one entry per employee, summed here and returned as one JSON document (POST-A-536). Service role only.';
