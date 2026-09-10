"use client";

/**
 * APPLY A SALARY STRUCTURE TO A ROSTER (PAY-11).
 *
 * public.salary_structures has existed since migration 054 and nothing ever
 * read it. A CA could create "Junior — 40/20", see it listed on the Setup
 * shelf, and still key every employee's basic, HRA and DA in one at a time —
 * which is the job the template exists to remove.
 *
 * THE GROSS IS NAMED, NEVER INFERRED. Migration 054 calls the percentages
 * "% of CTC", which cannot be what they mean: an Indian CTC includes the
 * employer's provident fund, itself 12% of basic, so basic as a percentage of
 * CTC is circular (migration 330). So each employee's monthly gross is typed,
 * and the modal defaults it to their current basic only as a starting point.
 *
 * PREVIEW FIRST, ALWAYS. The server computes every employee, reports every
 * one, and writes nothing when `preview` is set — including the notes that
 * matter most: a two-decimal percentage that cannot express the structure's
 * HRA exactly, and months already released and paid at the old figures, whose
 * difference is arrears rather than a recomputation.
 *
 * ALL OR NOTHING. If the structure does not fit one employee the server
 * refuses the whole request, and this modal shows why rather than applying to
 * the rest — half a roster on the new scale and half on the old, with nothing
 * on screen saying which, is the worse outcome.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ApplyStructureResult } from "@/lib/api";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";

type RosterEmployee = {
  id: string; name: string; basic_paise?: number; status?: string;
};

function fmt(paise?: number | string | null) {
  const p = Number(paise ?? 0);
  return "₹" + Math.floor(p / 100).toLocaleString("en-IN");
}

const FIELD =
  "border border-[#E2E8F0] rounded-lg px-2 py-1.5 text-[12px] outline-none focus:border-blue-400";

export default function ApplyStructureModal({
  structureId, structureName, clientId, employees, onClose, onApplied,
}: {
  structureId: string;
  structureName: string;
  clientId: string;
  employees: RosterEmployee[];
  onClose: () => void;
  onApplied: (message: string) => void;
}) {
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [reason, setReason] = useState("");
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [gross, setGross] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ApplyStructureResult | null>(null);
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);

  // The current basic is a starting point for the gross, not an answer — the
  // two are different things and the CA is the one who knows which.
  useEffect(() => {
    setGross((g) => {
      const next = { ...g };
      for (const e of employees) {
        if (next[e.id] === undefined) {
          next[e.id] = e.basic_paise ? String(Math.floor(e.basic_paise / 100)) : "";
        }
      }
      return next;
    });
  }, [employees]);

  const assignments = useCallback(() =>
    employees
      .filter((e) => picked[e.id])
      .map((e) => ({
        employee_id: e.id,
        monthly_gross_paise: paiseFromRupeeInput(gross[e.id] ?? "") ?? 0,
      })), [employees, picked, gross]);

  async function send(preview: boolean) {
    setBusy(preview ? "preview" : "apply");
    setErr(null); setProblems([]);
    try {
      const res = await api.payroll.applySalaryStructure(structureId, {
        client_id: clientId,
        effective_from: effectiveFrom,
        reason: reason.trim() || undefined,
        preview,
        assignments: assignments(),
      });
      if (!res?.success) throw new Error(res?.error ?? "That did not work.");
      setResult(res.data);
      if (!preview) {
        onApplied(`${structureName} applied to ${res.data.applied} employee(s) `
          + `from ${effectiveFrom}.`);
      }
    } catch (e) {
      // The server refuses the WHOLE request with a per-employee list when the
      // structure does not fit somebody. Surfacing only "422" would leave the
      // CA guessing which employee, which is the reason it refuses whole.
      const message = e instanceof Error ? e.message : "That did not work.";
      const found = message.match(/\[[^\]]*\]/);
      if (found) {
        try {
          const parsed = JSON.parse(found[0]) as string[];
          if (Array.isArray(parsed)) setProblems(parsed);
        } catch { /* not a list — the message below carries it */ }
      }
      setErr(message);
      setResult(null);
    } finally { setBusy(null); }
  }

  const chosen = employees.filter((e) => picked[e.id]).length;
  const missingGross = employees.some(
    (e) => picked[e.id] && (paiseFromRupeeInput(gross[e.id] ?? "") ?? 0) <= 0);
  const ready = effectiveFrom.trim() !== "" && chosen > 0 && !missingGross;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/25 p-4"
      onClick={onClose}>
      <div className="w-full max-w-[720px] max-h-[88vh] overflow-y-auto bg-white rounded-xl shadow-xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 bg-white border-b border-[#E2E8F0] px-5 py-3 flex items-start justify-between gap-3">
          <div>
            <p className="text-[14px] font-semibold text-[#1E293B]">Apply “{structureName}”</p>
            <p className="text-[11px] text-[#94A3B8]">
              Writes a salary revision per employee, effective from the date below.
              Months already released keep the figures they were paid on.
            </p>
          </div>
          <button onClick={onClose}
            className="text-[12px] text-[#64748B] border border-[#E2E8F0] rounded-lg px-2.5 py-1 hover:bg-[#F8FAFC] shrink-0">
            Close
          </button>
        </div>

        <div className="p-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <label className="text-[11px] text-[#64748B] block">Effective from
              <input type="date" value={effectiveFrom}
                onChange={(e) => { setEffectiveFrom(e.target.value); setResult(null); }}
                className={`${FIELD} w-full mt-1`} />
            </label>
            <label className="text-[11px] text-[#64748B] block">Reason
              <input value={reason} onChange={(e) => setReason(e.target.value)}
                placeholder="Annual revision, restructure…"
                className={`${FIELD} w-full mt-1`} />
            </label>
          </div>

          <div className="rounded-xl border border-[#E2E8F0]">
            <div className="px-3 py-2 border-b border-[#F1F5F9] flex items-center justify-between">
              <p className="text-[11px] font-semibold text-[#1E293B]">
                Employees · {chosen} selected
              </p>
              <button
                onClick={() => setPicked(
                  chosen === employees.length
                    ? {}
                    : Object.fromEntries(employees.map((e) => [e.id, true])))}
                className="text-[11px] px-2 py-1 border border-[#E2E8F0] rounded-lg text-[#334155] hover:bg-[#F8FAFC]">
                {chosen === employees.length ? "Clear" : "Select all"}
              </button>
            </div>
            {employees.length === 0 ? (
              <p className="p-4 text-[12px] text-[#94A3B8] text-center">
                This client has no employees to apply a structure to.
              </p>
            ) : (
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-left text-[#64748B] border-b border-[#F1F5F9]">
                    <th className="px-3 py-1.5 w-8"></th>
                    <th className="px-3 py-1.5">Employee</th>
                    <th className="px-3 py-1.5 text-right">Current basic</th>
                    <th className="px-3 py-1.5">Monthly gross to apply</th>
                  </tr>
                </thead>
                <tbody>
                  {employees.map((e) => (
                    <tr key={e.id} className="border-b border-[#F8FAFC]">
                      <td className="px-3 py-1.5">
                        <input type="checkbox" checked={!!picked[e.id]}
                          onChange={(ev) => { setPicked((p) => ({ ...p, [e.id]: ev.target.checked })); setResult(null); }} />
                      </td>
                      <td className="px-3 py-1.5 text-[#1E293B]">{e.name}</td>
                      <td className="px-3 py-1.5 text-right text-[#64748B]">{fmt(e.basic_paise)}</td>
                      <td className="px-3 py-1.5">
                        <input value={gross[e.id] ?? ""} type="text" inputMode="decimal"
                          onChange={(ev) => { setGross((g) => ({ ...g, [e.id]: ev.target.value })); setResult(null); }}
                          disabled={!picked[e.id]}
                          className={`${FIELD} w-32 disabled:opacity-40 ${
                            picked[e.id] && (paiseFromRupeeInput(gross[e.id] ?? "") ?? 0) <= 0
                              ? "border-red-300" : ""}`} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {missingGross && (
            <p className="text-[11px] text-red-600">
              Every selected employee needs a monthly gross — the structure&apos;s
              percentages are of the gross, and it is not inferred from the master.
            </p>
          )}

          {err && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3">
              <p className="text-[11px] font-semibold text-red-700">
                Nothing was changed
              </p>
              {problems.length
                ? problems.map((p, i) => <p key={i} className="text-[11px] text-red-700 mt-0.5">· {p}</p>)
                : <p className="text-[11px] text-red-700 mt-0.5">{err}</p>}
            </div>
          )}

          {result && (
            <div className="space-y-3">
              {!!result.notes?.length && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
                  {result.notes.map((n, i) => (
                    <p key={i} className="text-[11px] text-amber-800">· {n}</p>
                  ))}
                </div>
              )}
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-left text-[#64748B] border-b border-[#E2E8F0]">
                    <th className="py-1.5 pr-2">Employee</th>
                    <th className="py-1.5 pr-2 text-right">Gross</th>
                    <th className="py-1.5 pr-2 text-right">Basic</th>
                    <th className="py-1.5 pr-2 text-right">HRA</th>
                    <th className="py-1.5 text-right">DA</th>
                  </tr>
                </thead>
                <tbody>
                  {result.employees.map((e) => (
                    <tr key={e.employee_id} className="border-b border-[#F1F5F9]">
                      <td className="py-1.5 pr-2 text-[#1E293B]">{e.name ?? e.employee_id}</td>
                      <td className="py-1.5 pr-2 text-right">{fmt(e.monthly_gross_paise)}</td>
                      <td className="py-1.5 pr-2 text-right">{fmt(e.basic_paise as number)}</td>
                      <td className="py-1.5 pr-2 text-right">{fmt(e.hra_paise as number)}</td>
                      <td className="py-1.5 text-right">{fmt(e.da_paise as number)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {result.preview && (
                <p className="text-[11px] text-[#94A3B8]">
                  Nothing has been written. Apply below to record a revision per employee.
                </p>
              )}
              {!result.preview && (
                <p className="text-[12px] px-3 py-2 rounded-lg bg-green-50 text-green-700">
                  Applied to {result.applied} employee(s).
                </p>
              )}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button onClick={() => send(true)} disabled={!ready || busy !== null}
              className="px-3 py-1.5 text-[12px] border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155] disabled:opacity-40">
              {busy === "preview" ? "Computing…" : "Preview"}
            </button>
            {/* Apply is offered only AFTER a preview has come back, so nobody
                writes a revision for a whole roster without having seen it. */}
            <button onClick={() => send(false)}
              disabled={!ready || busy !== null || !result?.preview}
              className="px-3 py-1.5 text-[12px] rounded-lg bg-[#1E293B] text-white disabled:opacity-40">
              {busy === "apply" ? "Applying…" : "Apply"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
