"use client";

import { useState, useEffect } from "react";
import { Shield, AlertTriangle, Clock, CheckCircle, FileText, Plus } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/services/formatting";
import type { ComplianceRecord, ComplianceRecordStatus, ComplianceRecordType, ComplianceFirmSummary, ApiResponse } from "@/lib/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const STATUS_COLORS: Record<ComplianceRecordStatus, string> = {
  "Not Started": "bg-gray-100 text-gray-600",
  "Awaiting Documents": "bg-amber-100 text-amber-700",
  "In Progress": "bg-blue-100 text-blue-700",
  "Ready For Review": "bg-orange-100 text-orange-700",
  "Ready To File": "bg-purple-100 text-purple-700",
  "Filed": "bg-green-100 text-green-700",
  "Overdue": "bg-red-100 text-red-700",
};

const RISK_COLORS: Record<string, string> = {
  low: "text-green-600",
  medium: "text-amber-600",
  high: "text-orange-600",
  critical: "text-red-600",
};

function riskLabel(score: number): string {
  if (score >= 86) return "Critical";
  if (score >= 70) return "High";
  if (score >= 50) return "Medium";
  if (score >= 10) return "Low";
  return "None";
}

function riskLevel(score: number): string {
  if (score >= 86) return "critical";
  if (score >= 70) return "high";
  if (score >= 50) return "medium";
  return "low";
}

const ALL_STATUSES: ComplianceRecordStatus[] = [
  "Not Started", "Awaiting Documents", "In Progress", "Ready For Review", "Ready To File", "Filed", "Overdue"
];
const ALL_TYPES: ComplianceRecordType[] = ["GST", "Income Tax", "TDS", "MCA", "Payroll", "Bookkeeping"];

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

export default function CompliancePage() {
  const [records, setRecords] = useState<ComplianceRecord[]>([]);
  const [firmSummary, setFirmSummary] = useState<ComplianceFirmSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<ComplianceRecordStatus | "">("");
  const [typeFilter, setTypeFilter] = useState<ComplianceRecordType | "">("");
  const [clientFilter, setClientFilter] = useState("");

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [recRes, sumRes] = await Promise.all([
        fetch(`${BASE_URL}/api/compliance-records`).then((r) => r.json()) as Promise<ApiResponse<ComplianceRecord[]>>,
        fetch(`${BASE_URL}/api/compliance-records/firm/summary`).then((r) => r.json()) as Promise<ApiResponse<ComplianceFirmSummary>>,
      ]);
      if (recRes.success) setRecords(recRes.data);
      else setError(recRes.error ?? "Failed to load records");
      if (sumRes.success) setFirmSummary(sumRes.data);
    } catch {
      setError("Failed to load compliance data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadData(); }, []);

  async function handleStatusUpdate(id: string, newStatus: ComplianceRecordStatus) {
    const res: ApiResponse<ComplianceRecord> = await fetch(`${BASE_URL}/api/compliance-records/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: newStatus }),
    }).then((r) => r.json());
    if (res.success) {
      setRecords((prev) => prev.map((r) => r.id === id ? res.data : r));
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

  const filtered = records.filter((r) => {
    if (statusFilter && r.status !== statusFilter) return false;
    if (typeFilter && r.compliance_type !== typeFilter) return false;
    if (clientFilter && !r.client_name?.toLowerCase().includes(clientFilter.toLowerCase())) return false;
    return true;
  });

  const STATS = [
    { label: "Due This Week", value: firmSummary?.due_this_week ?? 0, icon: Clock, color: "text-amber-600", bg: "bg-amber-50" },
    { label: "Overdue", value: firmSummary?.overdue ?? 0, icon: AlertTriangle, color: "text-red-600", bg: "bg-red-50" },
    { label: "Ready For Review", value: firmSummary?.ready_for_review ?? 0, icon: FileText, color: "text-orange-600", bg: "bg-orange-50" },
    { label: "Ready To File", value: firmSummary?.ready_to_file ?? 0, icon: Shield, color: "text-purple-600", bg: "bg-purple-50" },
    { label: "Filed", value: firmSummary?.filed_this_month ?? 0, icon: CheckCircle, color: "text-green-600", bg: "bg-green-50" },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Compliance</h1>
          <p className="text-sm text-gray-500 mt-0.5">Track GST, ITR, TDS and other filings across all clients</p>
        </div>
        <button className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700">
          <Plus size={13} /> New Record
        </button>
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

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div>
          <label className="text-xs text-gray-500">Status</label>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as ComplianceRecordStatus | "")}
            className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All statuses</option>
            {ALL_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500">Type</label>
          <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value as ComplianceRecordType | "")}
            className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All types</option>
            {ALL_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500">Client</label>
          <input value={clientFilter} onChange={(e) => setClientFilter(e.target.value)}
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
                <th className="px-3 py-3 text-left font-semibold">Assigned</th>
                <th className="px-5 py-3 text-left font-semibold">Risk</th>
                <th className="px-3 py-3 text-left font-semibold">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {filtered.map((r) => (
                <tr key={r.id} className="hover:bg-gray-50">
                  <td className="px-5 py-3 text-sm font-medium text-gray-900">{r.client_name}</td>
                  <td className="px-3 py-3 text-xs text-gray-600">{r.compliance_type}</td>
                  <td className="px-3 py-3 text-xs text-gray-500">{r.period_label}</td>
                  <td className="px-3 py-3 text-xs text-gray-600 whitespace-nowrap">{formatDate(r.due_date)}</td>
                  <td className="px-3 py-3">
                    <Badge className={`text-xs ${STATUS_COLORS[r.status]}`}>{r.status}</Badge>
                  </td>
                  <td className="px-3 py-3 text-xs text-gray-500">{r.assigned_to ?? "—"}</td>
                  <td className="px-5 py-3">
                    <span className={`text-xs font-semibold ${RISK_COLORS[riskLevel(r.risk_score)]}`}>
                      {riskLabel(r.risk_score)} ({r.risk_score})
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <select
                      value={r.status}
                      onChange={(e) => handleStatusUpdate(r.id, e.target.value as ComplianceRecordStatus)}
                      className="text-xs border border-gray-200 rounded px-1.5 py-1 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    >
                      {ALL_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
