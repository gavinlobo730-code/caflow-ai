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
import { formatMonthYear } from "@/lib/dates/format";
import { YearPicker } from "@/components/ui/year-picker";
import { objectWithLists } from "@/lib/api/shape";
import { LoadingRegion } from "@/components/ui/skeleton";

interface MonthRow {
  month: string;
  actual: boolean;
  /** A month before your employer's payroll ran here (POST-A-082): what it paid is in the opening position, in total, so the
   *  month's own figures are null and are shown as a dash, never as a paid nothing. */
  opening?: boolean;
  gross_paise: number | null;
  tds_paise: number | null;
}

interface OpeningPosition {
  first_month_here: string;
  months_paid: number;
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
  opening_position?: OpeningPosition | null;
  gaps: string[];
}

/** A month's own figure, or a dash when the server sent none (a month inside the opening position). */
const monthFigure = (paise: number | null | undefined) => (paise == null ? "—" : formatPaise(paise));

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
      setData(objectWithLists<Projection>(res.data, "gaps", "months"));
    } catch (e) {
      setData(null);
      onToast(e instanceof Error ? e.message : "Couldn't load your tax working.");
    } finally {
      setLoading(false);
    }
  }, [fy, onToast]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
      <div className="px-5 py-4 border-b border-ps-border flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ps-ink flex items-center gap-2">
            <TrendingUp size={15} className="text-blue-600" />
            Tax deducted from your salary
          </h2>
          <p className="text-2xs text-ps-hint mt-0.5">
            Income-tax Act s.192 · what has been deducted, and what is expected
          </p>
        </div>
        <YearPicker value={fy} onChange={setFy} size="sm" className="w-auto" />
      </div>

      {loading && (
        <LoadingRegion label="Loading the projection" noticeClassName="justify-center text-center px-5">
          <div className="px-5 py-8 flex justify-center text-ps-hint">
            <Loader2 size={18} className="animate-spin" />
          </div>
        </LoadingRegion>
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
                <tr className="border-b border-ps-border text-ps-hint">
                  <th className="px-5 py-2 text-left font-semibold">Month</th>
                  <th className="px-5 py-2 text-right font-semibold">Gross</th>
                  <th className="px-5 py-2 text-right font-semibold">Tax deducted</th>
                  <th className="px-5 py-2 text-left font-semibold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-border">
                {data.months.map((m) => (
                  <tr key={m.month}>
                    <td className="px-5 py-2 text-ps-ink">{formatMonthYear(m.month)}</td>
                    <td className="px-5 py-2 text-right tabular-nums">{monthFigure(m.gross_paise)}</td>
                    <td className="px-5 py-2 text-right tabular-nums">{monthFigure(m.tds_paise)}</td>
                    <td className="px-5 py-2">
                      {/* A PAID month and an EXPECTED one must never look the
                          same: one is what came out of a payslip, the other is
                          an estimate that can still move. A month before the
                          payroll ran here is neither: its pay is in the opening
                          position, in total. */}
                      {m.opening ? (
                        <span className="text-2xs px-1.5 py-0.5 rounded bg-ps-muted text-ps-label">
                          Before this payroll (in the opening position)
                        </span>
                      ) : m.actual ? (
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

          {/* The opening position's totals, once, beside the months it covers. */}
          {data.opening_position && (
            <div className="px-5 py-3 border-t border-ps-border">
              <p className="text-2xs text-ps-label">
                Before {formatMonthYear(data.opening_position.first_month_here)} your employer&apos;s payroll was not run
                here. For those {data.opening_position.months_paid} month(s) your employer recorded{" "}
                {formatPaise(data.opening_position.gross_paise)} paid and {formatPaise(data.opening_position.tds_paise)}{" "}
                tax deducted, in total; that is counted in &quot;Deducted so far&quot; and &quot;Months paid&quot; above.
              </p>
            </div>
          )}

          {/* The caveats are the server's sentences, rendered where the figures
              are. A projection read without them is taken for a decision. */}
          {data.gaps.length > 0 && (
            <div className="px-5 py-3 border-t border-ps-border space-y-1.5">
              {data.gaps.map((g, i) => (
                <p key={i} className="text-2xs text-ps-label flex gap-1.5">
                  <Info size={12} className="shrink-0 mt-0.5 text-ps-hint" />
                  <span>{g}</span>
                </p>
              ))}
            </div>
          )}

          <div className="px-5 py-3 border-t border-ps-border bg-ps-bg">
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
