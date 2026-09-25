"use client";

/**
 * Capital work-in-progress (FA-11a, migration 397).
 *
 * WHY THIS IS NOT PART OF THE ASSET REGISTER
 *   Because the whole point is that these are not fixed assets. Everything in
 *   the register is depreciated; AS-10 paragraph 20 starts depreciation when
 *   the asset is available for use, which is the date a project here is
 *   capitalised and leaves. Until then it sits on its own Schedule III line
 *   with its own two disclosure schedules.
 *
 * THIS SCREEN DECIDES NOTHING (CLAUDE.md). The four ageing bands and their
 * labels, the two rows, which projects reach the completion schedule and why,
 * and the sentence explaining that work-in-progress is not depreciated — every
 * one is `domain/fixed_assets/cwip.py`'s answer, served by /api/cwip/schedules.
 * In particular the browser does not know that exactly one year falls in the
 * SECOND band, and does not decide that a project with no recorded approval
 * cannot be called overdue.
 */
import { useCallback, useEffect, useState } from "react";
import { Plus, AlertCircle, Info, HardHat, CheckCircle2, PauseCircle, PlayCircle } from "lucide-react";
import { request } from "@/lib/api";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { formatPaise } from "@/lib/services/formatting";
import { todayLocalISO } from "@/lib/dateMath";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Callout } from "@/components/ui/callout";
import { objectWithLists } from "@/lib/api/shape";

interface Project {
  id: string;
  project_code: string | null;
  project_name: string;
  started_on: string;
  approved_cost_paise: number | null;
  status: string;
  incurred_paise: number;
  over_approved_cost: boolean;
}

interface Register { projects: Project[]; does_not_depreciate: string }

interface Schedules {
  ageing: {
    as_of: string;
    bucket_order: string[];
    bucket_labels: Record<string, string>;
    row_order: string[];
    row_labels: Record<string, string>;
    rows: Record<string, Record<string, number>>;
    total_paise: number;
    notes: string[];
  };
  completion_schedule: {
    bucket_labels: Record<string, string>;
    rows: Array<{ project_name: string; reason: string; incurred_paise: number; bucket: string | null }>;
    gaps: string[];
  };
  does_not_depreciate: string;
}

const INPUT = "w-full px-2.5 py-1.5 border border-ps-border rounded-lg text-xs";

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block text-xs">
      <span className="block text-ps-hint mb-1">{label}</span>
      {children}
      {hint && <span className="block text-3xs text-ps-hint mt-1">{hint}</span>}
    </label>
  );
}

function Shell({ title, children, onClose, onSave, saving, error, cta }: {
  title: string; children: React.ReactNode; onClose: () => void;
  onSave: () => void; saving: boolean; error: string; cta: string;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="bg-white rounded-xl w-full max-w-lg shadow-xl">
        <div className="px-5 py-4 border-b border-ps-muted">
          <h3 className="text-sm font-semibold text-ps-ink">{title}</h3>
        </div>
        <div className="px-5 py-4 space-y-3">
          {error && <Callout tone="problem">{error}</Callout>}
          {children}
        </div>
        <div className="px-5 py-3 border-t border-ps-muted flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 rounded-lg border border-ps-border text-xs text-ps-label">
            Cancel
          </button>
          <button onClick={onSave} disabled={saving}
            className="px-3 py-1.5 rounded-lg bg-brand text-white text-xs disabled:opacity-40">
            {cta}
          </button>
        </div>
      </div>
    </div>
  );
}

export function CwipTab({ clientId, asOf, openDoc }:
    { clientId: string; asOf: string;
      /** ACC-22 — the CWIP project a ledger drill-through arrived at. A cost
       *  tranche and a capitalisation both stamp the PROJECT, because that is
       *  the row a CA opens. */
      openDoc?: string | null }) {
  const [register, setRegister] = useState<Register | null>(null);
  const [schedules, setSchedules] = useState<Schedules | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const [costFor, setCostFor] = useState<Project | null>(null);
  const [capitalising, setCapitalising] = useState<Project | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [reg, sch] = await Promise.all([
        request<{ success: boolean; data: Register; error: string | null }>(
          `/api/cwip?client_id=${encodeURIComponent(clientId)}`),
        request<{ success: boolean; data: Schedules; error: string | null }>(
          `/api/cwip/schedules?client_id=${encodeURIComponent(clientId)}&as_of=${asOf}`),
      ]);
      if (!reg.success || !sch.success) throw new Error(reg.error ?? sch.error ?? "Couldn't load.");
      setRegister(objectWithLists<Register>(reg.data, "projects"));
      setSchedules(sch.data);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load capital work-in-progress.");
    } finally {
      setLoading(false);
    }
  }, [clientId, asOf]);

  useEffect(() => { load(); }, [load]);

  async function setStatus(p: Project, status: string) {
    try {
      await request(`/api/cwip/${p.id}/status`, {
        method: "PUT",
        body: JSON.stringify({ client_id: clientId, status, on_date: todayLocalISO() }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't change the status.");
    }
  }

  if (loading) return <TableSkeleton />;
  const ag = schedules?.ageing;
  const cs = schedules?.completion_schedule;

  return (
    <div className="space-y-5">
      {error && (
        <div role="alert" className="bg-state-problem-surface border border-state-problem-border rounded-lg px-3 py-2 text-xs text-state-problem flex gap-2">
          <AlertCircle size={13} className="shrink-0 mt-0.5" /><span>{error}</span>
        </div>
      )}

      {/* The one thing a reader has to know about this whole tab, and it is the
          server's sentence rather than one written here. */}
      {register && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2 text-xs text-blue-900 flex gap-2">
          <Info size={13} className="shrink-0 mt-0.5" />
          <span>{register.does_not_depreciate}</span>
        </div>
      )}

      <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
        <div className="px-5 py-3 border-b border-ps-border flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ps-ink flex items-center gap-2">
            <HardHat size={15} className="text-amber-600" /> Projects under construction
          </h3>
          <button onClick={() => setAdding(true)}
            className="text-xs px-3 py-1.5 rounded-lg bg-brand text-white flex items-center gap-1">
            <Plus size={12} /> New project
          </button>
        </div>
        {register && register.projects.length === 0 ? (
          <p className="px-5 py-6 text-xs text-ps-hint">No projects under construction.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-ps-muted text-ps-hint">
                  <th className="px-5 py-2 text-left font-semibold">Project</th>
                  <th className="px-5 py-2 text-left font-semibold">Started</th>
                  <th className="px-5 py-2 text-right font-semibold">Spent</th>
                  <th className="px-5 py-2 text-right font-semibold">Approved cost</th>
                  <th className="px-5 py-2 text-left font-semibold">Status</th>
                  <th className="px-5 py-2 text-right font-semibold"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-bg">
                {register?.projects?.map((p) => (
                  <tr key={p.id} className={openDoc && p.id === openDoc
                      ? "bg-state-attention-surface ring-2 ring-inset ring-amber-300" : undefined}>
                    <td className="px-5 py-2 text-ps-ink">
                      {p.project_name}
                      {p.project_code && (
                        <span className="ml-1.5 font-mono text-3xs text-ps-hint">{p.project_code}</span>
                      )}
                    </td>
                    <td className="px-5 py-2 text-ps-label">{p.started_on}</td>
                    <td className="px-5 py-2 text-right tabular-nums">{formatPaise(p.incurred_paise)}</td>
                    <td className="px-5 py-2 text-right tabular-nums">
                      {/* "Not recorded" and a figure are different facts: the
                          completion schedule cannot call a project over budget
                          without an original approval, and the server says so. */}
                      {p.approved_cost_paise === null
                        ? <span className="text-ps-hint">Not recorded</span>
                        : <span className={p.over_approved_cost ? "text-red-600 font-medium" : ""}>
                            {formatPaise(p.approved_cost_paise)}
                          </span>}
                    </td>
                    <td className="px-5 py-2">
                      <span className={`text-2xs px-1.5 py-0.5 rounded ${
                        p.status === "capitalised" ? "bg-emerald-50 text-emerald-700"
                        : p.status === "suspended" ? "bg-state-attention-surface text-state-attention"
                        : p.status === "abandoned" ? "bg-ps-muted text-ps-label"
                        : "bg-blue-50 text-blue-700"}`}>
                        {p.status.replace("_", " ")}
                      </span>
                    </td>
                    <td className="px-5 py-2 text-right whitespace-nowrap">
                      {(p.status === "in_progress" || p.status === "suspended") && (
                        <>
                          <button onClick={() => setCostFor(p)}
                            className="text-2xs px-2 py-1 rounded border border-ps-border text-ps-label hover:bg-ps-bg mr-1">
                            Add cost
                          </button>
                          {p.status === "in_progress" ? (
                            <button onClick={() => setStatus(p, "suspended")}
                              title="Suspend — the balance stays in capital work-in-progress"
                              aria-label="Suspend project"
                              className="text-2xs px-2 py-1 rounded border border-ps-border text-ps-label hover:bg-ps-bg mr-1">
                              <PauseCircle size={11} className="inline" />
                            </button>
                          ) : (
                            <button onClick={() => setStatus(p, "in_progress")}
                              aria-label="Resume project"
                              className="text-2xs px-2 py-1 rounded border border-ps-border text-ps-label hover:bg-ps-bg mr-1">
                              <PlayCircle size={11} className="inline" />
                            </button>
                          )}
                          <button onClick={() => setCapitalising(p)}
                            className="text-2xs px-2 py-1 rounded border border-blue-200 text-blue-700 hover:bg-blue-50">
                            <CheckCircle2 size={11} className="inline" /> Capitalise
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {ag && (
        <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
          <div className="px-5 py-3 border-b border-ps-border">
            <h3 className="text-sm font-semibold text-ps-ink">CWIP ageing schedule</h3>
            <p className="text-2xs text-ps-hint mt-0.5">Schedule III, as at {ag.as_of}</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-ps-muted text-ps-hint">
                  <th className="px-5 py-2 text-left font-semibold">Amount in CWIP for a period of</th>
                  {ag.bucket_order.map((b) => (
                    <th key={b} className="px-5 py-2 text-right font-semibold">{ag.bucket_labels[b]}</th>
                  ))}
                  <th className="px-5 py-2 text-right font-semibold">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-bg">
                {ag.row_order.map((r) => (
                  <tr key={r}>
                    <td className="px-5 py-2 text-ps-ink">{ag.row_labels[r]}</td>
                    {ag.bucket_order.map((b) => (
                      <td key={b} className="px-5 py-2 text-right tabular-nums">
                        {formatPaise(ag.rows[r]?.[b] ?? 0)}
                      </td>
                    ))}
                    <td className="px-5 py-2 text-right tabular-nums font-medium">
                      {formatPaise(ag.bucket_order.reduce((t, b) => t + (ag.rows[r]?.[b] ?? 0), 0))}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-ps-border">
                  <td className="px-5 py-2 font-semibold text-ps-ink">Total</td>
                  {ag.bucket_order.map((b) => (
                    <td key={b} className="px-5 py-2 text-right tabular-nums font-semibold">
                      {formatPaise(ag.row_order.reduce((t, r) => t + (ag.rows[r]?.[b] ?? 0), 0))}
                    </td>
                  ))}
                  {/* The grand total is the SERVER's, not a sum of the row
                      sums: it must tie to the capital work-in-progress figure
                      on the balance sheet, and that is the number it ties to. */}
                  <td className="px-5 py-2 text-right tabular-nums font-semibold">
                    {formatPaise(ag.total_paise)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
          {ag.notes.length > 0 && (
            <div className="px-5 py-3 border-t border-ps-muted space-y-1">
              {ag.notes.map((n, i) => <p key={i} className="text-2xs text-ps-label">{n}</p>)}
            </div>
          )}
        </div>
      )}

      {cs && (
        <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
          <div className="px-5 py-3 border-b border-ps-border">
            <h3 className="text-sm font-semibold text-ps-ink">
              Completion schedule — overdue or over budget
            </h3>
          </div>
          {cs.rows.length === 0 ? (
            <p className="px-5 py-4 text-xs text-ps-hint">
              No project is overdue against its approved completion date or over its approved cost.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-ps-muted text-ps-hint">
                    <th className="px-5 py-2 text-left font-semibold">Project</th>
                    <th className="px-5 py-2 text-left font-semibold">Why it is reported</th>
                    <th className="px-5 py-2 text-right font-semibold">Amount</th>
                    <th className="px-5 py-2 text-left font-semibold">To be completed in</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ps-bg">
                  {cs.rows.map((r, i) => (
                    <tr key={i}>
                      <td className="px-5 py-2 text-ps-ink">{r.project_name}</td>
                      <td className="px-5 py-2 text-ps-label">{r.reason}</td>
                      <td className="px-5 py-2 text-right tabular-nums">{formatPaise(r.incurred_paise)}</td>
                      <td className="px-5 py-2">
                        {/* A band nobody stated renders as a gap, never as the
                            longest one — that would assert something false. */}
                        {r.bucket ? cs.bucket_labels[r.bucket]
                          : <span className="text-state-attention">Not stated</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {/* Gaps are ACTIONABLE — nobody can yet tell — and render differently
              from the settled notes above, the same split the RCM panel makes. */}
          {cs.gaps.length > 0 && (
            <div className="px-5 py-3 border-t border-ps-muted bg-state-attention-surface space-y-1">
              {cs.gaps.map((g, i) => <p key={i} className="text-2xs text-amber-900">{g}</p>)}
            </div>
          )}
        </div>
      )}

      {adding && <ProjectModal clientId={clientId} onClose={() => setAdding(false)}
        onSaved={() => { setAdding(false); load(); }} />}
      {costFor && <CostModal clientId={clientId} project={costFor}
        onClose={() => setCostFor(null)} onSaved={() => { setCostFor(null); load(); }} />}
      {capitalising && <CapitaliseModal clientId={clientId} project={capitalising}
        onClose={() => setCapitalising(null)} onSaved={() => { setCapitalising(null); load(); }} />}
    </div>
  );
}

function ProjectModal({ clientId, onClose, onSaved }: {
  clientId: string; onClose: () => void; onSaved: () => void;
}) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [started, setStarted] = useState(todayLocalISO());
  const [approvedDate, setApprovedDate] = useState("");
  const [approvedCost, setApprovedCost] = useState("");
  const [expected, setExpected] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setSaving(true); setError("");
    try {
      await request("/api/cwip", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId, project_name: name.trim(),
          project_code: code.trim() || null, started_on: started,
          approved_completion_date: approvedDate || null,
          approved_cost_paise: paiseFromRupeeInput(approvedCost),
          expected_completion_date: expected || null,
        }),
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the project.");
    } finally { setSaving(false); }
  }

  return (
    <Shell title="New project under construction" onClose={onClose} onSave={save}
      saving={saving} error={error} cta="Create">
      <Field label="Project name">
        <input value={name} onChange={(e) => setName(e.target.value)} className={INPUT} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Reference (optional)">
          <input value={code} onChange={(e) => setCode(e.target.value)} className={INPUT} />
        </Field>
        <Field label="Started on">
          <input type="date" value={started} onChange={(e) => setStarted(e.target.value)} className={INPUT} />
        </Field>
      </div>
      {/* Both OPTIONAL and never defaulted here. The completion schedule
          measures against the ORIGINAL approval, and the server names a project
          with neither rather than reporting it as on track. */}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Approved completion date" hint="As originally approved — blank if there is none">
          <input type="date" value={approvedDate}
            onChange={(e) => setApprovedDate(e.target.value)} className={INPUT} />
        </Field>
        <Field label="Approved cost (₹)" hint="As originally approved">
          <input value={approvedCost} inputMode="decimal"
            onChange={(e) => setApprovedCost(e.target.value)}
            className={`${INPUT} text-right tabular-nums`} />
        </Field>
      </div>
      <Field label="Now expected to complete on" hint="A fresh judgement, not the original promise">
        <input type="date" value={expected} onChange={(e) => setExpected(e.target.value)} className={INPUT} />
      </Field>
    </Shell>
  );
}

function CostModal({ clientId, project, onClose, onSaved }: {
  clientId: string; project: Project; onClose: () => void; onSaved: () => void;
}) {
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [incurred, setIncurred] = useState(todayLocalISO());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    const paise = paiseFromRupeeInput(amount);
    if (!description.trim() || paise === null || paise <= 0) {
      setError("Say what the cost is and what it came to.");
      return;
    }
    setSaving(true); setError("");
    try {
      await request(`/api/cwip/${project.id}/costs`, {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId, incurred_on: incurred,
          description: description.trim(), amount_paise: paise,
        }),
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't record the cost.");
    } finally { setSaving(false); }
  }

  return (
    <Shell title={`Cost on ${project.project_name}`} onClose={onClose} onSave={save}
      saving={saving} error={error} cta="Record">
      <Field label="What it is">
        <input value={description} onChange={(e) => setDescription(e.target.value)}
          placeholder="Contractor running bill" className={INPUT} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Amount (₹)">
          <input value={amount} inputMode="decimal" onChange={(e) => setAmount(e.target.value)}
            className={`${INPUT} text-right tabular-nums`} />
        </Field>
        {/* The date the ageing schedule ages from — the note ages the MONEY,
            so a build begun three years ago whose last bill arrived last month
            has amounts in three bands at once. */}
        <Field label="Incurred on" hint="What the ageing schedule measures from">
          <input type="date" value={incurred} onChange={(e) => setIncurred(e.target.value)} className={INPUT} />
        </Field>
      </div>
    </Shell>
  );
}

function CapitaliseModal({ clientId, project, onClose, onSaved }: {
  clientId: string; project: Project; onClose: () => void; onSaved: () => void;
}) {
  const [readyOn, setReadyOn] = useState(todayLocalISO());
  const [life, setLife] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setSaving(true); setError("");
    try {
      await request(`/api/cwip/${project.id}/capitalise`, {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId, put_to_use_date: readyOn,
          useful_life_years: life ? Number(life) : null,
        }),
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't capitalise the project.");
    } finally { setSaving(false); }
  }

  return (
    <Shell title={`Capitalise ${project.project_name}`} onClose={onClose} onSave={save}
      saving={saving} error={error} cta="Capitalise">
      <p className="text-xs text-ps-label">
        {formatPaise(project.incurred_paise)} accumulated on this project becomes a
        fixed asset. Depreciation starts from the date it became ready for use.
      </p>
      <Field label="Ready for use on" hint="The date depreciation starts — not the date the build began">
        <input type="date" value={readyOn} onChange={(e) => setReadyOn(e.target.value)} className={INPUT} />
      </Field>
      <Field label="Useful life (years, optional)">
        <input value={life} inputMode="numeric" onChange={(e) => setLife(e.target.value)} className={INPUT} />
      </Field>
      <p className="text-2xs text-state-attention">
        This cannot be undone from here — it creates the asset and posts a journal entry.
      </p>
    </Shell>
  );
}
