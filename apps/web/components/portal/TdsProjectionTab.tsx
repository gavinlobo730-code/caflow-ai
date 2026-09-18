"use client";

/**
 * The employee's own §192 withholding, month by month (PAY-26).
 *
 * WHY THIS EXISTS
 *   This is the question an employee asks their employer every January: how
 *   much tax is coming out of my salary, and why. The engine has existed since
 *   PAY-10 — `_compute_slip`, the same function the payroll run pays from — and
 *   the employee could not reach it, because the API had no employee principal.
 *   GET /api/portal/employee/tds-projection is that door.
 *
 * THIS COMPONENT DECIDES NOTHING, and here that is not only the CLAUDE.md rule
 * — it is the whole point. A browser copy of the §192 ladder is exactly what
 * PAY-10 deleted: `lib/services/payrollTdsEstimate.ts` had last year's slabs,
 * no old regime, no declaration and no §192(3), so from 1 April it showed a
 * confidently wrong figure. Every number below is the run's own.
 *
 * NO IDS ARE SENT. The endpoint takes a financial year and nothing else; who
 * the caller is comes from their Supabase identity, resolved server-side. So
 * there is no employee id in this file to get wrong, and none to tamper with.
 */
import { useCallback, useEffect, useState } from "react";
import { Loader2, Info, TrendingUp } from "lucide-react";
import { apiGet, getAuthToken } from "@/lib/invoices/shared";
import { formatPaise } from "@/lib/services/formatting";
import { financialYearChoicesAround } from "@/lib/dates/periods";

interface MonthRow {
  month: string;
  actual: boolean;
  gross_paise: number;
  tds_paise: number;
}

interface Projection {
  financial_year: string;
  months: MonthRow[];
  deducted_so_far_paise: number;
  months_paid: number;
  projected_monthly_paise: number;
  projected_monthly_gross_paise: number;
  estimated_annual_tds_paise: number;
  estimated_annual_gross_paise: number;
  gaps: string[];
}

const MONTH_LABEL = (ym: string) => {
  const [y, m] = ym.split("-");
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${names[Number(m) - 1] ?? m} ${y}`;
};

export function TdsProjectionTab({ onToast }: { onToast: (m: string) => void }) {
  // The year list is DERIVED from the clock, never listed — a hardcoded array
  // ends at a year already past, which is the defect
  // scripts/a-financial-year-choice-comes-from-the-clock.test.ts guards.
  const years = financialYearChoicesAround();
  const [fy, setFy] = useState(years[0]);
  const [data, setData] = useState<Projection | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const token = await getAuthToken();
      const res = await apiGet(
        `/api/portal/employee/tds-projection?financial_year=${encodeURIComponent(fy)}`,
        token);
      if (!res.success || !res.data) throw new Error(res.error ?? "Couldn't load your tax working.");
      setData(res.data as Projection);
    } catch (e) {
      setData(null);
      onToast(e instanceof Error ? e.message : "Couldn't load your tax working.");
    } finally {
      setLoading(false);
    }
  }, [fy, onToast]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ps-ink flex items-center gap-2">
            <TrendingUp size={15} className="text-blue-600" />
            Tax deducted from your salary
          </h2>
          <p className="text-2xs text-ps-hint mt-0.5">
            Income-tax Act s.192 · what has been deducted, and what is expected
          </p>
        </div>
        <select value={fy} onChange={(e) => setFy(e.target.value)}
          className="px-2.5 py-1.5 border border-ps-border rounded-lg text-xs bg-white">
          {years.map((y) => <option key={y} value={y}>FY {y}</option>)}
        </select>
      </div>

      {loading && (
        <div className="px-5 py-8 flex justify-center text-ps-hint">
          <Loader2 size={18} className="animate-spin" />
        </div>
      )}

      {!loading && data && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-ps-muted">
            {[
              ["Deducted so far", formatPaise(data.deducted_so_far_paise)],
              ["Months paid", String(data.months_paid)],
              ["Expected each month", formatPaise(data.projected_monthly_paise)],
              ["Expected for the year", formatPaise(data.estimated_annual_tds_paise)],
            ].map(([label, value]) => (
              <div key={label} className="bg-white px-4 py-3">
                <p className="text-2xs text-ps-hint">{label}</p>
                <p className="text-sm font-semibold text-ps-ink tabular-nums mt-0.5">{value}</p>
              </div>
            ))}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-ps-muted text-ps-hint">
                  <th className="px-5 py-2 text-left font-semibold">Month</th>
                  <th className="px-5 py-2 text-right font-semibold">Gross</th>
                  <th className="px-5 py-2 text-right font-semibold">Tax deducted</th>
                  <th className="px-5 py-2 text-left font-semibold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-bg">
                {data.months.map((m) => (
                  <tr key={m.month}>
                    <td className="px-5 py-2 text-ps-ink">{MONTH_LABEL(m.month)}</td>
                    <td className="px-5 py-2 text-right tabular-nums">{formatPaise(m.gross_paise)}</td>
                    <td className="px-5 py-2 text-right tabular-nums">{formatPaise(m.tds_paise)}</td>
                    <td className="px-5 py-2">
                      {/* A PAID month and an EXPECTED one must never look the
                          same: one is what came out of a payslip, the other is
                          an estimate that can still move. */}
                      {m.actual ? (
                        <span className="text-2xs px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700">
                          Paid
                        </span>
                      ) : (
                        <span className="text-2xs px-1.5 py-0.5 rounded bg-ps-muted text-ps-label">
                          Expected
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* The caveats are the server's sentences, rendered where the figures
              are. A projection read without them is taken for a decision. */}
          {data.gaps.length > 0 && (
            <div className="px-5 py-3 border-t border-ps-muted space-y-1.5">
              {data.gaps.map((g, i) => (
                <p key={i} className="text-2xs text-ps-label flex gap-1.5">
                  <Info size={12} className="shrink-0 mt-0.5 text-ps-hint" />
                  <span>{g}</span>
                </p>
              ))}
            </div>
          )}

          <div className="px-5 py-3 border-t border-ps-muted bg-ps-bg">
            <p className="text-2xs text-ps-hint">
              These figures come from the same calculation your payslip is made
              from. If something looks wrong, speak to your employer — a
              declaration you submit changes the months still to come.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
