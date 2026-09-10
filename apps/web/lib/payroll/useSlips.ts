"use client";

/**
 * Payslips for ONE thing — a run, a month, or an employee's year.
 *
 * WHAT THIS REPLACED
 *   /payroll/reports put every run's UUID into a single PostgREST `in.()` and
 *   pulled every payslip the firm had ever produced, on mount, before any tab
 *   was chosen. Its five tabs then each looked at a slice: one run, one month,
 *   one employee's financial year. Not one of them wanted the whole history.
 *
 *   A hundred employees over three years is 3,600 payslips — each carrying
 *   gross, net, every statutory deduction and the employer split — to render a
 *   table of a dozen rows. CLAUDE.md: "What crosses the wire must be
 *   proportional to the size of the ANSWER, not the size of the ledger."
 *
 * WHY A HOOK AND NOT FIVE FETCHES
 *   The five tabs ask five different questions of one endpoint, and the
 *   enrichment — attaching the employee and the run to each slip, which every
 *   tab then reads through `s.run?.month` — has to happen identically in all
 *   of them. Five copies of that is five chances for one tab to join runs
 *   differently and disagree with its neighbour about which month a slip is in.
 *
 *   `null` means "nothing selected yet", and it FETCHES NOTHING rather than
 *   fetching everything. That is the same defect one level up: the server
 *   refuses an unnarrowed request (services/payroll_report_service.
 *   assert_narrowed), and this makes sure the browser never sends one.
 */

import { useEffect, useMemo, useState } from "react";
import { api, type ApiResp } from "@/lib/api";
import type { Employee, PayrollRun, PayrollSlip } from "@/lib/payroll/types";

export type SlipQuery = {
  run_id?: string;
  month?: string;
  employee_id?: string;
  financial_year?: string;
};

/** True when the query names something the server will accept. */
export function isNarrowed(q: SlipQuery | null): q is SlipQuery {
  return !!q && !!(q.run_id || q.month || q.employee_id);
}

export function useSlips(
  query: SlipQuery | null,
  employees: Employee[],
  runs: PayrollRun[],
): { slips: PayrollSlip[]; loading: boolean; error: string | null } {
  const [slips, setSlips] = useState<PayrollSlip[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The query object is rebuilt on every render by its caller, so compare the
  // VALUES — depending on the object identity refetches on every keystroke
  // anywhere on the page.
  const key = useMemo(
    () => isNarrowed(query)
      ? JSON.stringify([query.run_id ?? "", query.month ?? "",
                        query.employee_id ?? "", query.financial_year ?? ""])
      : "",
    [query],
  );

  useEffect(() => {
    if (!key) { setSlips([]); setError(null); return; }
    const [run_id, month, employee_id, financial_year] = JSON.parse(key) as string[];
    let cancelled = false;
    setLoading(true);
    setError(null);
    (api.payroll.slips({
      run_id: run_id || undefined,
      month: month || undefined,
      employee_id: employee_id || undefined,
      financial_year: financial_year || undefined,
    }) as Promise<ApiResp<{ slips: PayrollSlip[] }>>)
      .then(res => {
        if (cancelled) return;
        if (!res.success) throw new Error(res.error || "Could not load payslips");
        setSlips((res.data?.slips ?? []).map(s => ({
          ...s,
          employee: s.employee ?? employees.find(e => e.id === s.employee_id),
          run: runs.find(r => r.id === s.run_id),
        })));
      })
      .catch(e => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Could not load payslips");
        // Cleared, not left stale: a table showing the PREVIOUS selection's
        // rows under the new selection's heading is worse than an empty one.
        setSlips([]);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // employees and runs are lookup tables, not part of the question — including
    // them would refetch when the roster loads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { slips, loading, error };
}
