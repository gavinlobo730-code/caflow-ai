"use client";

import { useState, useEffect } from "react";
import { Shield, AlertTriangle, Clock, CheckCircle, FileText } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/services/formatting";
import { getComplianceCalendar, updateFilingStatus, seedComplianceCalendar } from "@/lib/data/compliance";
import type { ComplianceEntry } from "@/lib/data/compliance";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";

const FILING_STATUS_COLORS: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  in_progress: "bg-blue-100 text-blue-700",
  filed: "bg-green-100 text-green-700",
  overdue: "bg-red-100 text-red-700",
  na: "bg-gray-100 text-gray-500",
};

const ALL_TYPES = ["GSTR1", "GSTR3B", "GSTR9", "ITR", "TDS24Q", "TDS26Q", "ADVANCE_TAX"];
const ALL_STATUSES = ["pending", "in_progress", "filed", "overdue", "na"];

function LoadingSpinner() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4 animate-pulse">
      <div className="h-6 bg-gray-200 rounded w-48" />
      <div className="grid grid-cols-5 gap-3">
        {[1, 2, 3, 4, 5].map((i) => <div key={i} className="h-20 bg-gray-100 rounded-lg" />)}
      </div>
      <div className="h-64 bg-gray-100 rounded-xl" />
    </div>
  );
}

interface MarkFiledForm {
  id: string;
  arn: string;
}

export default function CompliancePage() {
  const [records, setRecords] = useState<ComplianceEntry[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [clientFilter, setClientFilter] = useState("");
  const [markFiled, setMarkFiled] = useState<MarkFiledForm | null>(null);
  const [filingLoading, setFilingLoading] = useState(false);

  async function loadData(clientId?: string) {
    setLoading(true);
    setError(null);
    try {
      const [recs, cls] = await Promise.all([
        getComplianceCalendar(clientId || undefined),
        getClients().catch(() => [] as Client[]),
      ]);
      // If filtering by client and empty — seed calendar
      if (clientId && recs.length === 0) {
        await seedComplianceCalendar(clientId).catch(() => undefined);
        const seeded = await getComplianceCalendar(clientId).catch(() => [] as ComplianceEntry[]);
        setRecords(seeded);
      } else {
        setRecords(recs);
      }
      setClients(cls);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load compliance data");
    } finally {
      setLoading(false);
    }
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

  // Computed stats from fetched data
  const overdue = records.filter(r => r.due_date < today && r.filing_status !== "filed" && r.filing_status !== "na").length;
  const dueThisWeek = records.filter(r => r.due_date >= today && r.due_date <= in7Days && r.filing_status !== "filed").length;
  const inProgress = records.filter(r => r.filing_status === "in_progress").length;
  const filed = records.filter(r => r.filing_status === "filed").length;
  const pending = records.filter(r => r.filing_status === "pending").length;

  const STATS = [
    { label: "Due This Week", value: dueThisWeek, icon: Clock, color: "text-amber-600", bg: "bg-amber-50" },
    { label: "Overdue", value: overdue, icon: AlertTriangle, color: "text-red-600", bg: "bg-red-50" },
    { label: "In Progress", value: inProgress, icon: FileText, color: "text-blue-600", bg: "bg-blue-50" },
    { label: "Pending", value: pending, icon: Shield, color: "text-purple-600", bg: "bg-purple-50" },
    { label: "Filed", value: filed, icon: CheckCircle, color: "text-green-600", bg: "bg-green-50" },
  ];

  // Client lookup
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
          <h1 className="text-xl font-semibold text-gray-900">Compliance</h1>
          <p className="text-sm text-gray-500 mt-0.5">Track GST, ITR, TDS and other filings across all clients</p>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {STATS.map((s) => (
          <Card key={s.label}>
            <CardContent className="pt-4 pb-3">
              <div className={`w-8 h-8 rounded-lg ${s.bg} flex items-center justify-center mb-2`}>
                <s.icon size={16} className={s.color} />
              </div>
              <p className="text-2xl font-bold text-gray-900">{s.value}</p>
              <p className="text-xs text-gray-500 mt-0.5 leading-tight">{s.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Mark as Filed inline form */}
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
                className="text-xs px-3 py-1.5 border border-gray-200 rounded-md hover:bg-gray-100 bg-white"
              >
                Cancel
              </button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div>
          <label className="text-xs text-gray-500">Status</label>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
            className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All statuses</option>
            {ALL_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500">Type</label>
          <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
            className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All types</option>
            {ALL_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500">Client</label>
          <input value={clientFilter} onChange={e => setClientFilter(e.target.value)}
            placeholder="Search client…"
            className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 w-48" />
        </div>
      </div>

      {/* Records table */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">{filtered.length} records</CardTitle>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-xs text-gray-400">
                <th className="px-5 py-3 text-left font-semibold">Client</th>
                <th className="px-3 py-3 text-left font-semibold">Type</th>
                <th className="px-3 py-3 text-left font-semibold">Period</th>
                <th className="px-3 py-3 text-left font-semibold">Due Date</th>
                <th className="px-3 py-3 text-left font-semibold">Status</th>
                <th className="px-3 py-3 text-left font-semibold">ARN</th>
                <th className="px-5 py-3 text-left font-semibold">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {filtered.map((r) => (
                <tr key={r.id} className="hover:bg-gray-50">
                  <td className="px-5 py-3 text-sm font-medium text-gray-900">
                    {clientMap[r.client_id] ?? r.client_id.slice(0, 8)}
                  </td>
                  <td className="px-3 py-3 text-xs text-gray-600">{r.compliance_type}</td>
                  <td className="px-3 py-3 text-xs text-gray-500 whitespace-nowrap">
                    {formatDate(r.period_start)} – {formatDate(r.period_end)}
                  </td>
                  <td className={`px-3 py-3 text-xs whitespace-nowrap ${r.due_date < today && r.filing_status !== "filed" ? "text-red-600 font-medium" : "text-gray-600"}`}>
                    {formatDate(r.due_date)}
                  </td>
                  <td className="px-3 py-3">
                    <Badge className={`text-xs ${FILING_STATUS_COLORS[r.filing_status] ?? "bg-gray-100 text-gray-600"}`}>
                      {r.filing_status}
                    </Badge>
                  </td>
                  <td className="px-3 py-3 text-xs text-gray-500 font-mono">{r.arn_number ?? "—"}</td>
                  <td className="px-5 py-3">
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
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <div className="text-center py-8 text-sm text-gray-400">No compliance records found</div>
          )}
        </div>
      </Card>
    </div>
  );
}
