"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { ShieldCheck, RefreshCw, Bell, PlayCircle, AlertTriangle, CalendarClock, Download } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { PartnerGuard } from "@/components/practice/PartnerGuard";
import { todayLocalISO } from "@/lib/dateMath";
import { downloadCsv } from "@/components/ui/data-table";
import { toCsv } from "@/lib/table/process";
import { objectOrNull } from "@/lib/api/shape";
import { MarkFiledModal } from "@/components/compliance/MarkFiledModal";
import { describeFilingOutcome } from "@/lib/compliance/filingOutcome";

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
  "Awaiting Documents": "bg-state-attention-surface text-state-attention",
  "In Progress": "bg-state-working-surface text-state-working",
  "Ready For Review": "bg-state-attention-surface text-state-attention",
  "Ready To File": "bg-state-attention-surface text-state-attention",
  "Filed": "bg-state-ready-surface text-state-ready",
  "Completed": "bg-state-ready-surface text-state-ready",
  "Overdue": "bg-state-problem-surface text-state-problem",
};

interface Obligation {
  id: string; client_id: string; compliance_type: string; obligation_type?: string | null;
  period_label?: string; due_date: string; status: string;
  preparer_id?: string | null; reviewer_id?: string | null; approver_id?: string | null;
  risk_score?: number;
  /** Resolved server-side by `GET /api/compliance/dashboard` — this is the
   *  FIRM-WIDE queue, so a row without its client is a row nobody can act on.
   *  Optional because a backend older than the field does not send it. */
  client_name?: string | null;
}
// Mirrors the visible "Compliance queue" table columns (see the <td> cells below).
// The file falls back to the client ID where the name is absent: a blank cell
// in an exported file cannot be looked up, an ID can.
const QUEUE_EXPORT_COLUMNS: { key: string; header: string; accessor: (row: Obligation) => unknown }[] = [
  { key: "client",      header: "Client",      accessor: (o) => o.client_name ?? o.client_id },
  { key: "obligation",  header: "Obligation",  accessor: (o) => o.period_label ?? o.obligation_type ?? o.compliance_type },
  { key: "type",        header: "Type",        accessor: (o) => o.compliance_type },
  { key: "due_date",    header: "Due Date",    accessor: (o) => o.due_date },
  { key: "status",      header: "Status",      accessor: (o) => o.status },
  { key: "risk_score",  header: "Risk Score",  accessor: (o) => o.risk_score ?? "" },
];
// `key` is the bucket's ID (a client or staff UUID, or "unassigned") and stays
// the React key; `label` is the name the server resolved for it. A backend
// older than `label` sends only the key, which is still rendered rather than
// dropping the row.
interface WorkloadRow { key: string; label?: string | null; obligations: number; overdue: number }
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
  // The obligation being moved to Filed. That move is the one that RECORDS a
  // filing — and, for a GSTR-1 or GSTR-3B, closes its period — so it asks for
  // the date the return was filed rather than stamping one; every other move is
  // a plain status change.
  const [filing, setFiling] = useState<Obligation | null>(null);
  const [filingError, setFilingError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const d = await api.complianceOps.dashboard() as ApiResp<Dashboard>;
      setDash(objectOrNull(d.data));
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
    if (status === "Filed") { setFilingError(null); setFiling(o); return; }
    await act(() => api.complianceOps.transition(o.id, status),
      () => `${o.obligation_type ?? o.compliance_type} → ${status}`);
  }

  async function markFiled(v: { filedDate: string; arn: string }) {
    if (!filing) return;
    const o = filing;
    setBusy(true); setFilingError(null);
    try {
      const res = await api.complianceOps.markFiled(o.id, {
        acknowledgementNo: v.arn || undefined, filedDate: v.filedDate,
      });
      const outcome = describeFilingOutcome(res.data, o.period_label ?? o.obligation_type ?? o.compliance_type);
      setFiling(null);
      setMsg(`${outcome.title}. ${outcome.description}`);
      await load();
    } catch (e) {
      setFilingError(e instanceof Error ? e.message : "Couldn't mark this filed.");
    } finally { setBusy(false); }
  }

  const today = todayLocalISO();
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
          <ShieldCheck size={18} className="text-brand" />
          <h1 className="text-lg font-semibold text-brand">Compliance</h1>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={() => act(() => api.complianceOps.generate(), (r) => {
            const d = (r as ApiResp<{ generated: number }>).data; return `${d?.generated ?? 0} obligation(s) generated.`;
          })} disabled={busy}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-brand hover:bg-ps-bg disabled:opacity-50">
            <PlayCircle size={13} /> Generate obligations
          </button>
          <button onClick={() => act(() => api.complianceOps.runEscalations(), (r) => {
            const d = (r as ApiResp<{ escalated: number }>).data; return `${d?.escalated ?? 0} escalation(s) sent (internal).`;
          })} disabled={busy}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-brand text-white disabled:opacity-50">
            <Bell size={13} /> Run escalations
          </button>
          <button onClick={load} className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-brand">
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      {msg && <div className="mb-3 text-xs px-3 py-2 rounded-lg bg-blue-50 text-blue-700">{msg}</div>}

      {/* Summary */}
      <div className="grid grid-cols-5 gap-3 mb-6">
        {[
          { label: "Total", value: s?.total_obligations ?? 0, cls: "text-brand" },
          { label: "Open", value: s?.open_obligations ?? 0, cls: "text-brand" },
          { label: "Due this week", value: s?.due_this_week ?? 0, cls: "text-amber-600" },
          { label: "Due this month", value: s?.due_this_month ?? 0, cls: "text-blue-600" },
          { label: "Overdue", value: s?.overdue ?? 0, cls: "text-red-600" },
        ].map((t) => (
          <div key={t.label} className="bg-white rounded-xl border border-gray-200 p-4">
            <p className="text-2xs text-gray-500 uppercase">{t.label}</p>
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
        <div className="flex items-center justify-between px-4 py-3 border-b border-ps-border">
          <div className="flex items-center gap-2">
            <CalendarClock size={15} className="text-brand" />
            <h2 className="text-sm font-semibold text-brand">Compliance queue</h2>
            <span className="text-2xs text-gray-400">{queue.length} of {dash?.queue?.length ?? 0}</span>
          </div>
          <div className="flex gap-2">
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
              className="text-xs border border-gray-200 rounded-lg px-2 py-1 text-gray-600">
              <option value="all">All statuses</option>
              {Object.keys(NEXT_STATUS).map((st) => <option key={st} value={st}>{st}</option>)}
            </select>
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}
              className="text-xs border border-gray-200 rounded-lg px-2 py-1 text-gray-600">
              <option value="all">All types</option>
              {types.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <button onClick={() => downloadCsv("compliance-queue.csv", toCsv(queue, QUEUE_EXPORT_COLUMNS))}
              disabled={queue.length === 0}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-brand hover:bg-ps-bg disabled:opacity-50">
              <Download size={13} /> Export
            </button>
          </div>
        </div>
        {queue.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-12">No obligations match the filters.</p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-ps-hint border-b border-ps-border">
                <th className="px-4 py-2.5 text-left font-semibold">Client</th>
                <th className="px-3 py-2.5 text-left font-semibold">Obligation</th>
                <th className="px-3 py-2.5 text-left font-semibold">Type</th>
                <th className="px-3 py-2.5 text-left font-semibold">Due</th>
                <th className="px-3 py-2.5 text-left font-semibold">Status</th>
                <th className="px-3 py-2.5 text-right font-semibold">Risk</th>
                <th className="px-4 py-2.5 text-right font-semibold">Advance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ps-border">
              {queue.map((o) => {
                const overdue = o.status !== "Filed" && o.status !== "Completed" && o.due_date < today;
                return (
                  <tr key={o.id} className="hover:bg-ps-bg">
                    <td className="px-4 py-2.5 text-ps-body truncate max-w-[200px]" title={o.client_name ?? o.client_id}>
                      {o.client_name ?? "—"}
                    </td>
                    <td className="px-3 py-2.5 font-medium text-ps-ink">{o.period_label ?? o.obligation_type ?? "—"}</td>
                    <td className="px-3 py-2.5 text-gray-500">{o.compliance_type}</td>
                    <td className={`px-3 py-2.5 whitespace-nowrap ${overdue ? "text-red-600 font-medium" : "text-gray-600"}`}>
                      {overdue && <AlertTriangle size={11} className="inline mr-1 -mt-0.5" />}{o.due_date}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`px-1.5 py-0.5 rounded-full text-3xs font-medium ${STATUS_BADGE[o.status] ?? "bg-gray-100 text-gray-600"}`}>{o.status}</span>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-gray-500">{o.risk_score ?? "—"}</td>
                    <td className="px-4 py-2.5 text-right">
                      {(NEXT_STATUS[o.status] ?? []).length === 0 ? (
                        <span className="text-gray-300">—</span>
                      ) : (
                        <select disabled={busy} defaultValue=""
                          onChange={(e) => { if (e.target.value) transition(o, e.target.value); }}
                          className="text-2xs border border-gray-200 rounded px-1.5 py-1 text-brand">
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

      {filing && (
        <MarkFiledModal
          intro={`${filing.client_name ?? "Client"} — ${filing.period_label ?? filing.obligation_type ?? filing.compliance_type}`}
          busy={busy}
          error={filingError}
          onConfirm={markFiled}
          onClose={() => { setFiling(null); setFilingError(null); }}
        />
      )}

      <p className="text-2xs text-gray-400 mt-4">
        Obligations are generated from active engagements using statutory due dates. Escalations are internal only —
        clients are never emailed. Nothing here files or submits to any government portal.
      </p>
    </div>
  );
}

function WorkloadCard({ title, rows, emptyLabel }: { title: string; rows: WorkloadRow[]; emptyLabel: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-4 py-3 border-b border-ps-border">
        <h2 className="text-sm font-semibold text-brand">{title}</h2>
      </div>
      {rows.length === 0 ? (
        <p className="text-xs text-gray-400 text-center py-8">{emptyLabel}</p>
      ) : (
        <table className="w-full text-xs">
          <tbody className="divide-y divide-ps-border">
            {rows.slice(0, 8).map((r) => (
              <tr key={r.key} className="hover:bg-ps-bg">
                <td
                  className={`px-4 py-2.5 text-ps-body truncate max-w-[260px] ${r.label ? "" : "font-mono"}`}
                  title={r.label ? r.key : undefined}
                >
                  {r.label ?? r.key}
                </td>
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
