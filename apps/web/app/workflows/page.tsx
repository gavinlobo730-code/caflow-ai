"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  Play, Pause, CheckCircle2, Search, Zap, RefreshCw, Activity,
} from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/services/formatting";

// ── Types ────────────────────────────────────────────────────────────────────

interface WorkflowTemplate {
  id: string;
  name: string;
  description?: string;
  category: string;
  trigger_type: string;
  is_active: boolean;
  is_system: boolean;
  execution_count: number;
  success_count: number;
  failure_count: number;
  avg_duration_ms?: number;
  created_at: string;
  updated_at: string;
}

interface WorkflowInstance {
  id: string;
  template_id: string;
  trigger_event: string;
  status: string;
  started_at?: string;
  completed_at?: string;
}

interface WorkflowAnalytics {
  summary: {
    total_templates: number;
    total_executions: number;
    overall_success_rate: number;
    pending_approvals: number;
    unresolved_failures: number;
  };
  by_template: Array<{
    template_id: string;
    template_name: string;
    total_executions: number;
    successful: number;
    failed: number;
    success_rate: number;
    pending_approvals: number;
    executions_last_7_days: number;
  }>;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const CATEGORY_COLORS: Record<string, string> = {
  gst:          "bg-green-100 text-green-700",
  tds:          "bg-blue-100 text-blue-700",
  onboarding:   "bg-purple-100 text-purple-700",
  compliance:   "bg-orange-100 text-orange-700",
  health:       "bg-pink-100 text-pink-700",
  relationship: "bg-cyan-100 text-cyan-700",
  lifecycle:    "bg-indigo-100 text-indigo-700",
  income_tax:   "bg-yellow-100 text-yellow-700",
  payroll:      "bg-teal-100 text-teal-700",
  mca:          "bg-rose-100 text-rose-700",
  accounting:   "bg-slate-100 text-slate-700",
  general:      "bg-gray-100 text-gray-600",
};

const TRIGGER_LABELS: Record<string, string> = {
  gst_due: "GST Due",
  tds_due: "TDS Due",
  itr_due: "ITR Due",
  roc_due: "ROC Due",
  client_created: "Client Created",
  client_archived: "Client Archived",
  client_health_changed: "Health Changed",
  client_risk_detected: "Risk Detected",
  lead_created: "Lead Created",
  proposal_sent: "Proposal Sent",
  onboarding_started: "Onboarding Started",
  onboarding_completed: "Onboarding Completed",
  renewal_due: "Renewal Due",
  relationship_created: "Relationship Created",
  conflict_detected: "Conflict Detected",
  ownership_changed: "Ownership Changed",
  health_score_below_threshold: "Low Health Score",
  health_alert_created: "Health Alert",
  ai_risk_detected: "AI Risk Detected",
  ai_opportunity_detected: "AI Opportunity",
  scheduled: "Scheduled",
};

function fmtDuration(ms?: number): string {
  if (!ms) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${Math.round(ms / 1000)}s`;
  if (ms < 3600000) return `${Math.round(ms / 60000)}m`;
  return `${Math.round(ms / 3600000)}h`;
}

function StatCard({ label, value, sub, color = "#182350" }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-xl p-4 flex flex-col gap-1">
      <span className="text-xs text-[#64748B] font-medium uppercase tracking-wide">{label}</span>
      <span className="text-2xl font-bold" style={{ color }}>{value}</span>
      {sub && <span className="text-xs text-[#94A3B8]">{sub}</span>}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function WorkflowsPage() {
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [analytics, setAnalytics] = useState<WorkflowAnalytics | null>(null);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState<string | null>(null);
  const [tab, setTab] = useState<"templates" | "instances" | "analytics">("templates");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (category !== "all") params.category = category;
      if (search) params.search = search;
      const [tplRes, analyticsRes] = await Promise.all([
        api.workflowEngine.listTemplates(params) as Promise<{ data: { templates: WorkflowTemplate[] } }>,
        api.workflowEngine.analytics() as Promise<{ data: WorkflowAnalytics }>,
      ]);
      setTemplates(tplRes.data?.templates || []);
      setAnalytics(analyticsRes.data || null);
    } catch {
      setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, [search, category]);

  useEffect(() => { load(); }, [load]);

  const toggle = async (id: string) => {
    setToggling(id);
    try {
      await api.workflowEngine.toggleTemplate(id);
      setTemplates((prev: WorkflowTemplate[]) => prev.map((t: WorkflowTemplate) => t.id === id ? { ...t, is_active: !t.is_active } : t));
    } finally {
      setToggling(null);
    }
  };

  const filtered = templates.filter((t: WorkflowTemplate) => {
    const q = search.toLowerCase();
    return !q || t.name.toLowerCase().includes(q) || (t.description || "").toLowerCase().includes(q);
  });

  const summary = analytics?.summary;

  return (
    <div className="min-h-screen bg-[#F8FAFC]">
      {/* Header */}
      <div className="bg-white border-b border-[#E2E8F0] px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-[#182350]">Workflow Automation</h1>
            <p className="text-sm text-[#64748B] mt-0.5">Automate firm operations across compliance, onboarding, and more</p>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/workflows/approvals"
              className="flex items-center gap-1.5 px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg bg-white hover:bg-[#F8FAFC] text-[#475569]"
            >
              <CheckCircle2 size={14} />
              Approvals
              {summary?.pending_approvals ? (
                <span className="ml-1 bg-orange-500 text-white text-xs rounded-full px-1.5 py-0.5 font-semibold">
                  {summary.pending_approvals}
                </span>
              ) : null}
            </Link>
            <button
              onClick={load}
              className="flex items-center gap-1.5 px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg bg-white hover:bg-[#F8FAFC] text-[#475569]"
            >
              <RefreshCw size={14} />
              Refresh
            </button>
            {/* "New Workflow" button removed — it had no handler (dead button) and no
                builder flow exists yet. Re-add wired to a builder when implemented. */}
          </div>
        </div>
      </div>

      <div className="px-6 py-6 max-w-[1400px] mx-auto space-y-6">

        {/* Summary stats */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <StatCard label="Total Workflows" value={summary?.total_templates ?? 0} />
          <StatCard label="Total Executions" value={summary?.total_executions ?? 0} sub="all time" />
          <StatCard label="Success Rate" value={`${summary?.overall_success_rate ?? 0}%`} color="#16A34A" />
          <StatCard label="Pending Approvals" value={summary?.pending_approvals ?? 0} color="#D97706" />
          <StatCard label="Unresolved Failures" value={summary?.unresolved_failures ?? 0} color="#DC2626" />
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-[#E2E8F0]">
          {(["templates", "instances", "analytics"] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 text-sm font-medium capitalize border-b-2 transition-colors ${
                tab === t
                  ? "border-[#182350] text-[#182350]"
                  : "border-transparent text-[#64748B] hover:text-[#334155]"
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Filters */}
        {tab === "templates" && (
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
              <input
                type="text"
                placeholder="Search workflows..."
                value={search}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
                className="w-full pl-9 pr-3 py-2 text-sm border border-[#E2E8F0] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#182350]/20"
              />
            </div>
            <select
              value={category}
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setCategory(e.target.value)}
              className="px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg bg-white focus:outline-none"
            >
              <option value="all">All Categories</option>
              {["gst","tds","onboarding","compliance","health","relationship","lifecycle","income_tax","payroll","mca","accounting"].map(c => (
                <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1).replace("_"," ")}</option>
              ))}
            </select>
          </div>
        )}

        {/* Templates Tab */}
        {tab === "templates" && (
          loading ? (
            <div className="text-center py-16 text-[#94A3B8]">Loading workflows...</div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-16">
              <Zap size={40} className="mx-auto text-[#CBD5E1] mb-3" />
              <p className="text-[#64748B]">No workflows found</p>
              <p className="text-sm text-[#94A3B8] mt-1">Create a workflow to start automating</p>
            </div>
          ) : (
            <div className="grid gap-4">
              {filtered.map((template: WorkflowTemplate) => {
                const analyticsRow = analytics?.by_template.find((a: WorkflowAnalytics["by_template"][number]) => a.template_id === template.id);
                return (
                  <div key={template.id} className="bg-white border border-[#E2E8F0] rounded-xl p-5 hover:shadow-sm transition-shadow">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex items-start gap-3 flex-1 min-w-0">
                        <div className="mt-0.5 w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                          style={{ backgroundColor: template.is_active ? "#EFF6FF" : "#F1F5F9" }}>
                          <Zap size={16} style={{ color: template.is_active ? "#182350" : "#94A3B8" }} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-semibold text-[#182350] text-sm">{template.name}</span>
                            {template.is_system && (
                              <span className="text-[10px] bg-[#EFF6FF] text-[#182350] px-2 py-0.5 rounded-full font-medium">SYSTEM</span>
                            )}
                            <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${CATEGORY_COLORS[template.category] || CATEGORY_COLORS.general}`}>
                              {template.category.toUpperCase().replace("_", " ")}
                            </span>
                          </div>
                          {template.description && (
                            <p className="text-xs text-[#64748B] mt-1 line-clamp-1">{template.description}</p>
                          )}
                          <div className="flex items-center gap-4 mt-2 text-xs text-[#94A3B8]">
                            <span className="flex items-center gap-1">
                              <Activity size={11} />
                              Trigger: <strong className="text-[#475569]">{TRIGGER_LABELS[template.trigger_type] || template.trigger_type}</strong>
                            </span>
                            <span>{analyticsRow?.total_executions ?? template.execution_count} executions</span>
                            {analyticsRow && analyticsRow.total_executions > 0 && (
                              <span className={analyticsRow.success_rate >= 90 ? "text-green-600" : analyticsRow.success_rate >= 70 ? "text-amber-600" : "text-red-600"}>
                                {analyticsRow.success_rate}% success
                              </span>
                            )}
                            <span>Avg: {fmtDuration(template.avg_duration_ms)}</span>
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 flex-shrink-0">
                        {analyticsRow?.pending_approvals ? (
                          <span className="text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded-full font-medium">
                            {analyticsRow.pending_approvals} pending
                          </span>
                        ) : null}
                        {/* Toggle active */}
                        <button
                          onClick={() => toggle(template.id)}
                          disabled={toggling === template.id || template.is_system}
                          className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border font-medium transition-colors ${
                            template.is_active
                              ? "bg-green-50 text-green-700 border-green-200 hover:bg-green-100"
                              : "bg-[#F1F5F9] text-[#64748B] border-[#E2E8F0] hover:bg-[#E2E8F0]"
                          } ${template.is_system ? "opacity-50 cursor-not-allowed" : ""}`}
                          title={template.is_system ? "System workflows cannot be toggled" : undefined}
                        >
                          {template.is_active ? <><Play size={11} /> Active</> : <><Pause size={11} /> Inactive</>}
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )
        )}

        {/* Analytics Tab */}
        {tab === "analytics" && analytics && (
          <div className="space-y-4">
            <div className="overflow-hidden rounded-xl border border-[#E2E8F0] bg-white">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#E2E8F0] bg-[#F8FAFC]">
                    {["Workflow", "Total Runs", "Successful", "Failed", "Success Rate", "Avg Duration", "Last 7 Days"].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-[#64748B] uppercase tracking-wide">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {analytics.by_template.map((row: WorkflowAnalytics["by_template"][number], i: number) => (
                    <tr key={row.template_id} className={`border-b border-[#F1F5F9] hover:bg-[#FAFBFD] ${i % 2 === 0 ? "" : "bg-[#FAFBFD]"}`}>
                      <td className="px-4 py-3 font-medium text-[#182350]">{row.template_name}</td>
                      <td className="px-4 py-3 text-[#334155]">{row.total_executions}</td>
                      <td className="px-4 py-3 text-green-600 font-medium">{row.successful}</td>
                      <td className="px-4 py-3 text-red-600 font-medium">{row.failed}</td>
                      <td className="px-4 py-3">
                        <span className={`font-semibold ${row.success_rate >= 90 ? "text-green-600" : row.success_rate >= 70 ? "text-amber-600" : "text-red-600"}`}>
                          {row.success_rate}%
                        </span>
                      </td>
                      <td className="px-4 py-3 text-[#64748B]">
                        {fmtDuration(templates.find((t: WorkflowTemplate) => t.id === row.template_id)?.avg_duration_ms)}
                      </td>
                      <td className="px-4 py-3 text-[#334155]">{row.executions_last_7_days}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Instances Tab */}
        {tab === "instances" && <WorkflowInstancesTab />}
      </div>
    </div>
  );
}

function WorkflowInstancesTab() {
  const [instances, setInstances] = useState<WorkflowInstance[]>([]);
  const [status, setStatus] = useState("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const params: Record<string, string> = {};
        if (status !== "all") params.status = status;
        const res = (await api.workflowEngine.listInstances(params)) as { data: { instances: WorkflowInstance[] } };
        setInstances(res.data?.instances || []);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [status]);

  const STATUS_STYLES: Record<string, string> = {
    completed: "bg-green-100 text-green-700",
    failed: "bg-red-100 text-red-700",
    running: "bg-blue-100 text-blue-700",
    pending: "bg-gray-100 text-gray-600",
    cancelled: "bg-gray-100 text-gray-500",
    waiting_approval: "bg-orange-100 text-orange-700",
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <select
          value={status}
          onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setStatus(e.target.value)}
          className="px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg bg-white"
        >
          <option value="all">All Statuses</option>
          {["pending","running","completed","failed","cancelled","waiting_approval"].map(s => (
            <option key={s} value={s}>{s.replace("_"," ")}</option>
          ))}
        </select>
      </div>
      {loading ? (
        <div className="text-center py-12 text-[#94A3B8]">Loading...</div>
      ) : instances.length === 0 ? (
        <div className="text-center py-12 text-[#94A3B8]">No workflow runs found</div>
      ) : (
        <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#E2E8F0] bg-[#F8FAFC]">
                {["Instance ID", "Trigger", "Status", "Started", "Duration"].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-[#64748B] uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {instances.map((inst: WorkflowInstance) => (
                <tr key={inst.id} className="border-b border-[#F1F5F9] hover:bg-[#FAFBFD]">
                  <td className="px-4 py-3 font-mono text-xs text-[#475569]">{inst.id.slice(0,12)}...</td>
                  <td className="px-4 py-3 text-[#334155]">{TRIGGER_LABELS[inst.trigger_event] || inst.trigger_event}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium capitalize ${STATUS_STYLES[inst.status] || "bg-gray-100 text-gray-600"}`}>
                      {inst.status.replace("_"," ")}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[#64748B] text-xs">{formatDateTime(inst.started_at)}</td>
                  <td className="px-4 py-3 text-[#64748B] text-xs">
                    {inst.completed_at && inst.started_at
                      ? fmtDuration(new Date(inst.completed_at).getTime() - new Date(inst.started_at).getTime())
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

