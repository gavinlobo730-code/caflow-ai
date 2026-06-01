"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import {
  FileText, Clock, Bot,
  ChevronRight, Building2, Mail, Phone, MapPin, Calendar,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { ClientWorkspace, ComplianceTask, AIInsight, ComplianceRecord, ComplianceRecordStatus, ClientHealthScore, ApiResponse, RiskItem, AIInsightV2 } from "@/lib/types";
import { statusColor, priorityColor, formatDueDateLabel } from "@/lib/services/compliance";
import { formatRelativeTime, formatDate, ENTITY_TYPE_LABELS } from "@/lib/services/formatting";

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

function LoadingSkeleton() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6 animate-pulse">
      <div className="h-8 bg-gray-200 rounded w-64" />
      <div className="grid grid-cols-5 gap-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-20 bg-gray-100 rounded-lg" />
        ))}
      </div>
      <div className="h-64 bg-gray-100 rounded-xl" />
    </div>
  );
}

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

type TabId = "overview" | "compliance" | "documents" | "activity" | "intelligence";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "compliance", label: "Compliance" },
  { id: "documents", label: "Documents" },
  { id: "activity", label: "Activity" },
  { id: "intelligence", label: "Intelligence" },
];

function healthColor(score: number): string {
  if (score > 70) return "text-green-600";
  if (score >= 40) return "text-amber-600";
  return "text-red-600";
}

function healthBg(score: number): string {
  if (score > 70) return "bg-green-50";
  if (score >= 40) return "bg-amber-50";
  return "bg-red-50";
}

export default function ClientWorkspacePage() {
  const params = useParams();
  const id = Array.isArray(params.id) ? params.id[0] : params.id;

  const [workspace, setWorkspace] = useState<ClientWorkspace | null>(null);
  const [complianceRecords, setComplianceRecords] = useState<ComplianceRecord[]>([]);
  const [health, setHealth] = useState<ClientHealthScore | null>(null);
  const [clientRisks, setClientRisks] = useState<RiskItem[]>([]);
  const [clientInsights, setClientInsights] = useState<AIInsightV2[]>([]);
  const [generatingInsights, setGeneratingInsights] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>("overview");

  useEffect(() => {
    if (!id || id === "_placeholder") return;

    async function loadData() {
      setLoading(true);
      setError(null);
      try {
        const [wsRes, crRes, hRes, risksRes, insightsRes] = await Promise.all([
          fetch(`${BASE_URL}/api/clients/${id}`).then((r) => r.json()) as Promise<ApiResponse<ClientWorkspace>>,
          fetch(`${BASE_URL}/api/compliance-records?client_id=${id}`).then((r) => r.json()) as Promise<ApiResponse<ComplianceRecord[]>>,
          fetch(`${BASE_URL}/api/compliance-records/client/${id}/health`).then((r) => r.json()) as Promise<ApiResponse<ClientHealthScore>>,
          fetch(`${BASE_URL}/api/risks/client/${id}`).then((r) => r.json()),
          fetch(`${BASE_URL}/api/ai-insights?client_id=${id}`).then((r) => r.json()),
        ]);
        if (!wsRes.success) { setError(wsRes.error ?? "Failed to load workspace"); return; }
        setWorkspace(wsRes.data);
        if (crRes.success) setComplianceRecords(crRes.data);
        if (hRes.success) setHealth(hRes.data);
        if (risksRes.success) setClientRisks(risksRes.data ?? []);
        if (insightsRes.success) setClientInsights(insightsRes.data ?? []);
      } catch {
        setError("Failed to load client workspace");
      } finally {
        setLoading(false);
      }
    }

    loadData();
  }, [id]);

  async function generateInsights() {
    if (!id) return;
    setGeneratingInsights(true);
    try {
      await fetch(`${BASE_URL}/api/ai-insights/generate/${id}`, { method: "POST" });
      const res = await fetch(`${BASE_URL}/api/ai-insights?client_id=${id}`).then((r) => r.json());
      if (res.success) setClientInsights(res.data ?? []);
    } finally {
      setGeneratingInsights(false);
    }
  }

  if (!id || id === "_placeholder") {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <p className="text-gray-500 text-sm">Loading client…</p>
      </div>
    );
  }

  if (loading) return <LoadingSkeleton />;

  if (error || !workspace) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">
          {error ?? "Client not found"}
        </div>
      </div>
    );
  }

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

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-100">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.id
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Overview tab */}
      {activeTab === "overview" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="space-y-4">
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
          </div>

          <div className="lg:col-span-2 space-y-4">
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
          </div>
        </div>
      )}

      {/* Compliance tab */}
      {activeTab === "compliance" && (
        <div className="space-y-6">
          {/* Health score */}
          {health && (
            <Card>
              <CardContent className={`pt-5 pb-4 ${healthBg(health.health_score)}`}>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-gray-500 mb-1">Client Health Score</p>
                    <p className={`text-4xl font-bold ${healthColor(health.health_score)}`}>
                      {health.health_score}<span className="text-lg font-normal">/100</span>
                    </p>
                    <p className={`text-sm font-medium mt-1 capitalize ${healthColor(health.health_score)}`}>
                      {health.risk_level} risk
                    </p>
                  </div>
                  <div className="space-y-1 text-right">
                    {health.breakdown.map((b, i) => (
                      <p key={i} className="text-xs text-gray-600">-{b.deduction} · {b.label}</p>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Compliance records grouped by type */}
          {(["GST", "Income Tax", "TDS"] as const).map((type) => {
            const records = complianceRecords.filter((r) => r.compliance_type === type);
            if (records.length === 0) return null;
            return (
              <Card key={type}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">{type}</CardTitle>
                </CardHeader>
                <CardContent className="pb-4">
                  <div className="divide-y divide-gray-50">
                    {records.map((r) => (
                      <div key={r.id} className="flex items-center gap-4 py-3">
                        <div className="flex-1">
                          <p className="text-sm font-medium text-gray-900">{r.period_label}</p>
                          <p className="text-xs text-gray-500 mt-0.5">Due: {formatDate(r.due_date)}</p>
                        </div>
                        <Badge className={`text-xs ${STATUS_COLORS[r.status]}`}>{r.status}</Badge>
                        <span className={`text-xs font-medium ${r.risk_score >= 70 ? "text-red-600" : r.risk_score >= 40 ? "text-amber-600" : "text-green-600"}`}>
                          Risk: {r.risk_score}
                        </span>
                        <button className="text-xs text-blue-600 hover:underline shrink-0">Update</button>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Documents tab */}
      {activeTab === "documents" && (
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
      )}

      {/* Activity tab */}
      {activeTab === "activity" && (
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
      )}

      {/* Intelligence tab */}
      {activeTab === "intelligence" && (
        <div className="space-y-6">
          {/* Health Score */}
          {health && (
            <Card>
              <CardContent className={`pt-5 pb-4 ${healthBg(health.health_score)}`}>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-gray-500 mb-1">Client Health Score</p>
                    <p className={`text-4xl font-bold ${healthColor(health.health_score)}`}>
                      {health.health_score}<span className="text-lg font-normal">/100</span>
                    </p>
                    <p className={`text-sm font-medium mt-1 capitalize ${healthColor(health.health_score)}`}>
                      {health.risk_level} risk
                    </p>
                  </div>
                  <div className="space-y-1 text-right">
                    {health.breakdown.map((b, i) => (
                      <p key={i} className="text-xs text-gray-600">-{b.deduction} · {b.label}</p>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Open Risks */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                Open Risks ({clientRisks.filter((r) => r.resolution_status === "open").length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              {clientRisks.filter((r) => r.resolution_status === "open").length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-4">No open risks</p>
              ) : (
                <div className="space-y-3">
                  {clientRisks.filter((r) => r.resolution_status === "open").map((risk) => (
                    <div key={risk.id} className={`border rounded-lg p-4 ${severityColor[risk.severity]}`}>
                      <div className="flex items-start gap-2 justify-between">
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <Badge variant="outline" className="text-xs">{risk.severity}</Badge>
                            <span className="text-xs text-gray-500">{risk.category.replace(/_/g, " ")}</span>
                          </div>
                          <p className="text-sm font-semibold">{risk.title}</p>
                          <p className="text-xs mt-1 opacity-90">{risk.description}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* AI Insights */}
          <Card>
            <CardHeader className="pb-3 flex flex-row items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-2">
                <Bot size={15} />
                AI Insights ({clientInsights.length})
              </CardTitle>
              <button
                onClick={generateInsights}
                disabled={generatingInsights}
                className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5"
              >
                {generatingInsights ? "Generating…" : "Generate Insights"}
              </button>
            </CardHeader>
            <CardContent>
              {clientInsights.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-4">No insights yet. Click &quot;Generate Insights&quot; to analyse this client.</p>
              ) : (
                <div className="space-y-3">
                  {clientInsights.map((insight) => (
                    <div key={insight.id} className={`border rounded-lg p-4 ${severityColor[insight.severity]}`}>
                      <div className="flex items-start gap-2">
                        <Bot size={16} className="mt-0.5 shrink-0" />
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <Badge variant="outline" className="text-xs">{insight.severity}</Badge>
                            <span className="text-xs text-gray-500 capitalize">{insight.category}</span>
                          </div>
                          <p className="text-sm font-semibold">{insight.title}</p>
                          <p className="text-xs mt-1 opacity-90">{insight.description}</p>
                          {insight.recommendation && (
                            <p className="text-xs mt-2 font-medium">→ {insight.recommendation}</p>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
