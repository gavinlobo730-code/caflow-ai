"use client";
export const runtime = "edge";

import { useState } from "react";
import { Shield, AlertTriangle, Clock, CheckCircle, FileText, Plus } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/services/formatting";
import type { ComplianceRecord, ComplianceRecordStatus, ComplianceRecordType } from "@/lib/types";

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

// Mock compliance records — wire to /api/compliance-records once backend is running
const MOCK_RECORDS: ComplianceRecord[] = [
  { id: "cr-001", client_id: "c-001", client_name: "Sharma Enterprises", compliance_type: "GST", period_label: "Apr 2025", period_start: "2025-04-01", period_end: "2025-04-30", status: "In Progress", due_date: "2026-06-04", assigned_to: "tm-001", priority: "critical", risk_score: 75, created_at: "2026-05-22", updated_at: "2026-05-31" },
  { id: "cr-002", client_id: "c-001", client_name: "Sharma Enterprises", compliance_type: "Income Tax", period_label: "FY 2024-25", period_start: "2024-04-01", period_end: "2025-03-31", status: "Awaiting Documents", due_date: "2025-07-31", assigned_to: "tm-001", priority: "medium", risk_score: 25, created_at: "2026-05-12", updated_at: "2026-05-27" },
  { id: "cr-003", client_id: "c-001", client_name: "Sharma Enterprises", compliance_type: "TDS", period_label: "Q4 FY 2024-25", period_start: "2025-01-01", period_end: "2025-03-31", status: "Filed", due_date: "2025-05-31", assigned_to: "tm-001", priority: "low", risk_score: 0, created_at: "2026-04-02", updated_at: "2026-05-29" },
  { id: "cr-004", client_id: "c-002", client_name: "Patel & Sons", compliance_type: "GST", period_label: "Apr 2025", period_start: "2025-04-01", period_end: "2025-04-30", status: "Awaiting Documents", due_date: "2026-06-09", assigned_to: "tm-001", priority: "high", risk_score: 60, created_at: "2026-05-24", updated_at: "2026-05-30" },
  { id: "cr-005", client_id: "c-002", client_name: "Patel & Sons", compliance_type: "Income Tax", period_label: "FY 2024-25", period_start: "2024-04-01", period_end: "2025-03-31", status: "Not Started", due_date: "2025-07-31", assigned_to: "tm-001", priority: "medium", risk_score: 25, created_at: "2026-05-17", updated_at: "2026-05-17" },
  { id: "cr-006", client_id: "c-002", client_name: "Patel & Sons", compliance_type: "TDS", period_label: "Q4 FY 2024-25", period_start: "2025-01-01", period_end: "2025-03-31", status: "Filed", due_date: "2025-05-31", assigned_to: "tm-001", priority: "low", risk_score: 0, created_at: "2026-03-23", updated_at: "2026-06-01" },
  { id: "cr-007", client_id: "c-003", client_name: "Mehta Consulting", compliance_type: "GST", period_label: "Mar 2025", period_start: "2025-03-01", period_end: "2025-03-31", status: "Overdue", due_date: "2026-05-17", assigned_to: "tm-001", priority: "critical", risk_score: 90, created_at: "2026-05-03", updated_at: "2026-05-27" },
  { id: "cr-008", client_id: "c-003", client_name: "Mehta Consulting", compliance_type: "Income Tax", period_label: "FY 2024-25", period_start: "2024-04-01", period_end: "2025-03-31", status: "Awaiting Documents", due_date: "2025-07-31", assigned_to: "tm-001", priority: "medium", risk_score: 60, created_at: "2026-05-08", updated_at: "2026-05-16" },
  { id: "cr-009", client_id: "c-003", client_name: "Mehta Consulting", compliance_type: "TDS", period_label: "Q4 FY 2024-25", period_start: "2025-01-01", period_end: "2025-03-31", status: "Overdue", due_date: "2026-05-22", assigned_to: "tm-001", priority: "critical", risk_score: 90, created_at: "2026-04-23", updated_at: "2026-05-22" },
  { id: "cr-010", client_id: "c-004", client_name: "Desai Traders", compliance_type: "GST", period_label: "Apr 2025", period_start: "2025-04-01", period_end: "2025-04-30", status: "Ready To File", due_date: "2026-06-06", assigned_to: "tm-001", priority: "high", risk_score: 20, created_at: "2026-05-21", updated_at: "2026-05-31" },
  { id: "cr-011", client_id: "c-004", client_name: "Desai Traders", compliance_type: "Income Tax", period_label: "FY 2024-25", period_start: "2024-04-01", period_end: "2025-03-31", status: "Ready For Review", due_date: "2025-07-31", assigned_to: "tm-001", priority: "medium", risk_score: 25, created_at: "2026-05-15", updated_at: "2026-05-30" },
  { id: "cr-012", client_id: "c-004", client_name: "Desai Traders", compliance_type: "TDS", period_label: "Q4 FY 2024-25", period_start: "2025-01-01", period_end: "2025-03-31", status: "Filed", due_date: "2025-05-31", assigned_to: "tm-001", priority: "low", risk_score: 0, created_at: "2026-03-28", updated_at: "2026-05-21" },
  { id: "cr-013", client_id: "c-005", client_name: "Joshi Textiles", compliance_type: "GST", period_label: "Apr 2025", period_start: "2025-04-01", period_end: "2025-04-30", status: "In Progress", due_date: "2026-06-07", assigned_to: "tm-001", priority: "high", risk_score: 50, created_at: "2026-05-24", updated_at: "2026-05-31" },
  { id: "cr-014", client_id: "c-005", client_name: "Joshi Textiles", compliance_type: "Income Tax", period_label: "FY 2024-25", period_start: "2024-04-01", period_end: "2025-03-31", status: "Awaiting Documents", due_date: "2026-06-13", assigned_to: "tm-001", priority: "high", risk_score: 50, created_at: "2026-05-19", updated_at: "2026-05-25" },
  { id: "cr-015", client_id: "c-005", client_name: "Joshi Textiles", compliance_type: "TDS", period_label: "Q4 FY 2024-25", period_start: "2025-01-01", period_end: "2025-03-31", status: "Filed", due_date: "2025-05-31", assigned_to: "tm-001", priority: "low", risk_score: 0, created_at: "2026-04-03", updated_at: "2026-05-26" },
];

const ALL_STATUSES: ComplianceRecordStatus[] = [
  "Not Started", "Awaiting Documents", "In Progress", "Ready For Review", "Ready To File", "Filed", "Overdue"
];
const ALL_TYPES: ComplianceRecordType[] = ["GST", "Income Tax", "TDS", "MCA", "Payroll", "Bookkeeping"];

export default function CompliancePage() {
  const [statusFilter, setStatusFilter] = useState<ComplianceRecordStatus | "">("");
  const [typeFilter, setTypeFilter] = useState<ComplianceRecordType | "">("");
  const [clientFilter, setClientFilter] = useState("");

  const filtered = MOCK_RECORDS.filter((r) => {
    if (statusFilter && r.status !== statusFilter) return false;
    if (typeFilter && r.compliance_type !== typeFilter) return false;
    if (clientFilter && !r.client_name?.toLowerCase().includes(clientFilter.toLowerCase())) return false;
    return true;
  });

  // Stat cards — computed from mock data
  const dueThisWeek = MOCK_RECORDS.filter((r) => r.status !== "Filed" && r.due_date >= "2026-06-01" && r.due_date <= "2026-06-08").length;
  const overdue = MOCK_RECORDS.filter((r) => r.status === "Overdue").length;
  const readyForReview = MOCK_RECORDS.filter((r) => r.status === "Ready For Review").length;
  const readyToFile = MOCK_RECORDS.filter((r) => r.status === "Ready To File").length;
  const filedThisMonth = MOCK_RECORDS.filter((r) => r.status === "Filed").length;

  const STATS = [
    { label: "Due This Week", value: dueThisWeek, icon: Clock, color: "text-amber-600", bg: "bg-amber-50" },
    { label: "Overdue", value: overdue, icon: AlertTriangle, color: "text-red-600", bg: "bg-red-50" },
    { label: "Ready For Review", value: readyForReview, icon: FileText, color: "text-orange-600", bg: "bg-orange-50" },
    { label: "Ready To File", value: readyToFile, icon: Shield, color: "text-purple-600", bg: "bg-purple-50" },
    { label: "Filed", value: filedThisMonth, icon: CheckCircle, color: "text-green-600", bg: "bg-green-50" },
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
