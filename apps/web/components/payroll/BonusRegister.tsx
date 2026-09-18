"use client";

/**
 * The annual statutory bonus register — Payment of Bonus Act 1965 (PAY-23).
 *
 * DECIDES NOTHING. Which employees the Act reaches (§2(13)), who qualifies
 * (§8), who is disqualified (§9), what the calculation base is (§12) and what
 * is payable (§10 with §11) are all `apps/api/domain/payroll/bonus.py` and
 * `bonus_register.py`, served by GET /api/payroll/bonus-register. Every
 * sentence on this screen — the reasons, the gaps, the notes — is the
 * server's.
 *
 * What the CA records here is the part no ledger holds: the employer's own
 * §10/§11 rate from their allocable surplus, §12's minimum wage for the
 * scheduled employment, and any §9 dismissal.
 *
 * NOTHING IS POSTED FROM HERE, and that is the server's decision rather than
 * an omission: the provision is a journal the CA raises, because the rate is
 * their determination and the account is their choice.
 */
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2, RefreshCw, Scale } from "lucide-react";
import { Field, Input, Select } from "@/components/ui/field";
import { api } from "@/lib/api";
import type { BonusRegister as BonusRegisterData } from "@/lib/api";
import { paiseFromRupeeInput, bpsFromPercentInput } from "@/lib/money/rupeeInput";
import { financialYearChoicesAround } from "@/lib/dates/periods";

function rupees(paise: number): string {
  return "₹" + (paise / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}

export function BonusRegisterTab({ clientId }: { clientId: string }) {
  const years = financialYearChoicesAround();
  const [year, setYear] = useState(years[0] ?? "");
  const [data, setData] = useState<BonusRegisterData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  // Initialised from the SERVER on load — never from a literal here. The
  // register always answers with a rate, §10's minimum where nothing is
  // declared, so the statutory figure lives in one place.
  const [rate, setRate] = useState("");
  const [minWage, setMinWage] = useState("");
  const [employment, setEmployment] = useState("");
  const [surplus, setSurplus] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!clientId || !year) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.payroll.bonusRegister({
        client_id: clientId, accounting_year: year,
      });
      if (!res.success) {
        setError(res.error || "Couldn't load the bonus register.");
        setData(null);
        return;
      }
      setData(res.data ?? null);
      const d = res.data?.declaration;
      setRate(((res.data?.rate_bps ?? 0) / 100).toFixed(2));
      setMinWage(d?.minimum_wage_monthly_paise != null
        ? (d.minimum_wage_monthly_paise / 100).toString() : "");
      setEmployment(d?.scheduled_employment ?? "");
      setSurplus(d?.allocable_surplus_paise != null
        ? (d.allocable_surplus_paise / 100).toString() : "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load the bonus register.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [clientId, year]);

  useEffect(() => { void load(); }, [load]);

  async function saveDeclaration() {
    setSaving(true);
    setError(null);
    try {
      const res = await api.payroll.saveBonusDeclaration({
        client_id: clientId,
        accounting_year: year,
        // What was typed, or nothing. The server applies the statutory
        // minimum for a null and confines anything else to the §10-§11 band;
        // a fallback here would be a second copy of 8.33%.
        rate_bps: bpsFromPercentInput(rate),
        allocable_surplus_paise: paiseFromRupeeInput(surplus),
        minimum_wage_monthly_paise: paiseFromRupeeInput(minWage),
        scheduled_employment: employment || null,
      });
      if (!res.success) {
        setError(res.error || "Couldn't record the determination.");
        return;
      }
      setEditing(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't record the determination.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="p-5 space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Scale size={14} className="text-blue-600" />
            <h2 className="text-[13px] font-semibold text-ps-ink">
              Statutory bonus
            </h2>
          </div>
          <p className="text-2xs text-ps-label mt-0.5">
            Payment of Bonus Act 1965 · the minimum is payable whether or not
            there is an allocable surplus
          </p>
        </div>
        <div className="flex items-end gap-2">
          <Field label="Accounting year" htmlFor="bonus-year" size="sm">
            <Select value={year} onChange={(e) => setYear(e.target.value)} size="sm" className="w-auto">
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </Select>
          </Field>
          <button onClick={load}
                  className="p-1.5 mb-0.5 rounded border border-ps-border hover:bg-ps-bg text-ps-label">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-2xs text-red-700">
          {error}
        </div>
      )}

      {loading && !data && (
        <div className="flex items-center gap-2 text-xs text-ps-hint">
          <Loader2 size={12} className="animate-spin" /> Loading…
        </div>
      )}

      {data && (
        <>
          {/* The employer's own determination. */}
          <div className="border border-ps-border rounded-lg bg-white">
            <div className="px-4 py-3 flex items-start justify-between gap-4">
              <div className="min-w-0 space-y-1">
                <p className="text-xs font-semibold text-ps-ink">
                  Rate {(data.rate_bps / 100).toFixed(2)}%
                  {data.rate_is_the_statutory_minimum && (
                    <span className="ml-2 px-1.5 py-0.5 rounded text-3xs bg-slate-100 text-slate-600 border border-slate-200">
                      statutory minimum
                    </span>
                  )}
                </p>
                <p className="text-2xs text-ps-label">
                  Due {data.due_date}
                  {data.minimum_wage_monthly_paise != null && (
                    <> · §12 minimum wage {rupees(data.minimum_wage_monthly_paise)} a month
                      {data.scheduled_employment ? ` (${data.scheduled_employment})` : ""}</>
                  )}
                </p>
              </div>
              <button onClick={() => setEditing((v) => !v)}
                      className="flex-shrink-0 px-2.5 py-1.5 text-xs border border-ps-border rounded-lg hover:bg-ps-bg text-ps-body">
                {editing ? "Cancel" : "Record"}
              </button>
            </div>

            {editing && (
              <div className="border-t border-ps-border px-4 py-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Field label="Rate % (§10 minimum 8.33, §11 maximum 20)" htmlFor="bonus-rate" size="sm">
                  <Input value={rate} onChange={(e) => setRate(e.target.value)} size="sm" />
                </Field>
                <Field label="Allocable surplus ₹ (§§4-7, optional)" htmlFor="bonus-surplus" size="sm">
                  <Input value={surplus} onChange={(e) => setSurplus(e.target.value)} size="sm" />
                </Field>
                <Field label="§12 minimum wage, ₹ a month" htmlFor="bonus-minwage" size="sm">
                  <Input value={minWage} onChange={(e) => setMinWage(e.target.value)} size="sm" />
                </Field>
                <Field label="Scheduled employment" htmlFor="bonus-employment" size="sm">
                  <Input value={employment} onChange={(e) => setEmployment(e.target.value)} size="sm" />
                </Field>
                <div className="sm:col-span-2 flex justify-end">
                  <button onClick={saveDeclaration} disabled={saving}
                          className="px-2.5 py-1.5 text-xs bg-brand-dark text-white rounded-lg hover:bg-brand disabled:opacity-50">
                    {saving ? "Saving…" : "Record"}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Totals. */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              ["Payable", rupees(data.total_payable_paise)],
              ["§10 minimum", rupees(data.total_minimum_paise)],
              ["§11 maximum", rupees(data.total_maximum_paise)],
              ["Employees", `${data.eligible_count} in · ${data.excluded_count} out`],
            ].map(([label, value]) => (
              <div key={label} className="border border-ps-border rounded-lg bg-white px-3 py-2">
                <p className="text-3xs text-ps-hint">{label}</p>
                <p className="text-[13px] font-semibold text-ps-ink tabular-nums">{value}</p>
              </div>
            ))}
          </div>

          {data.gaps.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 space-y-1">
              {data.gaps.map((g, i) => (
                <p key={i} className="text-2xs text-amber-800 flex gap-1.5 leading-relaxed">
                  <AlertTriangle size={12} className="shrink-0 mt-0.5" />
                  <span>{g}</span>
                </p>
              ))}
            </div>
          )}

          <div className="border border-ps-border rounded-lg bg-white overflow-x-auto">
            <table className="w-full text-2xs">
              <thead className="bg-ps-bg text-ps-label">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">Employee</th>
                  <th className="text-right px-3 py-2 font-medium">Basic + DA</th>
                  <th className="text-right px-3 py-2 font-medium">Months</th>
                  <th className="text-right px-3 py-2 font-medium">Days worked</th>
                  <th className="text-right px-3 py-2 font-medium">§12 base</th>
                  <th className="text-right px-3 py-2 font-medium">Payable</th>
                </tr>
              </thead>
              <tbody>
                {data.employees.map((e) => (
                  <tr key={e.employee_id} className="border-t border-ps-muted align-top">
                    <td className="px-3 py-2">
                      <p className="text-ps-ink">{e.employee_name}</p>
                      {[...e.reasons, ...e.gaps].map((r, i) => (
                        <p key={i} className="text-3xs text-ps-hint mt-0.5 leading-relaxed">{r}</p>
                      ))}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{rupees(e.monthly_salary_paise)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{e.months_worked}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {e.working_days == null ? "—" : e.working_days}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {e.eligible ? rupees(e.calculation_base_monthly_paise) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium">
                      {e.eligible ? rupees(e.payable_paise) : "—"}
                    </td>
                  </tr>
                ))}
                {data.employees.length === 0 && (
                  <tr><td colSpan={6} className="px-3 py-6 text-center text-ps-hint">
                    No employees on this client&apos;s payroll master.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="space-y-1">
            {data.notes.map((n, i) => (
              <p key={i} className="text-2xs text-ps-label leading-relaxed">{n}</p>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
