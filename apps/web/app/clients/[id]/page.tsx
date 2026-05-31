"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  FileText, AlertTriangle, CheckCircle, Clock, Bot,
  ChevronRight, Building2, Mail, Phone, MapPin, Calendar,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { ClientWorkspace, ComplianceTask, AIInsight } from "@/lib/types";
import { statusColor, priorityColor, formatDueDateLabel } from "@/lib/services/compliance";
import { formatRelativeTime, formatDate, ENTITY_TYPE_LABELS } from "@/lib/services/formatting";

// Mock workspace data for client c-001 (Sharma Enterprises)
// Wire to api.clients.getWorkspace(id) once backend is running
const MOCK_WORKSPACE: ClientWorkspace = {
  profile: {
    id: "c-001",
    client_name: "Sharma Enterprises",
    entity_type: "Proprietorship",
    pan: "AABCS1429B",
    gstin: "27AABCS1429B1ZB",
    mobile: "+91 98765 43210",
    email: "sharma@sharmaenterprises.in",
    address_line1: "12, MG Road",
    city: "Mumbai",
    state: "Maharashtra",
    pincode: "400001",
    state_code: "27",
    gst_filing_frequency: "monthly",
    status: "active",
    created_at: new Date(Date.now() - 180 * 86400000).toISOString(),
  },
  compliance_tasks: [
    { id: "ct-001", client_id: "c-001", compliance_type: "GSTR1", period_start: "2025-04-01", period_end: "2025-04-30", due_date: new Date(Date.now() + 3 * 86400000).toISOString().split("T")[0], status: "pending", priority: "critical", days_remaining: 3, assigned_to: "tm-001" },
    { id: "ct-002", client_id: "c-001", compliance_type: "GSTR3B", period_start: "2025-04-01", period_end: "2025-04-30", due_date: new Date(Date.now() + 18 * 86400000).toISOString().split("T")[0], status: "pending", priority: "medium", days_remaining: 18, assigned_to: "tm-001" },
  ],
  upcoming_deadlines: [
    { id: "ct-001", client_id: "c-001", compliance_type: "GSTR1", period_start: "2025-04-01", period_end: "2025-04-30", due_date: new Date(Date.now() + 3 * 86400000).toISOString().split("T")[0], status: "pending", priority: "critical", days_remaining: 3, assigned_to: "tm-001" },
  ],
  documents: [
    { id: "doc-001", client_id: "c-001", document_type: "GST_INVOICE", file_name: "invoice_march_2024.pdf", file_path: "/uploads/c-001/invoice_march_2024.pdf", financial_year: "2024-25", review_status: "approved", confidence_score: 0.97, upload_date: new Date(Date.now() - 5 * 86400000).toISOString() },
    { id: "doc-002", client_id: "c-001", document_type: "FORM16", file_name: "form16_2024_25.pdf", file_path: "/uploads/c-001/form16_2024_25.pdf", financial_year: "2024-25", review_status: "pending_review", confidence_score: 0.91, upload_date: new Date(Date.now() - 2 * 86400000).toISOString() },
  ],
  recent_activity: [
    { id: "al-001", client_id: "c-001", actor_id: "tm-001", action: "document_uploaded", description: "GST invoice uploaded: invoice_march_2024.pdf", entity_type: "document", entity_id: "doc-001", created_at: new Date(Date.now() - 5 * 86400000).toISOString() },
    { id: "al-002", client_id: "c-001", actor_id: "tm-001", action: "compliance_task_created", description: "GSTR-1 task created for current period", entity_type: "compliance_task", entity_id: "ct-001", created_at: new Date(Date.now() - 10 * 86400000).toISOString() },
    { id: "al-003", client_id: "c-001", actor_id: "tm-001", action: "reminder_sent", description: "WhatsApp compliance reminder sent", entity_type: undefined, entity_id: undefined, created_at: new Date(Date.now() - 86400000).toISOString() },
  ],
  ai_insights: [
    { id: "ai-001", client_id: "c-001", insight_type: "DEADLINE_APPROACHING", severity: "high", title: "GSTR-1 due in 3 days", description: "GSTR-1 for the current period is approaching. Filing not yet initiated.", recommended_action: "Begin GSTR-1 preparation immediately. Reconcile sales invoices.", status: "open", created_at: new Date().toISOString() },
  ],
  summary: {
    total_tasks: 2,
    overdue_count: 0,
    pending_count: 2,
    filed_count: 0,
    document_count: 2,
    open_insights: 1,
  },
};

const severityColor: Record<string, string> = {
  critical: "bg-red-100 text-red-800 border-red-200",
  high: "bg-orange-100 text-orange-800 border-orange-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  low: "bg-blue-100 text-blue-800 border-blue-200",
  info: "bg-gray-100 text-gray-800 border-gray-200",
};

const reviewBadge: Record<string, string> = {
  approved: "bg-green-100 text-green-700",
  pending_review: "bg-amber-100 text-amber-700",
  rejected: "bg-red-100 text-red-700",
};

function SummaryCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className={`rounded-lg px-4 py-3 ${color}`}>
      <p className="text-2xl font-bold">{value}</p>
      <p className="text-xs mt-0.5 opacity-80">{label}</p>
    </div>
  );
}

function ComplianceRow({ task }: { task: ComplianceTask }) {
  return (
    <div className="flex items-center gap-3 py-3 border-b border-gray-50 last:border-0">
      <div className="flex-1">
        <p className="text-sm font-medium text-gray-900">{task.compliance_type}</p>
        <p className="text-xs text-gray-500 mt-0.5">
          {formatDate(task.period_start)} — {formatDate(task.period_end)}
        </p>
      </div>
      <div className="text-right">
        <p className="text-xs text-gray-500">{formatDueDateLabel(task.days_remaining)}</p>
        <p className="text-xs text-gray-400">{formatDate(task.due_date)}</p>
      </div>
      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusColor[task.status]}`}>
        {task.status}
      </span>
      <span className={`text-xs px-2 py-0.5 rounded-full ${priorityColor[task.priority]}`}>
        {task.priority}
      </span>
    </div>
  );
}

function InsightCard({ insight }: { insight: AIInsight }) {
  return (
    <div className={`border rounded-lg p-4 ${severityColor[insight.severity]}`}>
      <div className="flex items-start gap-2">
        <Bot size={16} className="mt-0.5 shrink-0" />
        <div className="flex-1">
          <p className="text-sm font-semibold">{insight.title}</p>
          <p className="text-xs mt-1 opacity-90">{insight.description}</p>
          {insight.recommended_action && (
            <p className="text-xs mt-2 font-medium">→ {insight.recommended_action}</p>
          )}
        </div>
        <Badge variant="outline" className="text-xs shrink-0">{insight.severity}</Badge>
      </div>
    </div>
  );
}

export default function ClientWorkspacePage() {
  const params = useParams();
  const [workspace] = useState<ClientWorkspace>(MOCK_WORKSPACE);
  const { profile, summary, compliance_tasks, documents, recent_activity, ai_insights } = workspace;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-1">
            <span>Clients</span>
            <ChevronRight size={14} />
            <span className="text-gray-900 font-medium">{profile.client_name}</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">{profile.client_name}</h1>
          <div className="flex items-center gap-2 mt-1">
            <Badge variant="secondary" className="text-xs">{ENTITY_TYPE_LABELS[profile.entity_type] ?? profile.entity_type}</Badge>
            <Badge variant={profile.status === "active" ? "secondary" : "outline"} className={profile.status === "active" ? "bg-green-100 text-green-700 text-xs" : "text-xs"}>
              {profile.status}
            </Badge>
          </div>
        </div>
      </div>

      {/* Summary row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <SummaryCard label="Total Tasks" value={summary.total_tasks} color="bg-gray-100 text-gray-800" />
        <SummaryCard label="Overdue" value={summary.overdue_count} color={summary.overdue_count > 0 ? "bg-red-100 text-red-800" : "bg-gray-100 text-gray-600"} />
        <SummaryCard label="Pending" value={summary.pending_count} color="bg-amber-100 text-amber-800" />
        <SummaryCard label="Filed" value={summary.filed_count} color="bg-green-100 text-green-800" />
        <SummaryCard label="AI Insights" value={summary.open_insights} color={summary.open_insights > 0 ? "bg-blue-100 text-blue-800" : "bg-gray-100 text-gray-600"} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left column */}
        <div className="space-y-4">
          {/* Client profile */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <Building2 size={15} />
                Client Information
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div>
                <p className="text-xs text-gray-500">PAN</p>
                <p className="font-mono font-medium">{profile.pan}</p>
              </div>
              {profile.gstin && (
                <div>
                  <p className="text-xs text-gray-500">GSTIN</p>
                  <p className="font-mono font-medium">{profile.gstin}</p>
                </div>
              )}
              {profile.mobile && (
                <div className="flex items-center gap-2 text-gray-700">
                  <Phone size={13} />
                  <span>{profile.mobile}</span>
                </div>
              )}
              {profile.email && (
                <div className="flex items-center gap-2 text-gray-700">
                  <Mail size={13} />
                  <span className="truncate">{profile.email}</span>
                </div>
              )}
              {profile.city && (
                <div className="flex items-center gap-2 text-gray-700">
                  <MapPin size={13} />
                  <span>{profile.city}, {profile.state} — {profile.pincode}</span>
                </div>
              )}
              <div className="flex items-center gap-2 text-gray-700">
                <Calendar size={13} />
                <span>GST filing: {profile.gst_filing_frequency}</span>
              </div>
            </CardContent>
          </Card>

          {/* Documents */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <FileText size={15} />
                Documents ({documents.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {documents.map((doc) => (
                <div key={doc.id} className="flex items-center gap-3 py-2 border-b border-gray-50 last:border-0">
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-gray-900 truncate">{doc.file_name}</p>
                    <p className="text-xs text-gray-500">{doc.document_type} · {doc.financial_year}</p>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${reviewBadge[doc.review_status]}`}>
                    {doc.review_status === "pending_review" ? "Pending" : doc.review_status}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        {/* Right columns */}
        <div className="lg:col-span-2 space-y-4">
          {/* AI Insights */}
          {ai_insights.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Bot size={15} />
                  AI Insights
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {ai_insights.map((insight) => (
                  <InsightCard key={insight.id} insight={insight} />
                ))}
              </CardContent>
            </Card>
          )}

          {/* Compliance tasks */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <Clock size={15} />
                Compliance Tasks
              </CardTitle>
            </CardHeader>
            <CardContent>
              {compliance_tasks.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-4">No tasks</p>
              ) : (
                compliance_tasks.map((t) => <ComplianceRow key={t.id} task={t} />)
              )}
            </CardContent>
          </Card>

          {/* Activity timeline */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Recent Activity</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {recent_activity.map((log) => (
                  <div key={log.id} className="flex items-start gap-3">
                    <div className="w-1.5 h-1.5 rounded-full bg-blue-400 mt-2 shrink-0" />
                    <div className="flex-1">
                      <p className="text-sm text-gray-800">{log.description}</p>
                      <p className="text-xs text-gray-400 mt-0.5">{formatRelativeTime(log.created_at)}</p>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
