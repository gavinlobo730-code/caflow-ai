"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { ShieldCheck, RefreshCw, Bell, PlayCircle, AlertTriangle, CalendarClock } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { PartnerGuard } from "@/components/practice/PartnerGuard";

// Compliance lifecycle (mirrors the server-side VALID_TRANSITIONS — presentation
// only; the backend is the source of truth and rejects invalid transitions).
const NEXT_STATUS: Record<string, string[]> = {
  "Not Started": ["Awaiting Documents", "In Progress"],
  "Awaiting Documents": ["In Progress"],
  "In Progress": ["Ready For Review", "Awaiting Documents"],
  "Ready For Review": ["Ready To File", "In Progress"],
  "Ready To File": ["Filed"],
  "Filed": ["Completed"],
  "Completed": [],
  "Overdue": ["In Progress", "Awaiting Documents"],
};
const STATUS_BADGE: Record<string, string> = {
  "Not Started": "bg-gray-100 text-gray-600",
  "Awaiting Documents": "bg-amber-50 text-amber-700",
  "In Progress": "bg-blue-50 text-blue-700",
  "Ready For Review": "bg-indigo-50 text-indigo-700",
  "Ready To File": "bg-violet-50 text-violet-700",
  "Filed": "bg-green-50 text-green-700",
  "Completed": "bg-emerald-50 text-emerald-700",
  "Overdue": "bg-red-50 text-red-700",
};

interface Obligation {
  id: string; client_id: string; compliance_type: string; obligation_type?: string | null;
  period_label?: string; due_date: string; status: string;
  preparer_id?: string | null; reviewer_id?: string | null; approver_id?: string | null;
  risk_score?: number;
}
interface WorkloadRow { key: string; obligations: number; overdue: number }
interface Dashboard {
  summary: { total_obligations: number; open_obligations: number; due_this_week: number; due_this_month: number; overdue: number };
  by_staff: WorkloadRow[];
  by_client: WorkloadRow[];
  queue: Obligation[];
}

function ComplianceDashboard() {
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const d = await api.complianceOps.dashboard() as ApiResp<Dashboard>;
      setDash(d.data);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load compliance dashboard"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function act(fn: () => Promise<unknown>, okMsg: (r: unknown) => string) {
    setBusy(true); setMsg(null);
    try { const r = await fn(); setMsg(okMsg(r)); await load(); }
    catch (e) { setMsg(e instanceof Error ? e.message : "Action failed"); }
    finally { setBusy(false); }
  }

  async function transition(o: Obligation, status: string) {
    await act(() => api.complianceOps.transition(o.id, status),
      () => `${o.obligation_type ?? o.compliance_type} → ${status}`);
  }

  const today = new Date().toISOString().slice(0, 10);
  const queue = useMemo(() => {
    const rows = dash?.queue ?? [];
    return rows.filter((o) => {
      if (statusFilter !== "all" && o.status !== statusFilter) return false;
      if (typeFilter !== "all" && o.compliance_type !== typeFilter) return false;
      return true;
    }).sort((a, b) => (a.due_date ?? "").localeCompare(b.due_date ?? ""));
  }, [dash, statusFilter, typeFilter]);

  const types = useMemo(
    () => Array.from(new Set((dash?.queue ?? []).map((o) => o.compliance_type))).sort(),
    [dash]
  );

  if (loading) return <div className="p-8 text-sm text-gray-500">Loading compliance…</div>;
  if (error) return <div className="p-8 text-sm text-red-600">{error}</div>;

  const s = dash?.summary;
  return (
    <div className="p-6 max-w-6xl">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <ShieldCheck size={18} className="text-[#182350]" />
          <h1 className="text-lg font-semibold text-[#182350]">Compliance</h1>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={() => act(() => api.complianceOps.generate(), (r) => {
            const d = (r as ApiResp<{ generated: number }>).data; return `${d?.generated ?? 0} obligation(s) generated.`;
          })} disabled={busy}
            className="flex items-center gap-1.5 text-[12px] px-3 py-1.5 rounded-lg border border-gray-200 text-[#182350] hover:bg-[#F8FAFC] disabled:opacity-50">
            <PlayCircle size={13} /> Generate obligations
          </button>
          <button onClick={() => act(() => api.complianceOps.runEscalations(), (r) => {
            const d = (r as ApiResp<{ escalated: number }>).data; return `${d?.escalated ?? 0} escalation(s) sent (internal).`;
          })} disabled={busy}
            className="flex items-center gap-1.5 text-[12px] px-3 py-1.5 rounded-lg bg-[#182350] text-white disabled:opacity-50">
            <Bell size={13} /> Run escalations
          </button>
          <button onClick={load} className="flex items-center gap-1.5 text-[12px] text-gray-500 hover:text-[#182350]">
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      {msg && <div className="mb-3 text-[12px] px-3 py-2 rounded-lg bg-blue-50 text-blue-700">{msg}</div>}

      {/* Summary */}
      <div className="grid grid-cols-5 gap-3 mb-6">
        {[
          { label: "Total", value: s?.total_obligations ?? 0, cls: "text-[#182350]" },
          { label: "Open", value: s?.open_obligations ?? 0, cls: "text-[#182350]" },
          { label: "Due this week", value: s?.due_this_week ?? 0, cls: "text-amber-600" },
          { label: "Due this month", value: s?.due_this_month ?? 0, cls: "text-blue-600" },
          { label: "Overdue", value: s?.overdue ?? 0, cls: "text-red-600" },
        ].map((t) => (
          <div key={t.label} className="bg-white rounded-xl border border-gray-200 p-4">
            <p className="text-[11px] text-gray-500 uppercase">{t.label}</p>
            <p className={`text-2xl font-semibold tabular-nums mt-1 ${t.cls}`}>{t.value}</p>
          </div>
        ))}
      </div>

      {/* Workload */}
      <div className="grid grid-cols-2 gap-4 mb-6">
        <WorkloadCard title="Workload by staff" rows={dash?.by_staff ?? []} emptyLabel="No assigned obligations" />
        <WorkloadCard title="Workload by client" rows={dash?.by_client ?? []} emptyLabel="No open obligations" />
      </div>

      {/* Queue */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <CalendarClock size={15} className="text-[#182350]" />
            <h2 className="text-sm font-semibold text-[#182350]">Compliance queue</h2>
            <span className="text-[11px] text-gray-400">{queue.length} of {dash?.queue.length ?? 0}</span>
          </div>
          <div className="flex gap-2">
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
              className="text-[12px] border border-gray-200 rounded-lg px-2 py-1 text-gray-600">
              <option value="all">All statuses</option>
              {Object.keys(NEXT_STATUS).map((st) => <option key={st} value={st}>{st}</option>)}
            </select>
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}
              className="text-[12px] border border-gray-200 rounded-lg px-2 py-1 text-gray-600">
              <option value="all">All types</option>
              {types.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        </div>
        {queue.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-12">No obligations match the filters.</p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[#94A3B8] border-b border-gray-100">
                <th className="px-4 py-2.5 text-left font-semibold">Obligation</th>
                <th className="px-3 py-2.5 text-left font-semibold">Type</th>
                <th className="px-3 py-2.5 text-left font-semibold">Due</th>
                <th className="px-3 py-2.5 text-left font-semibold">Status</th>
                <th className="px-3 py-2.5 text-right font-semibold">Risk</th>
                <th className="px-4 py-2.5 text-right font-semibold">Advance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {queue.map((o) => {
                const overdue = o.status !== "Filed" && o.status !== "Completed" && o.due_date < today;
                return (
                  <tr key={o.id} className="hover:bg-[#F8FAFC]">
                    <td className="px-4 py-2.5 font-medium text-[#1E293B]">{o.period_label ?? o.obligation_type ?? "—"}</td>
                    <td className="px-3 py-2.5 text-gray-500">{o.compliance_type}</td>
                    <td className={`px-3 py-2.5 whitespace-nowrap ${overdue ? "text-red-600 font-medium" : "text-gray-600"}`}>
                      {overdue && <AlertTriangle size={11} className="inline mr-1 -mt-0.5" />}{o.due_date}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE[o.status] ?? "bg-gray-100 text-gray-600"}`}>{o.status}</span>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-gray-500">{o.risk_score ?? "—"}</td>
                    <td className="px-4 py-2.5 text-right">
                      {(NEXT_STATUS[o.status] ?? []).length === 0 ? (
                        <span className="text-gray-300">—</span>
                      ) : (
                        <select disabled={busy} defaultValue=""
                          onChange={(e) => { if (e.target.value) transition(o, e.target.value); }}
                          className="text-[11px] border border-gray-200 rounded px-1.5 py-1 text-[#182350]">
                          <option value="">→ move to…</option>
                          {(NEXT_STATUS[o.status] ?? []).map((st) => <option key={st} value={st}>{st}</option>)}
                        </select>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <p className="text-[11px] text-gray-400 mt-4">
        Obligations are generated from active engagements using statutory due dates. Escalations are internal only —
        clients are never emailed. Nothing here files or submits to any government portal.
      </p>
    </div>
  );
}

function WorkloadCard({ title, rows, emptyLabel }: { title: string; rows: WorkloadRow[]; emptyLabel: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100">
        <h2 className="text-sm font-semibold text-[#182350]">{title}</h2>
      </div>
      {rows.length === 0 ? (
        <p className="text-[12px] text-gray-400 text-center py-8">{emptyLabel}</p>
      ) : (
        <table className="w-full text-xs">
          <tbody className="divide-y divide-gray-50">
            {rows.slice(0, 8).map((r) => (
              <tr key={r.key} className="hover:bg-[#F8FAFC]">
                <td className="px-4 py-2.5 text-[#334155] font-mono truncate max-w-[260px]">{r.key}</td>
                <td className="px-3 py-2.5 text-right text-gray-500">{r.obligations} open</td>
                <td className="px-4 py-2.5 text-right">
                  {r.overdue > 0
                    ? <span className="text-red-600 font-medium">{r.overdue} overdue</span>
                    : <span className="text-gray-300">0 overdue</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function CompliancePracticePage() {
  return <PartnerGuard><ComplianceDashboard /></PartnerGuard>;
}
