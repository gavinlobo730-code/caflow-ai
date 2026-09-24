"use client";

/**
 * The three things a CA does on the 3rd of the month (PAY-27).
 *
 *   WHY IS THIS MONTH BIGGER THAN LAST MONTH, AND BY WHOM. The first question
 *   anyone asks, and nothing answered any of it — the CA exported two
 *   registers and diffed them in a spreadsheet.
 *
 *   WHAT DOES EACH DEPARTMENT COST. `department` has been on the employee
 *   master since the module was built and nothing ever grouped by it.
 *
 *   WHO GETS PAID, AND WHO CANNOT BE. `bank_account_no` and `bank_ifsc` have
 *   been collected all along and nothing read them, so the bank file was built
 *   by hand every month.
 *
 * THIS SCREEN DECIDES NOTHING, and four things would be easy to decide here:
 *
 *   WHICH MONTH IS THE BASELINE. The server takes the PRECEDING calendar month
 *   and never reaches past it, and it requires that month's run to be
 *   RELEASED — a draft has paid nobody. Picking a different baseline in the
 *   browser would put a true-looking sentence over real figures.
 *
 *   WHY A FIGURE MOVED. Every component that moved is listed, largest first,
 *   and no single cause is named. A payroll total moves for several reasons at
 *   once and naming the biggest is how a CA stops reading the rest.
 *
 *   WHAT A DEPARTMENT COSTS. Gross plus the EMPLOYER's own contributions,
 *   which are two debits and two accounts (PAY-25). Net pay is not cost.
 *
 *   WHO CAN BE PAID BY TRANSFER. The server holds the row out and says what is
 *   missing; this renders that. It never emits a row with a blank IFSC,
 *   because some banks drop such a row silently and the CA believes everybody
 *   was paid.
 *
 * AND IT MOVES NO MONEY. The CSV is downloaded and uploaded to the firm's own
 * bank by a person, exactly as this product treats a government portal.
 */
import { useCallback, useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Banknote, Building2, Download, Info, TrendingUp } from "lucide-react";
import { api, type PayrollBankAdvice, type PayrollDepartmentCost, type PayrollMonthOnMonth } from "@/lib/api";
import { TableSkeleton } from "@/components/ui/skeleton";
import { formatPaise } from "@/lib/money/format";
import { objectWithLists } from "@/lib/api/shape";

function rupees(paise: number): string {
  const sign = paise < 0 ? "-" : "";
  const abs = Math.abs(paise);
  return `${sign}${formatPaise(abs)}`;
}

/** A movement's own colour, and it is NOT the ready/problem pair. A payroll
 *  that went down is not "good" and one that went up is not "wrong" — either
 *  can be right and either can be an error, which is why the CA is looking. */
function Delta({ paise }: { paise: number }) {
  if (paise === 0) return <span className="text-ps-hint">—</span>;
  const up = paise > 0;
  return (
    <span className={`inline-flex items-center gap-1 font-mono tabular-nums ${
      up ? "text-ps-ink" : "text-ps-body"}`}>
      {up ? <ArrowUp size={11} /> : <ArrowDown size={11} />}
      {rupees(Math.abs(paise))}
    </span>
  );
}

const STATUS_LABEL: Record<string, string> = {
  joined: "Joined",
  left: "Left",
  changed: "Changed",
  unchanged: "Unchanged",
};

export function MonthlyReview({ clientId, month }: { clientId: string; month: string }) {
  const [variance, setVariance] = useState<PayrollMonthOnMonth | null>(null);
  const [departments, setDepartments] = useState<PayrollDepartmentCost | null>(null);
  const [advice, setAdvice] = useState<PayrollBankAdvice | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);

  const load = useCallback(async () => {
    if (!clientId || !month) return;
    setLoading(true);
    setError("");
    const params = { client_id: clientId, month };
    try {
      const [v, d, a] = await Promise.all([
        api.payroll.monthOnMonth(params),
        api.payroll.departmentCost(params),
        api.payroll.bankAdvice(params).catch(() => null),
      ]);
      setVariance(v.success ? objectWithLists<PayrollMonthOnMonth>(v.data, "employees", "notes") : null);
      setDepartments(d.success ? objectWithLists<PayrollDepartmentCost>(d.data, "notes", "rows") : null);
      // A 404 here means no run for the month, which the variance panel
      // already says in its own words — not an error worth a red banner.
      setAdvice(a && a.success ? objectWithLists<PayrollBankAdvice>(a.data, "excluded", "notes", "rows") : null);
    } catch {
      setError("Couldn't load the monthly review — the request failed or timed out.");
    } finally {
      setLoading(false);
    }
  }, [clientId, month]);

  useEffect(() => { load(); }, [load]);

  const download = async () => {
    setDownloading(true);
    try {
      await api.payroll.downloadBankAdvice(clientId, month);
    } catch (e) {
      setError(e instanceof Error ? e.message
        : "Couldn't prepare the bank file.");
    } finally {
      setDownloading(false);
    }
  };

  if (loading) return <TableSkeleton rows={6} />;
  if (error) return <p className="text-xs text-state-problem">{error}</p>;

  return (
    <div className="space-y-4">
      {/* ── Against last month ─────────────────────────────────────────── */}
      <section className="bg-ps-surface border border-ps-border rounded-xl overflow-hidden">
        <div className="px-5 py-3 bg-ps-bg border-b border-ps-border flex items-center gap-2">
          <TrendingUp size={14} className="text-ps-label" />
          <div className="min-w-0">
            <h3 className="font-semibold text-ps-ink text-sm">Against last month</h3>
            <p className="text-xs text-ps-label">
              {variance?.comparable
                ? `${variance.month} against ${variance.prior_month}`
                : "No released run to compare against"}
            </p>
          </div>
          {variance?.comparable && (
            <span className="ml-auto text-sm font-mono tabular-nums text-ps-ink">
              <Delta paise={variance.gross_delta_paise} /> gross
            </span>
          )}
        </div>

        {variance?.comparable ? (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-ps-muted border-b border-ps-muted">
              {[
                { label: "Gross", now: variance.gross_paise, was: variance.prior_gross_paise },
                { label: "Net", now: variance.net_paise, was: variance.prior_net_paise },
              ].map(c => (
                <div key={c.label} className="px-4 py-3">
                  <p className="text-xs text-ps-label">{c.label}</p>
                  <p className="font-mono tabular-nums text-ps-ink text-sm">{rupees(c.now)}</p>
                  <p className="text-xs text-ps-hint font-mono tabular-nums">
                    was {rupees(c.was)}
                  </p>
                </div>
              ))}
              <div className="px-4 py-3">
                <p className="text-xs text-ps-label">Headcount</p>
                <p className="font-mono tabular-nums text-ps-ink text-sm">{variance.headcount}</p>
                <p className="text-xs text-ps-hint font-mono tabular-nums">
                  was {variance.prior_headcount}
                </p>
              </div>
              <div className="px-4 py-3">
                <p className="text-xs text-ps-label">Employees moved</p>
                <p className="font-mono tabular-nums text-ps-ink text-sm">{variance.changed_count}</p>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-ps-label uppercase border-b border-ps-border">
                    <th className="text-left py-2 px-5 font-medium">Employee</th>
                    <th className="text-right py-2 px-2 font-medium">Gross now</th>
                    <th className="text-right py-2 px-2 font-medium">Change</th>
                    <th className="text-left py-2 px-5 font-medium">What moved</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ps-muted">
                  {variance.employees.filter(e => e.status !== "unchanged").map(e => (
                    <tr key={e.employee_id} className="hover:bg-ps-bg align-top">
                      <td className="py-2 px-5 text-ps-ink">
                        {e.name || "(unnamed)"}
                        <span className="block text-ps-hint">{STATUS_LABEL[e.status] ?? e.status}</span>
                      </td>
                      <td className="py-2 px-2 text-right font-mono tabular-nums text-ps-body">
                        {rupees(e.gross_paise)}
                      </td>
                      <td className="py-2 px-2 text-right"><Delta paise={e.gross_delta_paise} /></td>
                      <td className="py-2 px-5 text-ps-label">
                        {/* EVERY component, never one. The server ordered them
                            largest-absolute first and this renders that order. */}
                        {e.moved.length === 0 && e.days_moved.length === 0
                          ? <span className="text-ps-hint">—</span>
                          : (
                            <span className="flex flex-wrap gap-x-3 gap-y-0.5">
                              {e.moved.map(m => (
                                <span key={m.label} className="whitespace-nowrap">
                                  {m.label} <span className="font-mono tabular-nums">
                                    {m.delta_paise > 0 ? "+" : ""}{rupees(m.delta_paise)}
                                  </span>
                                </span>
                              ))}
                              {e.days_moved.map(d => (
                                <span key={d.label} className="whitespace-nowrap text-ps-hint">
                                  {d.label} {d.delta > 0 ? "+" : ""}{d.delta}
                                </span>
                              ))}
                            </span>
                          )}
                        {e.unexplained && (
                          <span className="block text-state-attention mt-0.5">
                            Gross moved with no component behind it.
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {variance.employees.every(e => e.status === "unchanged") && (
                    <tr><td colSpan={4} className="py-3 px-5 text-ps-label">
                      Nobody&apos;s pay moved between these two months.
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        ) : null}

        {(variance?.notes.length ?? 0) > 0 && (
          <div className="px-5 py-3 border-t border-ps-muted bg-ps-bg space-y-1">
            {variance!.notes.map((n, i) => (
              <p key={i} className="text-xs text-ps-label flex gap-2">
                <Info size={12} className="mt-0.5 flex-shrink-0 text-ps-hint" />
                <span>{n}</span>
              </p>
            ))}
          </div>
        )}
      </section>

      {/* ── What each department costs ─────────────────────────────────── */}
      {departments && departments.rows.length > 0 && (
        <section className="bg-ps-surface border border-ps-border rounded-xl overflow-hidden">
          <div className="px-5 py-3 bg-ps-bg border-b border-ps-border flex items-center gap-2">
            <Building2 size={14} className="text-ps-label" />
            <div className="min-w-0">
              <h3 className="font-semibold text-ps-ink text-sm">Cost by department</h3>
              <p className="text-xs text-ps-label">
                Gross plus the employer&apos;s own contributions — two debits, shown apart
              </p>
            </div>
            <span className="ml-auto text-sm font-mono tabular-nums text-ps-ink">
              {rupees(departments.total_cost_paise)}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-ps-label uppercase border-b border-ps-border">
                  <th className="text-left py-2 px-5 font-medium">Department</th>
                  <th className="text-right py-2 px-2 font-medium">Headcount</th>
                  <th className="text-right py-2 px-2 font-medium">Gross</th>
                  <th className="text-right py-2 px-2 font-medium">Employer</th>
                  <th className="text-right py-2 px-5 font-medium">Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-muted">
                {departments.rows.map(r => (
                  <tr key={r.department} className="hover:bg-ps-bg">
                    <td className="py-2 px-5 text-ps-ink">{r.department}</td>
                    <td className="py-2 px-2 text-right font-mono tabular-nums text-ps-body">{r.headcount}</td>
                    <td className="py-2 px-2 text-right font-mono tabular-nums text-ps-body">{rupees(r.gross_paise)}</td>
                    <td className="py-2 px-2 text-right font-mono tabular-nums text-ps-body">{rupees(r.employer_contribution_paise)}</td>
                    <td className="py-2 px-5 text-right font-mono tabular-nums text-ps-ink">{rupees(r.cost_paise)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-ps-border-strong font-medium">
                  <td className="py-2 px-5 text-ps-ink">Total</td>
                  <td className="py-2 px-2 text-right font-mono tabular-nums text-ps-ink">{departments.total_headcount}</td>
                  <td className="py-2 px-2 text-right font-mono tabular-nums text-ps-ink">{rupees(departments.total_gross_paise)}</td>
                  <td className="py-2 px-2 text-right font-mono tabular-nums text-ps-ink">{rupees(departments.total_employer_contribution_paise)}</td>
                  <td className="py-2 px-5 text-right font-mono tabular-nums text-ps-ink">{rupees(departments.total_cost_paise)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
          <div className="px-5 py-3 border-t border-ps-muted bg-ps-bg space-y-1">
            {departments.notes.map((n, i) => (
              <p key={i} className="text-xs text-ps-label flex gap-2">
                <Info size={12} className="mt-0.5 flex-shrink-0 text-ps-hint" />
                <span>{n}</span>
              </p>
            ))}
          </div>
        </section>
      )}

      {/* ── The bank advice ────────────────────────────────────────────── */}
      {advice && (
        <section className="bg-ps-surface border border-ps-border rounded-xl overflow-hidden">
          <div className="px-5 py-3 bg-ps-bg border-b border-ps-border flex items-center gap-2">
            <Banknote size={14} className="text-ps-label" />
            <div className="min-w-0">
              <h3 className="font-semibold text-ps-ink text-sm">Bank payment advice</h3>
              <p className="text-xs text-ps-label">
                {advice.payable_count} employee{advice.payable_count === 1 ? "" : "s"}
                {" · "}{rupees(advice.total_paise)}
              </p>
            </div>
            {advice.payable_count > 0 && (
              <button onClick={download} disabled={downloading}
                className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-ps-border text-ps-body hover:bg-ps-hover disabled:opacity-50">
                <Download size={12} />
                {downloading ? "Preparing…" : "Download CSV"}
              </button>
            )}
          </div>

          {advice.excluded.length > 0 && (
            /* NAMED, NOT COUNTED. Each is a different thing for the CA to go
               and do, and a row held out of a payment file is somebody who
               does not get paid this month. */
            <div className="px-5 py-3 bg-state-attention-surface border-b border-state-attention-border">
              <p className="text-sm font-medium text-state-attention">
                {advice.excluded.length} employee{advice.excluded.length === 1 ? " is" : "s are"} not
                in this file and will not be paid by it
              </p>
              <ul className="mt-2 space-y-1">
                {advice.excluded.map(e => (
                  <li key={e.employee_id} className="text-xs text-ps-body">
                    <span className="font-medium text-ps-ink">{e.name || "(unnamed)"}</span>
                    {" — "}{e.why}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {advice.rows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-ps-label uppercase border-b border-ps-border">
                    <th className="text-left py-2 px-5 font-medium">Beneficiary</th>
                    <th className="text-left py-2 px-2 font-medium">Account</th>
                    <th className="text-left py-2 px-2 font-medium">IFSC</th>
                    <th className="text-right py-2 px-5 font-medium">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ps-muted">
                  {advice.rows.map(r => (
                    <tr key={r.employee_id} className="hover:bg-ps-bg">
                      <td className="py-2 px-5 text-ps-ink">{r.name || "(unnamed)"}</td>
                      {/* MASKED here and whole in the FILE — the CA is checking
                          the name and the amount, not re-typing the account. */}
                      <td className="py-2 px-2 font-mono text-ps-body">{r.account_no_masked}</td>
                      <td className="py-2 px-2 font-mono text-ps-body">{r.ifsc}</td>
                      <td className="py-2 px-5 text-right font-mono tabular-nums text-ps-ink">
                        {rupees(r.net_paise)}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t border-ps-border-strong font-medium">
                    <td className="py-2 px-5 text-ps-ink" colSpan={3}>Total</td>
                    <td className="py-2 px-5 text-right font-mono tabular-nums text-ps-ink">
                      {rupees(advice.total_paise)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}

          <div className="px-5 py-3 border-t border-ps-muted bg-ps-bg space-y-1">
            {advice.notes.map((n, i) => (
              <p key={i} className="text-xs text-ps-label flex gap-2">
                <Info size={12} className="mt-0.5 flex-shrink-0 text-ps-hint" />
                <span>{n}</span>
              </p>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
