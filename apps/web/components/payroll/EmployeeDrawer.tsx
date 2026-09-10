"use client";

/**
 * THE EMPLOYEE DRAWER — six finished capabilities that had no screen (PAY-11).
 *
 * The payroll roster rendered seven read-only cells and no row action, so an
 * employee could be created and paid and nothing else. Meanwhile the API had,
 * finished and mounted:
 *
 *   POST   /employees/{id}/settlement          the leaver's F&F, computed
 *   POST   /employees/{id}/settlement/record   …and recorded: withheld, posted, closed
 *   GET/POST /employees/{id}/salary-revisions  pay history and a new revision
 *   GET/POST /employees/{id}/loans             an advance recovered through the payslip
 *   POST   /employees/{id}/perquisites/value   Rule 3 valuation
 *   POST   /employees/{id}/arrears-relief      §89(1) relief, Rule 21A(2)
 *
 * docs/audits/2026-09-01-payroll-can-it-run-a-year.md answers its own question
 * "yes for the monthly cycle, the leaver and the statutory returns" — and the
 * leaver and the year-end were not reachable from anywhere in the product.
 *
 * ZERO BUSINESS LOGIC HERE. Every figure below is computed by apps/api and
 * displayed. The only arithmetic in this file is `fmt`, which divides paise by
 * 100 for display, and every typed amount goes through lib/money/rupeeInput.
 *
 * PREVIEW AND RECORD ARE TWO BUTTONS, deliberately. Recording a settlement ends
 * employment, releases money, posts an immutable journal and fixes the
 * employee's §17(1) for the year. It is not a side effect of looking.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type {
  ArrearsReliefResult, EmployeeLoanRow, PerquisiteResult,
  SalaryRevisionRow, SettlementInput, SettlementResult,
} from "@/lib/api";
import { paiseFromRupeeInput, bpsFromPercentInput } from "@/lib/money/rupeeInput";
import { financialYearOfMonth, financialYearChoicesAround } from "@/lib/dates/periods";

export type DrawerEmployee = {
  id: string;
  name: string;
  designation?: string | null;
  department?: string | null;
  status?: string;
  basic_paise?: number;
  joining_date?: string | null;
};

type Section = "settlement" | "revisions" | "loans" | "perquisites" | "relief";

const SECTIONS: { key: Section; label: string; hint: string }[] = [
  { key: "settlement", label: "Full & final",
    hint: "Gratuity, leave encashment, bonus and recoveries — computed, then recorded." },
  { key: "revisions", label: "Salary revisions",
    hint: "The whole component set as at a date. A backdated one gives arrears something to be computed from." },
  { key: "loans", label: "Loans & advances",
    hint: "Recovered through the payslip, after the statutory deductions." },
  { key: "perquisites", label: "Perquisites",
    hint: "§17(2) benefits valued under Rule 3, then recorded for the year." },
  { key: "relief", label: "§89 arrears relief",
    hint: "Rule 21A(2). Needs a Form 10E acknowledgement before relief is available." },
];

function fmt(paise?: number | null) {
  const p = Number(paise ?? 0);
  return "₹" + Math.floor(Math.abs(p) / 100).toLocaleString("en-IN")
    + (p < 0 ? " Cr" : "");
}

const FIELD =
  "border border-[#E2E8F0] rounded-lg px-2 py-1.5 text-[12px] outline-none focus:border-blue-400 w-full";
const LABEL = "text-[11px] text-[#64748B] block";

/** A typed rupee amount, through the one parser. Returns null for anything that
 *  is not an amount — see lib/money/rupeeInput. Never parseFloat. */
function Money({ label, value, onChange, hint }: {
  label: string; value: string; onChange: (v: string) => void; hint?: string;
}) {
  const bad = value.trim() !== "" && paiseFromRupeeInput(value) === null;
  return (
    <label className={LABEL}>
      {label}
      <input value={value} onChange={(e) => onChange(e.target.value)}
        type="text" inputMode="decimal" placeholder="0"
        className={`${FIELD} mt-1 ${bad ? "border-red-300" : ""}`} />
      {bad && <span className="text-[10px] text-red-600">Not an amount.</span>}
      {hint && !bad && <span className="text-[10px] text-[#94A3B8]">{hint}</span>}
    </label>
  );
}

/** Sentences the SERVER composed about what it could not establish. Rendered
 *  verbatim: each names a statute and who holds the missing fact, and
 *  paraphrasing them here would be the business logic this codebase keeps out
 *  of the browser. */
function Notes({ gaps, problems }: { gaps?: string[]; problems?: string[] }) {
  if (!gaps?.length && !problems?.length) return null;
  return (
    <div className="space-y-2">
      {!!problems?.length && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-2.5">
          <p className="text-[11px] font-semibold text-red-700">
            {problems.length} problem{problems.length === 1 ? "" : "s"}
          </p>
          {problems.map((p, i) => <p key={i} className="text-[11px] text-red-700 mt-0.5">· {p}</p>)}
        </div>
      )}
      {!!gaps?.length && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-2.5">
          <p className="text-[11px] font-semibold text-amber-800">
            What payroll cannot know
          </p>
          {gaps.map((g, i) => <p key={i} className="text-[11px] text-amber-800 mt-0.5">· {g}</p>)}
        </div>
      )}
    </div>
  );
}

export default function EmployeeDrawer({ employee, clientId, canFinalize, onClose, onChanged }: {
  employee: DrawerEmployee;
  clientId: string;
  /** payroll:finalize. Recording a settlement posts to the general ledger and
   *  closes the employee, so the button is absent rather than disabled for a
   *  caller who cannot do it — a disabled control invites the question. */
  canFinalize: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [section, setSection] = useState<Section>("settlement");

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/20" onClick={onClose}>
      <div className="w-full max-w-[720px] h-full bg-white shadow-xl overflow-y-auto"
        onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 bg-white border-b border-[#E2E8F0] px-5 py-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[14px] font-semibold text-[#1E293B] truncate">{employee.name}</p>
            <p className="text-[11px] text-[#94A3B8]">
              {[employee.designation, employee.department].filter(Boolean).join(" · ") || "—"}
              {employee.status && employee.status !== "active" ? ` · ${employee.status}` : ""}
            </p>
          </div>
          <button onClick={onClose}
            className="text-[12px] text-[#64748B] border border-[#E2E8F0] rounded-lg px-2.5 py-1 hover:bg-[#F8FAFC] shrink-0">
            Close
          </button>
        </div>

        <div className="px-5 pt-3 flex gap-1.5 flex-wrap border-b border-[#F1F5F9] pb-3">
          {SECTIONS.map((s) => (
            <button key={s.key} onClick={() => setSection(s.key)}
              className={`px-2.5 py-1 text-[12px] rounded-lg border ${
                section === s.key
                  ? "bg-[#1E293B] text-white border-[#1E293B]"
                  : "border-[#E2E8F0] text-[#475569] hover:bg-[#F8FAFC]"}`}>
              {s.label}
            </button>
          ))}
        </div>

        <p className="px-5 pt-3 text-[11px] text-[#94A3B8]">
          {SECTIONS.find((s) => s.key === section)?.hint}
        </p>

        <div className="p-5">
          {section === "settlement" && (
            <SettlementSection employee={employee} clientId={clientId}
              canFinalize={canFinalize} onRecorded={onChanged} />
          )}
          {section === "revisions" && (
            <RevisionsSection employee={employee} clientId={clientId} onSaved={onChanged} />
          )}
          {section === "loans" && (
            <LoansSection employee={employee} clientId={clientId} />
          )}
          {section === "perquisites" && (
            <PerquisitesSection employee={employee} clientId={clientId} />
          )}
          {section === "relief" && (
            <ReliefSection employee={employee} clientId={clientId} />
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Full and final settlement ───────────────────────────────────────────────

function SettlementSection({ employee, clientId, canFinalize, onRecorded }: {
  employee: DrawerEmployee; clientId: string; canFinalize: boolean; onRecorded: () => void;
}) {
  const [leavingDate, setLeavingDate] = useState("");
  const [onRetirement, setOnRetirement] = useState(false);
  const [onDeath, setOnDeath] = useState(false);
  const [isGovernment, setIsGovernment] = useState(false);
  const [salaryToLastDay, setSalaryToLastDay] = useState("");
  const [leaveDays, setLeaveDays] = useState("");
  const [leaveAmount, setLeaveAmount] = useState("");
  const [noticePay, setNoticePay] = useState("");
  const [loansOutstanding, setLoansOutstanding] = useState("");
  const [otherRecoveries, setOtherRecoveries] = useState("");
  const [averageTenMonths, setAverageTenMonths] = useState("");
  const [gratuityUsed, setGratuityUsed] = useState("");
  const [leaveUsed, setLeaveUsed] = useState("");
  const [newStatus, setNewStatus] = useState("resigned");
  const [paymentDate, setPaymentDate] = useState("");

  const [result, setResult] = useState<SettlementResult | null>(null);
  const [busy, setBusy] = useState<"preview" | "record" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  function body(): SettlementInput {
    return {
      client_id: clientId,
      leaving_date: leavingDate,
      on_retirement: onRetirement,
      on_death_or_disablement: onDeath,
      is_government_employee: isGovernment,
      salary_to_last_day_paise: paiseFromRupeeInput(salaryToLastDay) ?? 0,
      leave_days_encashed: Number(leaveDays || 0),
      leave_encashment_paise: paiseFromRupeeInput(leaveAmount) ?? 0,
      notice_pay_recovered_paise: paiseFromRupeeInput(noticePay) ?? 0,
      loans_outstanding_paise: paiseFromRupeeInput(loansOutstanding) ?? 0,
      other_recoveries_paise: paiseFromRupeeInput(otherRecoveries) ?? 0,
      // Absent means "the whole lifetime limit is still available", which the
      // server says out loud. Sending 0 would CLAIM that, which is different.
      average_last_ten_months_paise: paiseFromRupeeInput(averageTenMonths),
      gratuity_exemption_already_used_paise: paiseFromRupeeInput(gratuityUsed),
      leave_exemption_already_used_paise: paiseFromRupeeInput(leaveUsed),
    };
  }

  async function preview() {
    setBusy("preview"); setErr(null); setDone(null); setConfirming(false);
    try {
      const res = await api.payroll.previewSettlement(employee.id, body());
      if (!res?.success) throw new Error(res?.error ?? "That did not compute.");
      setResult(res.data);
    } catch (e) {
      setResult(null);
      setErr(e instanceof Error ? e.message : "That did not compute.");
    } finally { setBusy(null); }
  }

  async function record() {
    setBusy("record"); setErr(null);
    try {
      const res = await api.payroll.recordSettlement(employee.id, {
        ...body(), new_status: newStatus,
        payment_date: paymentDate || undefined,
      });
      if (!res?.success) throw new Error(res?.error ?? "That did not record.");
      setResult(res.data);
      setDone(`Settlement recorded. ${employee.name} is now ${newStatus}, the `
        + "withholding is on the year and the ledger entry is posted.");
      setConfirming(false);
      onRecorded();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "That did not record.");
    } finally { setBusy(null); }
  }

  const canPreview = leavingDate.trim() !== "";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <label className={LABEL}>Last working day
          <input type="date" value={leavingDate} onChange={(e) => setLeavingDate(e.target.value)}
            className={`${FIELD} mt-1`} />
          <span className="text-[10px] text-[#94A3B8]">
            Joined {employee.joining_date || "— not recorded, so gratuity cannot be computed"}.
          </span>
        </label>
        <label className={LABEL}>Recorded as
          <select value={newStatus} onChange={(e) => setNewStatus(e.target.value)}
            className={`${FIELD} mt-1`}>
            <option value="resigned">Resigned</option>
            <option value="retired">Retired</option>
            <option value="terminated">Terminated</option>
            <option value="deceased">Deceased</option>
          </select>
          <span className="text-[10px] text-[#94A3B8]">
            §9 of the Bonus Act turns on dismissal, so this is not cosmetic.
          </span>
        </label>
      </div>

      {/* §10(10AA) is decided ENTIRELY by whether the leave encashment is on
          retirement: on retirement it is exempt up to the limit, otherwise it
          is fully taxable. It is a checkbox because it is a fact, not a
          preference. */}
      <div className="flex flex-wrap gap-4">
        <label className="text-[11px] text-[#475569] flex items-center gap-1.5">
          <input type="checkbox" checked={onRetirement}
            onChange={(e) => setOnRetirement(e.target.checked)} />
          On retirement (decides §10(10AA))
        </label>
        <label className="text-[11px] text-[#475569] flex items-center gap-1.5">
          <input type="checkbox" checked={onDeath}
            onChange={(e) => setOnDeath(e.target.checked)} />
          On death or disablement
        </label>
        <label className="text-[11px] text-[#475569] flex items-center gap-1.5">
          <input type="checkbox" checked={isGovernment}
            onChange={(e) => setIsGovernment(e.target.checked)} />
          Government employee
        </label>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Money label="Salary to the last day" value={salaryToLastDay} onChange={setSalaryToLastDay} />
        <Money label="Leave encashment paid" value={leaveAmount} onChange={setLeaveAmount} />
        <label className={LABEL}>Leave days encashed
          <input value={leaveDays} onChange={(e) => setLeaveDays(e.target.value.replace(/[^0-9]/g, ""))}
            inputMode="numeric" className={`${FIELD} mt-1`} />
        </label>
        <Money label="Average of the last ten months (basic + DA)"
          value={averageTenMonths} onChange={setAverageTenMonths}
          hint="§10(10AA)'s own base. Left blank, the current rate is used and the server says so." />
        <Money label="Notice pay recovered" value={noticePay} onChange={setNoticePay}
          hint="Reduces what is PAID and never reduces §17(1)." />
        <Money label="Loans outstanding" value={loansOutstanding} onChange={setLoansOutstanding} />
        <Money label="Other recoveries" value={otherRecoveries} onChange={setOtherRecoveries} />
        <Money label="Gratuity exemption already used" value={gratuityUsed} onChange={setGratuityUsed}
          hint="§10(10) is a LIFETIME limit across employers." />
        <Money label="Leave exemption already used" value={leaveUsed} onChange={setLeaveUsed}
          hint="§10(10AA) is a LIFETIME limit across employers." />
      </div>

      <div className="flex items-center gap-2">
        <button onClick={preview} disabled={!canPreview || busy !== null}
          className="px-3 py-1.5 text-[12px] border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155] disabled:opacity-40">
          {busy === "preview" ? "Computing…" : "Compute"}
        </button>
        {!canPreview && <span className="text-[11px] text-[#94A3B8]">A last working day first.</span>}
      </div>

      {err && <p className="text-[12px] px-3 py-2 rounded-lg bg-red-50 text-red-600">{err}</p>}
      {done && <p className="text-[12px] px-3 py-2 rounded-lg bg-green-50 text-green-700">{done}</p>}

      {result && (
        <div className="space-y-3">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-left text-[#64748B] border-b border-[#E2E8F0]">
                <th className="py-1.5 pr-2">Component</th>
                <th className="py-1.5 pr-2">Statute</th>
                <th className="py-1.5 pr-2 text-right">Gross</th>
                <th className="py-1.5 pr-2 text-right">Exempt</th>
                <th className="py-1.5 text-right">Taxable</th>
              </tr>
            </thead>
            <tbody>
              {result.components.map((c, i) => (
                <tr key={i} className="border-b border-[#F1F5F9]">
                  <td className="py-1.5 pr-2 text-[#1E293B]">{c.label}</td>
                  <td className="py-1.5 pr-2 text-[#94A3B8]">
                    {c.statute}{c.exempt_section ? ` / ${c.exempt_section}` : ""}
                  </td>
                  <td className="py-1.5 pr-2 text-right">{fmt(c.gross_paise)}</td>
                  <td className="py-1.5 pr-2 text-right">{fmt(c.exempt_paise)}</td>
                  <td className="py-1.5 text-right">{fmt(c.taxable_paise)}</td>
                </tr>
              ))}
              {result.deductions.map((d, i) => (
                <tr key={`d${i}`} className="border-b border-[#F1F5F9] text-[#B45309]">
                  <td className="py-1.5 pr-2">{d.label}</td>
                  <td className="py-1.5 pr-2 text-[#94A3B8]">{d.statute}</td>
                  <td className="py-1.5 pr-2 text-right">− {fmt(d.gross_paise)}</td>
                  <td className="py-1.5 pr-2 text-right">—</td>
                  <td className="py-1.5 text-right">—</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="grid grid-cols-3 gap-3">
            {[["Gross", result.totals.gross_paise],
              ["Taxable under §17(1)", result.totals.taxable_paise],
              ["Net payable", result.totals.net_payable_paise]].map(([label, value]) => (
              <div key={String(label)} className="rounded-lg border border-[#E2E8F0] p-2.5">
                <p className="text-[10px] text-[#94A3B8]">{label}</p>
                <p className="text-[13px] font-semibold text-[#1E293B]">{fmt(Number(value ?? 0))}</p>
              </div>
            ))}
          </div>
          {/* The one thing about a settlement that is easy to get backwards. */}
          <p className="text-[10px] text-[#94A3B8]">
            A recovery reduces what the employer pays and never reduces §17(1) —
            taking notice pay back does not un-earn the salary, so the two figures
            above legitimately differ.
          </p>

          <Notes gaps={result.gaps} problems={result.problems} />

          {canFinalize && !done && (
            <div className="rounded-xl border border-[#E2E8F0] p-3">
              <p className="text-[11px] font-semibold text-[#1E293B]">Record this settlement</p>
              <p className="text-[10px] text-[#94A3B8] mt-1">
                This ends the employment, withholds under §192 against the year, posts
                an immutable journal and closes the employee. It cannot be undone by
                editing — a correction is a reversal.
              </p>
              <div className="mt-2 flex items-end gap-3">
                <label className={LABEL}>Payment date
                  <input type="date" value={paymentDate} onChange={(e) => setPaymentDate(e.target.value)}
                    className={`${FIELD} mt-1`} />
                </label>
                {confirming ? (
                  <>
                    <button onClick={record} disabled={busy !== null}
                      className="px-3 py-1.5 text-[12px] rounded-lg bg-[#B91C1C] text-white disabled:opacity-40">
                      {busy === "record" ? "Recording…" : "Yes, record it"}
                    </button>
                    <button onClick={() => setConfirming(false)}
                      className="px-3 py-1.5 text-[12px] border border-[#E2E8F0] rounded-lg text-[#334155]">
                      Cancel
                    </button>
                  </>
                ) : (
                  <button onClick={() => setConfirming(true)} disabled={busy !== null}
                    className="px-3 py-1.5 text-[12px] rounded-lg bg-[#1E293B] text-white disabled:opacity-40">
                    Record settlement
                  </button>
                )}
              </div>
            </div>
          )}
          {!canFinalize && (
            <p className="text-[11px] text-[#94A3B8]">
              Recording a settlement needs payroll finalise rights. This is the
              computation only.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Salary revisions ────────────────────────────────────────────────────────

function RevisionsSection({ employee, clientId, onSaved }: {
  employee: DrawerEmployee; clientId: string; onSaved: () => void;
}) {
  const [rows, setRows] = useState<SalaryRevisionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [basic, setBasic] = useState("");
  const [hraPercent, setHraPercent] = useState("40");
  const [daPercent, setDaPercent] = useState("0");
  const [lta, setLta] = useState("");
  const [medical, setMedical] = useState("");
  const [special, setSpecial] = useState("");
  const [other, setOther] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.payroll.listSalaryRevisions(employee.id, clientId);
      setRows(res?.data?.revisions ?? []);
    } catch { setRows([]); } finally { setLoading(false); }
  }, [employee.id, clientId]);

  useEffect(() => { load(); }, [load]);

  async function save() {
    setBusy(true); setErr(null);
    try {
      const res = await api.payroll.addSalaryRevision(employee.id, {
        client_id: clientId,
        effective_from: effectiveFrom,
        basic_paise: paiseFromRupeeInput(basic) ?? 0,
        // A PERCENTAGE, not paise — bps/100 back to the percent the router
        // takes, through the one parser rather than parseFloat.
        hra_percent: (bpsFromPercentInput(hraPercent) ?? 0) / 100,
        da_percent: (bpsFromPercentInput(daPercent) ?? 0) / 100,
        lta_paise: paiseFromRupeeInput(lta) ?? 0,
        medical_paise: paiseFromRupeeInput(medical) ?? 0,
        special_allowance_paise: paiseFromRupeeInput(special) ?? 0,
        other_allowances_paise: paiseFromRupeeInput(other) ?? 0,
        reason: reason.trim(),
      });
      if ((res as { success?: boolean })?.success === false) {
        throw new Error((res as { error?: string })?.error ?? "That did not save.");
      }
      setEffectiveFrom(""); setBasic(""); setReason("");
      await load();
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "That did not save.");
    } finally { setBusy(false); }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[#E2E8F0] p-3">
        <p className="text-[11px] font-semibold text-[#1E293B]">New revision</p>
        <p className="text-[10px] text-[#94A3B8] mt-1">
          The WHOLE component set as at the date, not a change to it. Months already
          finalised keep the figures they were paid on; a backdated revision creates a
          difference, and settling it is a separate decision — see §89 relief.
        </p>
        <div className="grid grid-cols-2 gap-3 mt-3">
          <label className={LABEL}>Effective from
            <input type="date" value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)}
              className={`${FIELD} mt-1`} />
          </label>
          <Money label="Basic" value={basic} onChange={setBasic} />
          <label className={LABEL}>HRA %
            <input value={hraPercent} onChange={(e) => setHraPercent(e.target.value)}
              type="text" inputMode="decimal" className={`${FIELD} mt-1`} />
          </label>
          <label className={LABEL}>DA %
            <input value={daPercent} onChange={(e) => setDaPercent(e.target.value)}
              type="text" inputMode="decimal" className={`${FIELD} mt-1`} />
          </label>
          <Money label="LTA" value={lta} onChange={setLta} />
          <Money label="Medical" value={medical} onChange={setMedical} />
          <Money label="Special allowance" value={special} onChange={setSpecial} />
          <Money label="Other allowances" value={other} onChange={setOther} />
          <label className={`${LABEL} col-span-2`}>Reason
            <input value={reason} onChange={(e) => setReason(e.target.value)}
              placeholder="Annual increment, promotion, correction…"
              className={`${FIELD} mt-1`} />
          </label>
        </div>
        {err && <p className="mt-2 text-[12px] px-3 py-2 rounded-lg bg-red-50 text-red-600">{err}</p>}
        <div className="mt-3 flex justify-end">
          <button onClick={save} disabled={busy || !effectiveFrom}
            className="px-3 py-1.5 text-[12px] rounded-lg bg-[#1E293B] text-white disabled:opacity-40">
            {busy ? "Saving…" : "Record revision"}
          </button>
        </div>
      </div>

      {loading ? <p className="text-[12px] text-[#94A3B8]">Loading…</p>
        : rows.length === 0
          ? <p className="text-[12px] text-[#94A3B8]">No revisions recorded. The employee master&apos;s own figures apply.</p>
          : (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-left text-[#64748B] border-b border-[#E2E8F0]">
                  <th className="py-1.5 pr-2">Effective from</th>
                  <th className="py-1.5 pr-2 text-right">Basic</th>
                  <th className="py-1.5 pr-2 text-right">HRA %</th>
                  <th className="py-1.5 pr-2 text-right">DA %</th>
                  <th className="py-1.5">Reason</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-b border-[#F1F5F9]">
                    <td className="py-1.5 pr-2 text-[#1E293B]">{r.effective_from}</td>
                    <td className="py-1.5 pr-2 text-right">{fmt(r.basic_paise)}</td>
                    <td className="py-1.5 pr-2 text-right">{r.hra_percent ?? 0}</td>
                    <td className="py-1.5 pr-2 text-right">{r.da_percent ?? 0}</td>
                    <td className="py-1.5 text-[#64748B]">{r.reason || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
    </div>
  );
}

// ─── Loans and advances ──────────────────────────────────────────────────────

function LoansSection({ employee, clientId }: { employee: DrawerEmployee; clientId: string }) {
  const [rows, setRows] = useState<EmployeeLoanRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [principal, setPrincipal] = useState("");
  const [instalment, setInstalment] = useState("");
  const [ratePercent, setRatePercent] = useState("0");
  const [purpose, setPurpose] = useState("");
  const [startedOn, setStartedOn] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.payroll.listEmployeeLoans(employee.id, clientId);
      setRows(res?.data?.loans ?? []);
    } catch { setRows([]); } finally { setLoading(false); }
  }, [employee.id, clientId]);

  useEffect(() => { load(); }, [load]);

  async function save() {
    setBusy(true); setErr(null); setNotes([]);
    try {
      const res = await api.payroll.addEmployeeLoan(employee.id, {
        client_id: clientId,
        principal_paise: paiseFromRupeeInput(principal) ?? 0,
        monthly_instalment_paise: paiseFromRupeeInput(instalment) ?? 0,
        interest_rate_bps: bpsFromPercentInput(ratePercent) ?? 0,
        purpose: purpose.trim(),
        started_on: startedOn || undefined,
      });
      if (!res?.success) throw new Error(res?.error ?? "That did not save.");
      setNotes(res.data?.notes ?? []);
      setPrincipal(""); setInstalment(""); setPurpose("");
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "That did not save.");
    } finally { setBusy(false); }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[#E2E8F0] p-3">
        <p className="text-[11px] font-semibold text-[#1E293B]">New loan or advance</p>
        <p className="text-[10px] text-[#94A3B8] mt-1">
          Recovered through the payslip AFTER the statutory deductions and only out of
          what is left — PF, ESI, professional tax and TDS are owed to somebody else.
        </p>
        <div className="grid grid-cols-2 gap-3 mt-3">
          <Money label="Principal" value={principal} onChange={setPrincipal} />
          <Money label="Monthly instalment" value={instalment} onChange={setInstalment} />
          <label className={LABEL}>Interest rate %
            <input value={ratePercent} onChange={(e) => setRatePercent(e.target.value)}
              type="text" inputMode="decimal" className={`${FIELD} mt-1`} />
            <span className="text-[10px] text-[#94A3B8]">
              Zero is interest-free — and Rule 3(7)(i) makes the shortfall against the
              SBI rate a perquisite. Recording the recovery does not value it.
            </span>
          </label>
          <label className={LABEL}>Started on
            <input type="date" value={startedOn} onChange={(e) => setStartedOn(e.target.value)}
              className={`${FIELD} mt-1`} />
          </label>
          <label className={`${LABEL} col-span-2`}>Purpose
            <input value={purpose} onChange={(e) => setPurpose(e.target.value)}
              className={`${FIELD} mt-1`} />
          </label>
        </div>
        {err && <p className="mt-2 text-[12px] px-3 py-2 rounded-lg bg-red-50 text-red-600">{err}</p>}
        {!!notes.length && (
          <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5">
            {notes.map((n, i) => <p key={i} className="text-[11px] text-amber-800">· {n}</p>)}
          </div>
        )}
        <div className="mt-3 flex justify-end">
          <button onClick={save} disabled={busy || !principal.trim()}
            className="px-3 py-1.5 text-[12px] rounded-lg bg-[#1E293B] text-white disabled:opacity-40">
            {busy ? "Saving…" : "Record loan"}
          </button>
        </div>
      </div>

      {loading ? <p className="text-[12px] text-[#94A3B8]">Loading…</p>
        : rows.length === 0
          ? <p className="text-[12px] text-[#94A3B8]">No loans or advances recorded.</p>
          : (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-left text-[#64748B] border-b border-[#E2E8F0]">
                  <th className="py-1.5 pr-2">Purpose</th>
                  <th className="py-1.5 pr-2 text-right">Principal</th>
                  <th className="py-1.5 pr-2 text-right">Instalment</th>
                  <th className="py-1.5 pr-2 text-right">Outstanding</th>
                  <th className="py-1.5">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-b border-[#F1F5F9]">
                    <td className="py-1.5 pr-2 text-[#1E293B]">{r.purpose || "—"}</td>
                    <td className="py-1.5 pr-2 text-right">{fmt(r.principal_paise)}</td>
                    <td className="py-1.5 pr-2 text-right">{fmt(r.monthly_instalment_paise)}</td>
                    <td className="py-1.5 pr-2 text-right">{fmt(r.outstanding_paise)}</td>
                    <td className="py-1.5 text-[#64748B]">{r.status || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
    </div>
  );
}

// ─── §17(2) perquisites, Rule 3 ──────────────────────────────────────────────

function PerquisitesSection({ employee, clientId }: {
  employee: DrawerEmployee; clientId: string;
}) {
  const [fy, setFy] = useState(() => financialYearOfMonth(null));
  const [salaryForRule3, setSalaryForRule3] = useState("");
  const [accommodation, setAccommodation] = useState(false);
  const [populationLakh, setPopulationLakh] = useState("40");
  const [employerOwns, setEmployerOwns] = useState(true);
  const [leaseRent, setLeaseRent] = useState("");
  const [rentRecovered, setRentRecovered] = useState("");
  const [motorCar, setMotorCar] = useState(false);
  const [engineLitres, setEngineLitres] = useState("1.4");
  const [withDriver, setWithDriver] = useState(false);
  const [employerBearsRunning, setEmployerBearsRunning] = useState(true);
  const [loan, setLoan] = useState(false);
  const [loanOutstanding, setLoanOutstanding] = useState("");
  const [sbiRatePercent, setSbiRatePercent] = useState("");
  const [loanInterestCharged, setLoanInterestCharged] = useState("");
  const [gifts, setGifts] = useState("");

  const [result, setResult] = useState<PerquisiteResult | null>(null);
  const [busy, setBusy] = useState<"value" | "record" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function value() {
    setBusy("value"); setErr(null); setDone(null);
    try {
      const res = await api.payroll.valuePerquisites(employee.id, {
        client_id: clientId, fy,
        salary_for_rule_3_paise: paiseFromRupeeInput(salaryForRule3) ?? 0,
        accommodation,
        population_lakh: Number(populationLakh || 0),
        employer_owns_accommodation: employerOwns,
        actual_lease_rent_paise: paiseFromRupeeInput(leaseRent) ?? 0,
        rent_recovered_from_employee_paise: paiseFromRupeeInput(rentRecovered) ?? 0,
        motor_car: motorCar,
        engine_litres: Number(engineLitres || 0),
        with_driver: withDriver,
        employer_bears_running_costs: employerBearsRunning,
        loan,
        loan_maximum_outstanding_paise: paiseFromRupeeInput(loanOutstanding) ?? 0,
        // ABSENT, not zero. The SBI rate is published by the bank on the first
        // day of the previous year and cannot be derived; sending 0 would claim
        // the rate is nil, and the server refuses instead of valuing at a guess.
        sbi_rate_bps: sbiRatePercent.trim() === "" ? null : bpsFromPercentInput(sbiRatePercent),
        loan_interest_charged_paise: paiseFromRupeeInput(loanInterestCharged) ?? 0,
        gifts_total_paise: paiseFromRupeeInput(gifts) ?? 0,
      });
      if (!res?.success) throw new Error(res?.error ?? "That did not compute.");
      setResult(res.data);
    } catch (e) {
      setResult(null);
      setErr(e instanceof Error ? e.message : "That did not compute.");
    } finally { setBusy(null); }
  }

  async function record() {
    if (!result?.items?.length) return;
    setBusy("record"); setErr(null);
    try {
      const res = await api.payroll.recordPerquisites(employee.id, {
        client_id: clientId, fy, items: result.items,
      });
      if ((res as { success?: boolean })?.success === false) {
        throw new Error((res as { error?: string })?.error ?? "That did not record.");
      }
      setDone(`Recorded for ${fy}. These reach the employee's Form 16 through `
        + "24Q Annexure II.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "That did not record.");
    } finally { setBusy(null); }
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <label className={LABEL}>Financial year
          <select value={fy} onChange={(e) => { setFy(e.target.value); setResult(null); setDone(null); }}
            className={`${FIELD} mt-1`}>
            {financialYearChoicesAround(null).map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </label>
        <Money label="Salary for Rule 3" value={salaryForRule3} onChange={setSalaryForRule3} />
      </div>

      <details className="rounded-xl border border-[#E2E8F0] p-3">
        <summary className="text-[11px] font-semibold text-[#1E293B] cursor-pointer">
          Rule 3(1) — accommodation
        </summary>
        <label className="text-[11px] text-[#475569] flex items-center gap-1.5 mt-2">
          <input type="checkbox" checked={accommodation}
            onChange={(e) => setAccommodation(e.target.checked)} />
          Accommodation provided
        </label>
        {accommodation && (
          <div className="grid grid-cols-2 gap-3 mt-2">
            <label className={LABEL}>City population (lakh)
              <input value={populationLakh} onChange={(e) => setPopulationLakh(e.target.value.replace(/[^0-9]/g, ""))}
                inputMode="numeric" className={`${FIELD} mt-1`} />
            </label>
            <label className="text-[11px] text-[#475569] flex items-center gap-1.5 mt-5">
              <input type="checkbox" checked={employerOwns}
                onChange={(e) => setEmployerOwns(e.target.checked)} />
              Employer-owned (otherwise leased)
            </label>
            <Money label="Actual lease rent" value={leaseRent} onChange={setLeaseRent} />
            <Money label="Rent recovered from the employee" value={rentRecovered} onChange={setRentRecovered} />
          </div>
        )}
      </details>

      <details className="rounded-xl border border-[#E2E8F0] p-3">
        <summary className="text-[11px] font-semibold text-[#1E293B] cursor-pointer">
          Rule 3(2) — motor car
        </summary>
        <label className="text-[11px] text-[#475569] flex items-center gap-1.5 mt-2">
          <input type="checkbox" checked={motorCar} onChange={(e) => setMotorCar(e.target.checked)} />
          Car provided
        </label>
        {motorCar && (
          <div className="grid grid-cols-2 gap-3 mt-2">
            <label className={LABEL}>Engine capacity (litres)
              <input value={engineLitres} onChange={(e) => setEngineLitres(e.target.value)}
                type="text" inputMode="decimal" className={`${FIELD} mt-1`} />
            </label>
            <div className="flex flex-col gap-1.5 mt-5">
              <label className="text-[11px] text-[#475569] flex items-center gap-1.5">
                <input type="checkbox" checked={employerBearsRunning}
                  onChange={(e) => setEmployerBearsRunning(e.target.checked)} />
                Employer bears running costs
              </label>
              <label className="text-[11px] text-[#475569] flex items-center gap-1.5">
                <input type="checkbox" checked={withDriver}
                  onChange={(e) => setWithDriver(e.target.checked)} />
                With driver
              </label>
            </div>
          </div>
        )}
      </details>

      <details className="rounded-xl border border-[#E2E8F0] p-3">
        <summary className="text-[11px] font-semibold text-[#1E293B] cursor-pointer">
          Rule 3(7)(i) — concessional loan
        </summary>
        <label className="text-[11px] text-[#475569] flex items-center gap-1.5 mt-2">
          <input type="checkbox" checked={loan} onChange={(e) => setLoan(e.target.checked)} />
          Loan provided
        </label>
        {loan && (
          <div className="grid grid-cols-2 gap-3 mt-2">
            <Money label="Maximum monthly outstanding" value={loanOutstanding} onChange={setLoanOutstanding} />
            <label className={LABEL}>SBI rate %
              <input value={sbiRatePercent} onChange={(e) => setSbiRatePercent(e.target.value)}
                type="text" inputMode="decimal" placeholder="leave blank if not known"
                className={`${FIELD} mt-1`} />
              <span className="text-[10px] text-[#94A3B8]">
                Published by SBI on the first day of the previous year. Left blank, the
                loan is refused rather than valued at a guess.
              </span>
            </label>
            <Money label="Interest actually charged" value={loanInterestCharged} onChange={setLoanInterestCharged} />
          </div>
        )}
      </details>

      <Money label="Gifts and vouchers for the year" value={gifts} onChange={setGifts} />

      <div className="flex items-center gap-2">
        <button onClick={value} disabled={busy !== null}
          className="px-3 py-1.5 text-[12px] border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155] disabled:opacity-40">
          {busy === "value" ? "Valuing…" : "Value under Rule 3"}
        </button>
      </div>

      {err && <p className="text-[12px] px-3 py-2 rounded-lg bg-red-50 text-red-600">{err}</p>}
      {done && <p className="text-[12px] px-3 py-2 rounded-lg bg-green-50 text-green-700">{done}</p>}

      {result && (
        <div className="space-y-3">
          {result.items?.length ? (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-left text-[#64748B] border-b border-[#E2E8F0]">
                  <th className="py-1.5 pr-2">Perquisite</th>
                  <th className="py-1.5 pr-2">Rule</th>
                  <th className="py-1.5 text-right">Value</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((i, n) => (
                  <tr key={n} className="border-b border-[#F1F5F9]">
                    <td className="py-1.5 pr-2 text-[#1E293B]">{i.label}
                      {i.note && <span className="block text-[10px] text-[#94A3B8]">{i.note}</span>}</td>
                    <td className="py-1.5 pr-2 text-[#94A3B8]">{i.rule}</td>
                    <td className="py-1.5 text-right">{fmt(i.value_paise)}</td>
                  </tr>
                ))}
                <tr className="font-semibold text-[#1E293B]">
                  <td className="py-1.5 pr-2" colSpan={2}>Total §17(2)</td>
                  <td className="py-1.5 text-right">{fmt(result.total_paise)}</td>
                </tr>
              </tbody>
            </table>
          ) : (
            <p className="text-[12px] text-[#94A3B8]">Nothing valued — no benefit was described.</p>
          )}

          <Notes gaps={result.gaps} />

          {!!result.items?.length && (
            <div className="rounded-xl border border-[#E2E8F0] p-3">
              <p className="text-[11px] font-semibold text-[#1E293B]">Record for {fy}</p>
              <p className="text-[10px] text-[#94A3B8] mt-1">
                Replaces the year&apos;s whole set rather than adding to it — a car
                returned in June must not stay valued for the full year. These reach the
                employee&apos;s Form 16 through 24Q Annexure II.
              </p>
              <div className="mt-2 flex justify-end">
                <button onClick={record} disabled={busy !== null}
                  className="px-3 py-1.5 text-[12px] rounded-lg bg-[#1E293B] text-white disabled:opacity-40">
                  {busy === "record" ? "Recording…" : "Record for the year"}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── §89(1) relief on arrears ────────────────────────────────────────────────

function ReliefSection({ employee, clientId }: { employee: DrawerEmployee; clientId: string }) {
  const [receiptFy, setReceiptFy] = useState(() => financialYearOfMonth(null));
  const [totalIncome, setTotalIncome] = useState("");
  const [useNewRegime, setUseNewRegime] = useState(true);
  const [form10e, setForm10e] = useState("");
  const [slices, setSlices] = useState<{ fy: string; amount: string; income: string }[]>(
    [{ fy: "", amount: "", income: "" }]);
  const [result, setResult] = useState<ArrearsReliefResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function compute() {
    setBusy(true); setErr(null);
    try {
      const res = await api.payroll.arrearsRelief(employee.id, {
        client_id: clientId,
        receipt_fy: receiptFy,
        total_income_receipt_year_paise: paiseFromRupeeInput(totalIncome) ?? 0,
        use_new_regime: useNewRegime,
        // Absent, not empty string: the proviso to §89 with Rule 21AA bars
        // relief without a Form 10E, and the server says so rather than
        // returning a zero that reads as "no relief due".
        form_10e_acknowledgement: form10e.trim() || null,
        arrears: slices
          .filter((s) => s.fy.trim() && s.amount.trim())
          .map((s) => ({
            fy: s.fy.trim(),
            amount_paise: paiseFromRupeeInput(s.amount) ?? 0,
            total_income_that_year_paise: paiseFromRupeeInput(s.income),
          })),
      });
      if (!res?.success) throw new Error(res?.error ?? "That did not compute.");
      setResult(res.data);
    } catch (e) {
      setResult(null);
      setErr(e instanceof Error ? e.message : "That did not compute.");
    } finally { setBusy(false); }
  }

  return (
    <div className="space-y-4">
      <p className="text-[10px] text-[#94A3B8]">
        Salary is taxed in the year of RECEIPT (§15), so a revision backdated three
        years lands three years&apos; arrears in one year and pushes the employee
        through slabs they would never have reached. §89 compares the tax with what
        would have been paid had each instalment fallen in its own year.
      </p>

      <div className="grid grid-cols-2 gap-3">
        <label className={LABEL}>Year of receipt
          <select value={receiptFy} onChange={(e) => setReceiptFy(e.target.value)}
            className={`${FIELD} mt-1`}>
            {financialYearChoicesAround(null).map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </label>
        <Money label="Total income in the year of receipt" value={totalIncome} onChange={setTotalIncome} />
        <label className={LABEL}>Form 10E acknowledgement
          <input value={form10e} onChange={(e) => setForm10e(e.target.value)}
            placeholder="filed on the e-filing portal"
            className={`${FIELD} mt-1`} />
          <span className="text-[10px] text-[#94A3B8]">
            The proviso to §89 with Rule 21AA: no Form 10E, no relief. Nothing here
            files it.
          </span>
        </label>
        <label className="text-[11px] text-[#475569] flex items-center gap-1.5 mt-5">
          <input type="checkbox" checked={useNewRegime}
            onChange={(e) => setUseNewRegime(e.target.checked)} />
          New regime (§115BAC)
        </label>
      </div>

      <div className="rounded-xl border border-[#E2E8F0] p-3">
        <p className="text-[11px] font-semibold text-[#1E293B]">
          Which year each slice of the arrears belongs to
        </p>
        <p className="text-[10px] text-[#94A3B8] mt-1">
          The total income for an earlier year comes off the employee&apos;s own
          return — the employer never held it, so it is asked for rather than assumed.
        </p>
        {slices.map((s, i) => (
          <div key={i} className="grid grid-cols-3 gap-3 mt-2">
            <label className={LABEL}>Financial year
              <input value={s.fy} placeholder="2023-24"
                onChange={(e) => setSlices((v) => v.map((x, n) => n === i ? { ...x, fy: e.target.value } : x))}
                className={`${FIELD} mt-1`} />
            </label>
            <Money label="Arrears for that year" value={s.amount}
              onChange={(val) => setSlices((v) => v.map((x, n) => n === i ? { ...x, amount: val } : x))} />
            <Money label="Total income that year" value={s.income}
              onChange={(val) => setSlices((v) => v.map((x, n) => n === i ? { ...x, income: val } : x))} />
          </div>
        ))}
        <div className="mt-2 flex gap-2">
          <button onClick={() => setSlices((v) => [...v, { fy: "", amount: "", income: "" }])}
            className="px-2.5 py-1 text-[11px] border border-[#E2E8F0] rounded-lg text-[#334155] hover:bg-[#F8FAFC]">
            Add a year
          </button>
          {slices.length > 1 && (
            <button onClick={() => setSlices((v) => v.slice(0, -1))}
              className="px-2.5 py-1 text-[11px] border border-[#E2E8F0] rounded-lg text-[#334155] hover:bg-[#F8FAFC]">
              Remove the last
            </button>
          )}
        </div>
      </div>

      <button onClick={compute} disabled={busy}
        className="px-3 py-1.5 text-[12px] border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155] disabled:opacity-40">
        {busy ? "Computing…" : "Compute §89 relief"}
      </button>

      {err && <p className="text-[12px] px-3 py-2 rounded-lg bg-red-50 text-red-600">{err}</p>}

      {result && (
        <div className="space-y-3">
          {/* NOT AVAILABLE IS AN ANSWER WITH A REASON, and it must not read as
              "nil relief due": no Form 10E, or a year whose statutory rates the
              registry does not hold. §89 compares years AT THEIR OWN RATES, so
              a substituted year makes the whole relief a plausible fiction. */}
          {result.available === false ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
              <p className="text-[11px] font-semibold text-amber-800">Relief is not available</p>
              <p className="text-[11px] text-amber-800 mt-1">
                {result.blocked_reason || "The server did not say why."}
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-3">
              {[["Tax with the arrears", result.tax_with_arrears_paise],
                ["Tax spread over the years", result.tax_without_arrears_paise],
                ["§89 relief", result.relief_paise]].map(([label, v]) => (
                <div key={String(label)} className="rounded-lg border border-[#E2E8F0] p-2.5">
                  <p className="text-[10px] text-[#94A3B8]">{label}</p>
                  <p className="text-[13px] font-semibold text-[#1E293B]">{fmt(Number(v ?? 0))}</p>
                </div>
              ))}
            </div>
          )}
          <Notes gaps={result.gaps} />
        </div>
      )}
    </div>
  );
}
