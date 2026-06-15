"use client";

import { useState, useEffect } from "react";
import { Calendar, AlertTriangle, Clock, CheckCircle, FileText, ExternalLink, FlaskConical } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { formatDate } from "@/lib/services/formatting";
import { getComplianceCalendar, updateFilingStatus, seedComplianceCalendar } from "@/lib/data/compliance";
import type { ComplianceEntry } from "@/lib/data/compliance";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";
import DemoFilingModal from "@/components/DemoFilingModal";
import { getDemoFilingsByEntry, saveDemoFiling, type DemoFiling } from "@/lib/data/demoFilings";
import { isSimulatable, DEMO_STATUS_LABEL } from "@/lib/filing/demoFiling";

const FILING_STATUS_COLORS: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  in_progress: "bg-blue-100 text-blue-700",
  filed: "bg-green-100 text-green-700",
  overdue: "bg-red-100 text-red-700",
  na: "bg-[#F1F5F9] text-[#64748B]",
};

const ALL_TYPES = ["GSTR1", "GSTR3B", "GSTR9", "ITR", "TDS24Q", "TDS26Q", "ADVANCE_TAX"];
const ALL_STATUSES = ["pending", "in_progress", "filed", "overdue", "na"];

function LoadingSpinner() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4 animate-pulse">
      <div className="h-6 bg-white/[0.08] rounded w-48" />
      <div className="grid grid-cols-5 gap-3">
        {[1, 2, 3, 4, 5].map((i) => <div key={i} className="h-20 bg-[#F1F5F9] rounded-lg" />)}
      </div>
      <div className="h-64 bg-[#F1F5F9] rounded-xl" />
    </div>
  );
}

interface MarkFiledForm {
  id: string;
  arn: string;
}

export default function DeadlinesPage() {
  const [records, setRecords] = useState<ComplianceEntry[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [clientFilter, setClientFilter] = useState("");
  const [markFiled, setMarkFiled] = useState<MarkFiledForm | null>(null);
  const [filingLoading, setFilingLoading] = useState(false);
  const [demoFilings, setDemoFilings] = useState<Record<string, DemoFiling>>({});
  const [demoEntry, setDemoEntry] = useState<ComplianceEntry | null>(null);

  async function loadData(clientId?: string) {
    setLoading(true);
    setError(null);
    try {
      const [recs, cls, demos] = await Promise.all([
        getComplianceCalendar(clientId || undefined),
        getClients().catch(() => [] as Client[]),
        getDemoFilingsByEntry(clientId || undefined).catch(() => ({} as Record<string, DemoFiling>)),
      ]);
      if (clientId && recs.length === 0) {
        await seedComplianceCalendar(clientId).catch(() => undefined);
        const seeded = await getComplianceCalendar(clientId).catch(() => [] as ComplianceEntry[]);
        setRecords(seeded);
      } else {
        setRecords(recs);
      }
      setClients(cls);
      setDemoFilings(demos);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load deadline data");
    } finally {
      setLoading(false);
    }
  }

  async function handleSimulated(demoReference: string) {
    if (!demoEntry) return;
    await saveDemoFiling(demoEntry, demoReference);
    setDemoFilings(prev => ({
      ...prev,
      [demoEntry.id]: {
        id: "local", firm_id: "", client_id: demoEntry.client_id,
        compliance_entry_id: demoEntry.id, compliance_type: demoEntry.compliance_type,
        period_start: demoEntry.period_start, period_end: demoEntry.period_end,
        demo_reference: demoReference, demo_status: "demo_filed",
        simulated_at: new Date().toISOString(),
      },
    }));
  }

  useEffect(() => { loadData(); }, []);

  async function handleMarkFiled() {
    if (!markFiled) return;
    setFilingLoading(true);
    try {
      await updateFilingStatus(markFiled.id, "filed", markFiled.arn || undefined);
      setRecords(prev => prev.map(r =>
        r.id === markFiled.id ? { ...r, filing_status: "filed", arn_number: markFiled.arn } : r
      ));
      setMarkFiled(null);
    } finally {
      setFilingLoading(false);
    }
  }

  if (loading) return <LoadingSpinner />;

  if (error) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>
      </div>
    );
  }

  const today = new Date().toISOString().split("T")[0];
  const in7Days = new Date(Date.now() + 7 * 86400000).toISOString().split("T")[0];

  const overdue = records.filter(r => r.due_date < today && r.filing_status !== "filed" && r.filing_status !== "na").length;
  const dueThisWeek = records.filter(r => r.due_date >= today && r.due_date <= in7Days && r.filing_status !== "filed").length;
  const inProgress = records.filter(r => r.filing_status === "in_progress").length;
  const filed = records.filter(r => r.filing_status === "filed").length;
  const pending = records.filter(r => r.filing_status === "pending").length;

  const demoCount = Object.keys(demoFilings).length;

  const STATS = [
    { label: "Due This Week", value: dueThisWeek, icon: Clock, color: "text-amber-600", bg: "bg-amber-50" },
    { label: "Overdue", value: overdue, icon: AlertTriangle, color: "text-red-600", bg: "bg-red-50" },
    { label: "In Progress", value: inProgress, icon: FileText, color: "text-blue-600", bg: "bg-blue-50" },
    { label: "Pending", value: pending, icon: Calendar, color: "text-purple-600", bg: "bg-purple-50" },
    { label: "Filed", value: filed, icon: CheckCircle, color: "text-green-600", bg: "bg-green-50" },
    { label: "Demo Filed", value: demoCount, icon: FlaskConical, color: "text-amber-600", bg: "bg-amber-50" },
  ];

  const clientMap = Object.fromEntries(clients.map(c => [c.id, c.client_name]));

  const filtered = records.filter(r => {
    if (statusFilter && r.filing_status !== statusFilter) return false;
    if (typeFilter && r.compliance_type !== typeFilter) return false;
    if (clientFilter) {
      const name = (clientMap[r.client_id] ?? "").toLowerCase();
      if (!name.includes(clientFilter.toLowerCase())) return false;
    }
    return true;
  });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Deadlines</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            Cross-client compliance calendar — triage here, file inside each client
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        {STATS.map((s) => (
          <Card key={s.label}>
            <CardContent className="pt-4 pb-3">
              <div className={`w-8 h-8 rounded-lg ${s.bg} flex items-center justify-center mb-2`}>
                <s.icon size={16} className={s.color} />
              </div>
              <p className="text-2xl font-bold text-[#0F172A]">{s.value}</p>
              <p className="text-xs text-[#64748B] mt-0.5 leading-tight">{s.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
        <Calendar size={16} className="text-amber-600 mt-0.5 shrink-0" />
        <p className="text-sm text-amber-800">
          <strong>Triage view.</strong> To file a return, click the client name or &ldquo;Open Client&rdquo; to go
          directly to that client&apos;s Compliance tab.
        </p>
      </div>

      {markFiled && (
        <Card className="border-blue-200 bg-blue-50">
          <CardContent className="pt-4 pb-4">
            <p className="text-sm font-medium text-blue-900 mb-3">Mark as Filed</p>
            <div className="flex gap-3 items-center">
              <input
                value={markFiled.arn}
                onChange={e => setMarkFiled({ ...markFiled, arn: e.target.value })}
                placeholder="ARN Number (optional)"
                className="flex-1 px-3 py-1.5 text-sm border border-blue-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              />
              <button
                onClick={handleMarkFiled}
                disabled={filingLoading}
                className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                {filingLoading ? "Saving…" : "Confirm Filed"}
              </button>
              <button
                onClick={() => setMarkFiled(null)}
                className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-md hover:bg-[#F1F5F9] bg-white"
              >
                Cancel
              </button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="flex flex-wrap gap-3">
        <div>
          <label className="text-xs text-[#64748B]">Status</label>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
            className="block mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All statuses</option>
            {ALL_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-[#64748B]">Type</label>
          <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
            className="block mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All types</option>
            {ALL_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-[#64748B]">Client</label>
          <input value={clientFilter} onChange={e => setClientFilter(e.target.value)}
            placeholder="Search client…"
            className="block mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 w-48" />
        </div>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">{filtered.length} records</CardTitle>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                <th className="px-5 py-3 text-left font-semibold">Client</th>
                <th className="px-3 py-3 text-left font-semibold">Type</th>
                <th className="px-3 py-3 text-left font-semibold">Period</th>
                <th className="px-3 py-3 text-left font-semibold">Due Date</th>
                <th className="px-3 py-3 text-left font-semibold">Status</th>
                <th className="px-3 py-3 text-left font-semibold">ARN</th>
                <th className="px-5 py-3 text-left font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {filtered.map((r) => (
                <tr key={r.id} className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-sm font-medium">
                    <Link
                      href={`/clients/${r.client_id}`}
                      className="text-blue-600 hover:underline"
                    >
                      {clientMap[r.client_id] ?? r.client_id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="px-3 py-3 text-xs text-[#475569]">{r.compliance_type}</td>
                  <td className="px-3 py-3 text-xs text-[#64748B] whitespace-nowrap">
                    {formatDate(r.period_start)} – {formatDate(r.period_end)}
                  </td>
                  <td className={`px-3 py-3 text-xs whitespace-nowrap ${r.due_date < today && r.filing_status !== "filed" ? "text-red-600 font-medium" : "text-[#475569]"}`}>
                    {formatDate(r.due_date)}
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-col gap-1 items-start">
                      <Badge className={`text-xs ${FILING_STATUS_COLORS[r.filing_status] ?? "bg-[#F1F5F9] text-[#475569]"}`}>
                        {r.filing_status}
                      </Badge>
                      {demoFilings[r.id] && (
                        <Badge className="text-[10px] bg-amber-100 text-amber-700 flex items-center gap-1">
                          <FlaskConical size={10} /> {DEMO_STATUS_LABEL}
                        </Badge>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-xs text-[#64748B] font-mono">
                    {demoFilings[r.id]
                      ? <span className="text-amber-700" title="Demo reference — not filed with any portal">{demoFilings[r.id].demo_reference}</span>
                      : (r.arn_number ?? "—")}
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3 flex-wrap">
                      {r.filing_status !== "filed" && r.filing_status !== "na" && (
                        <button
                          onClick={() => setMarkFiled({ id: r.id, arn: r.arn_number ?? "" })}
                          className="text-xs text-blue-600 hover:underline flex items-center gap-1"
                        >
                          <CheckCircle size={12} /> Mark Filed
                        </button>
                      )}
                      {r.filing_status === "filed" && (
                        <span className="text-xs text-green-600 flex items-center gap-1">
                          <CheckCircle size={12} /> {r.filed_date ? formatDate(r.filed_date) : "Filed"}
                        </span>
                      )}
                      {isSimulatable(r.compliance_type) && (
                        <button
                          onClick={() => setDemoEntry(r)}
                          className="text-xs text-amber-700 hover:underline flex items-center gap-1"
                          title="Run a demo of the filing workflow — submits nothing"
                        >
                          <FlaskConical size={12} /> Simulate Filing
                        </button>
                      )}
                      <Link
                        href={`/clients/${r.client_id}`}
                        className="text-xs text-blue-600 hover:underline flex items-center gap-1"
                      >
                        <ExternalLink size={11} /> Open Client
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <div className="text-center py-8 text-sm text-[#94A3B8]">No compliance records found</div>
          )}
        </div>
      </Card>

      {demoEntry && (
        <DemoFilingModal
          entry={demoEntry}
          clientName={clientMap[demoEntry.client_id] ?? demoEntry.client_id.slice(0, 8)}
          onConfirmed={handleSimulated}
          onClose={() => setDemoEntry(null)}
        />
      )}
    </div>
  );
}
