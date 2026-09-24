"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  Play, Pause, CheckCircle2, Search, Zap, RefreshCw, Activity,
} from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/services/formatting";
import { ATTENTION, BRAND, BRAND_SURFACE, HINT, MUTED, PROBLEM, READY } from "@/lib/design/tokens";
import { objectWithLists } from "@/lib/api/shape";

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

function StatCard({ label, value, sub, color = BRAND }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div className="bg-white border border-ps-border rounded-xl p-4 flex flex-col gap-1">
      <span className="text-xs text-ps-label font-medium uppercase tracking-wide">{label}</span>
      <span className="text-2xl font-bold" style={{ color }}>{value}</span>
      {sub && <span className="text-xs text-ps-hint">{sub}</span>}
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
  // Distinguishes "fetch failed" from "no workflows exist" — a masked
  // failure previously rendered "No workflows found — Create a workflow to
  // start automating," which is false when the fetch simply failed.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);
  const [toggleError, setToggleError] = useState<string | null>(null);
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
      setAnalytics(objectWithLists<WorkflowAnalytics>(analyticsRes.data, "by_template") || null);
      setLoadError(null);
    } catch (e) {
      setTemplates([]);
      setLoadError(e instanceof Error ? e.message : "Couldn't load workflows. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [search, category]);

  useEffect(() => { load(); }, [load]);

  const toggle = async (id: string) => {
    setToggling(id);
    setToggleError(null);
    try {
      await api.workflowEngine.toggleTemplate(id);
      setTemplates((prev: WorkflowTemplate[]) => prev.map((t: WorkflowTemplate) => t.id === id ? { ...t, is_active: !t.is_active } : t));
    } catch (e) {
      setToggleError(e instanceof Error ? e.message : "Couldn't update the workflow. Please try again.");
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
    <div className="min-h-screen bg-ps-bg">
      {/* Header */}
      <div className="bg-white border-b border-ps-border px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-brand">Workflow Automation</h1>
            <p className="text-sm text-ps-label mt-0.5">Automate firm operations across compliance, onboarding, and more</p>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/workflows/approvals"
              className="flex items-center gap-1.5 px-3 py-2 text-sm border border-ps-border rounded-lg bg-white hover:bg-ps-bg text-ps-label"
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
              className="flex items-center gap-1.5 px-3 py-2 text-sm border border-ps-border rounded-lg bg-white hover:bg-ps-bg text-ps-label"
            >
              <RefreshCw size={14} />
              Refresh
            </button>
            {/* "New Workflow" button removed — it had no handler (dead button) and no
                builder flow exists yet. Re-add wired to a builder when implemented. */}
          </div>
        </div>
      </div>

      <div className="px-6 py-6 max-w-ps-data mx-auto space-y-6">

        {/* Summary stats */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <StatCard label="Total Workflows" value={summary?.total_templates ?? 0} />
          <StatCard label="Total Executions" value={summary?.total_executions ?? 0} sub="all time" />
          <StatCard label="Success Rate" value={`${summary?.overall_success_rate ?? 0}%`} color={READY} />
          <StatCard label="Pending Approvals" value={summary?.pending_approvals ?? 0} color={ATTENTION} />
          <StatCard label="Unresolved Failures" value={summary?.unresolved_failures ?? 0} color={PROBLEM} />
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-ps-border">
          {(["templates", "instances", "analytics"] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 text-sm font-medium capitalize border-b-2 transition-colors ${
                tab === t
                  ? "border-brand text-brand"
                  : "border-transparent text-ps-label hover:text-ps-body"
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
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ps-hint" />
              <input
                type="text"
                placeholder="Search workflows..."
                value={search}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
                className="w-full pl-9 pr-3 py-2 text-sm border border-ps-border rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-brand/20"
              />
            </div>
            <select
              value={category}
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setCategory(e.target.value)}
              className="px-3 py-2 text-sm border border-ps-border rounded-lg bg-white focus:outline-none"
            >
              <option value="all">All Categories</option>
              {["gst","tds","onboarding","compliance","health","relationship","lifecycle","income_tax","payroll","mca","accounting"].map(c => (
                <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1).replace("_"," ")}</option>
              ))}
            </select>
          </div>
        )}

        {/* Templates Tab */}
        {toggleError && (
          <div role="alert" className="mb-3 flex items-center justify-between gap-2 bg-state-problem-surface border border-state-problem-border rounded-lg px-3 py-2">
            <p className="text-xs text-state-problem">{toggleError}</p>
            <button onClick={() => setToggleError(null)} className="text-xs text-state-problem hover:underline shrink-0">Dismiss</button>
          </div>
        )}
        {tab === "templates" && (
          loading ? (
            <div className="text-center py-16 text-ps-hint">Loading workflows...</div>
          ) : loadError ? (
            <div className="text-center py-16">
              <p className="text-sm text-red-600 font-medium">{loadError}</p>
              <button onClick={() => load()} className="mt-3 text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg">Retry</button>
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-16">
              <Zap size={40} className="mx-auto text-ps-disabled mb-3" />
              <p className="text-ps-label">No workflows found</p>
              <p className="text-sm text-ps-hint mt-1">Create a workflow to start automating</p>
            </div>
          ) : (
            <div className="grid gap-4">
              {filtered.map((template: WorkflowTemplate) => {
                const analyticsRow = analytics?.by_template?.find((a: WorkflowAnalytics["by_template"][number]) => a.template_id === template.id);
                return (
                  <div key={template.id} className="bg-white border border-ps-border rounded-xl p-5 hover:shadow-sm transition-shadow">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex items-start gap-3 flex-1 min-w-0">
                        <div className="mt-0.5 w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                          style={{ backgroundColor: template.is_active ? BRAND_SURFACE : MUTED }}>
                          <Zap size={16} style={{ color: template.is_active ? BRAND : HINT }} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-semibold text-brand text-sm">{template.name}</span>
                            {template.is_system && (
                              <span className="text-3xs bg-[#EFF6FF] text-brand px-2 py-0.5 rounded-full font-medium">SYSTEM</span>
                            )}
                            <span className={`text-3xs px-2 py-0.5 rounded-full font-medium ${CATEGORY_COLORS[template.category] || CATEGORY_COLORS.general}`}>
                              {template.category.toUpperCase().replace("_", " ")}
                            </span>
                          </div>
                          {template.description && (
                            <p className="text-xs text-ps-label mt-1 line-clamp-1">{template.description}</p>
                          )}
                          <div className="flex items-center gap-4 mt-2 text-xs text-ps-hint">
                            <span className="flex items-center gap-1">
                              <Activity size={11} />
                              Trigger: <strong className="text-ps-label">{TRIGGER_LABELS[template.trigger_type] || template.trigger_type}</strong>
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
                              : "bg-ps-muted text-ps-label border-ps-border hover:bg-ps-border"
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
            <div className="overflow-hidden rounded-xl border border-ps-border bg-white">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-ps-border bg-ps-bg">
                    {["Workflow", "Total Runs", "Successful", "Failed", "Success Rate", "Avg Duration", "Last 7 Days"].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-ps-label uppercase tracking-wide">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {analytics.by_template.map((row: WorkflowAnalytics["by_template"][number], i: number) => (
                    <tr key={row.template_id} className={`border-b border-ps-muted hover:bg-ps-bg ${i % 2 === 0 ? "" : "bg-ps-bg"}`}>
                      <td className="px-4 py-3 font-medium text-brand">{row.template_name}</td>
                      <td className="px-4 py-3 text-ps-body">{row.total_executions}</td>
                      <td className="px-4 py-3 text-green-600 font-medium">{row.successful}</td>
                      <td className="px-4 py-3 text-red-600 font-medium">{row.failed}</td>
                      <td className="px-4 py-3">
                        <span className={`font-semibold ${row.success_rate >= 90 ? "text-green-600" : row.success_rate >= 70 ? "text-amber-600" : "text-red-600"}`}>
                          {row.success_rate}%
                        </span>
                      </td>
                      <td className="px-4 py-3 text-ps-label">
                        {fmtDuration(templates.find((t: WorkflowTemplate) => t.id === row.template_id)?.avg_duration_ms)}
                      </td>
                      <td className="px-4 py-3 text-ps-body">{row.executions_last_7_days}</td>
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
  // Distinguishes "fetch failed" from "no runs yet" — a masked failure
  // previously rendered "No workflow runs found" identically to a
  // genuinely empty instance log.
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (status !== "all") params.status = status;
      const res = (await api.workflowEngine.listInstances(params)) as { data: { instances: WorkflowInstance[] } };
      setInstances(res.data?.instances || []);
      setLoadError(null);
    } catch (e) {
      setInstances([]);
      setLoadError(e instanceof Error ? e.message : "Couldn't load workflow runs. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => { load(); }, [load]);

  const STATUS_STYLES: Record<string, string> = {
    completed: "bg-state-ready-surface text-state-ready",
    failed: "bg-state-problem-surface text-state-problem",
    running: "bg-state-working-surface text-state-working",
    pending: "bg-gray-100 text-gray-600",
    cancelled: "bg-state-done-surface text-state-done",
    waiting_approval: "bg-state-attention-surface text-state-attention",
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <select
          value={status}
          onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setStatus(e.target.value)}
          className="px-3 py-2 text-sm border border-ps-border rounded-lg bg-white"
        >
          <option value="all">All Statuses</option>
          {["pending","running","completed","failed","cancelled","waiting_approval"].map(s => (
            <option key={s} value={s}>{s.replace("_"," ")}</option>
          ))}
        </select>
      </div>
      {loading ? (
        <div className="text-center py-12 text-ps-hint">Loading...</div>
      ) : loadError ? (
        <div className="text-center py-12">
          <p className="text-sm text-red-600 font-medium">{loadError}</p>
          <button onClick={() => load()} className="mt-3 text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg">Retry</button>
        </div>
      ) : instances.length === 0 ? (
        <div className="text-center py-12 text-ps-hint">No workflow runs found</div>
      ) : (
        <div className="bg-white border border-ps-border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ps-border bg-ps-bg">
                {["Instance ID", "Trigger", "Status", "Started", "Duration"].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-ps-label uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {instances.map((inst: WorkflowInstance) => (
                <tr key={inst.id} className="border-b border-ps-muted hover:bg-ps-bg">
                  <td className="px-4 py-3 font-mono text-xs text-ps-label">{inst.id.slice(0,12)}...</td>
                  <td className="px-4 py-3 text-ps-body">{TRIGGER_LABELS[inst.trigger_event] || inst.trigger_event}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium capitalize ${STATUS_STYLES[inst.status] || "bg-gray-100 text-gray-600"}`}>
                      {inst.status.replace("_"," ")}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-ps-label text-xs">{formatDateTime(inst.started_at)}</td>
                  <td className="px-4 py-3 text-ps-label text-xs">
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

