"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  Brain,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  RefreshCw,
  User,
  TrendingUp,
  TrendingDown,
  Clock,
  ShieldAlert,
  Loader2,
  ChevronRight,
} from "lucide-react";

// ── Interfaces ────────────────────────────────────────────────────────────────

interface MemoryTrigger {
  id: string;
  client_id?: string;
  trigger_type: string;
  title: string;
  what_detected: string;
  evidence: string[];
  why_it_matters: string;
  recommended_action: string;
  confidence: number;
  severity: string;
  status: string;
  created_at: string;
}

interface ClientProfile {
  id: string;
  client_id: string;
  compliance_score: number;
  avg_response_time_days?: number;
  portal_engagement: number;
  doc_upload_reliability: number;
  recurring_issues: Array<{ type: string; count: number }>;
  missed_deadline_count: number;
  cash_flow_risk_months: string[];
  last_computed_at: string;
}

interface PatternAnomaly {
  id: string;
  client_id?: string;
  anomaly_type: string;
  metric_name: string;
  baseline_value: number;
  actual_value: number;
  deviation_pct: number;
  deviation_score: number;
  period: string;
  explanation: string;
  evidence: string[];
  status: string;
  created_at: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-red-100 text-red-700 border border-red-200",
  high: "bg-orange-100 text-orange-700 border border-orange-200",
  medium: "bg-yellow-100 text-yellow-700 border border-yellow-200",
  low: "bg-blue-100 text-blue-700 border border-blue-200",
};

const TRIGGER_TYPE_LABELS: Record<string, string> = {
  repeat_issue: "Repeat Issue",
  deadline_at_risk: "Deadline Risk",
  cash_flow_warning: "Cash Flow",
  year_end_readiness: "Year End",
  pattern_anomaly: "Anomaly",
};

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${SEVERITY_STYLES[severity] ?? "bg-slate-100 text-slate-600"}`}>
      {severity.toUpperCase()}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const color = value >= 80 ? "bg-emerald-500" : value >= 60 ? "bg-yellow-500" : "bg-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 rounded-full bg-slate-200 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="text-[11px] text-slate-500">{value}%</span>
    </div>
  );
}

// ── Tab: Triggers ─────────────────────────────────────────────────────────────

function TriggersTab() {
  const [triggers, setTriggers] = useState<MemoryTrigger[]>([]);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.memory.listTriggers({ status: "active" }) as { data: { triggers: MemoryTrigger[] } };
      setTriggers(res.data?.triggers ?? []);
    } catch {
      setTriggers([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const acknowledge = async (id: string) => {
    setActing(id);
    try {
      await api.memory.acknowledgeTrigger(id);
      setTriggers((prev) => prev.filter((t) => t.id !== id));
    } finally {
      setActing(null);
    }
  };

  const dismiss = async (id: string) => {
    setActing(id);
    try {
      await api.memory.dismissTrigger(id);
      setTriggers((prev) => prev.filter((t) => t.id !== id));
    } finally {
      setActing(null);
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center py-20">
      <Loader2 size={24} className="animate-spin text-[#182350]" />
    </div>
  );

  if (triggers.length === 0) return (
    <div className="flex flex-col items-center justify-center py-20 text-slate-400 gap-3">
      <CheckCircle2 size={40} className="text-emerald-400" />
      <p className="font-medium text-slate-500">No active memory triggers</p>
      <p className="text-sm">All patterns look healthy for your portfolio.</p>
    </div>
  );

  return (
    <div className="space-y-3">
      {triggers.map((t) => (
        <div key={t.id} className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm hover:shadow-md transition-shadow">
          <div className="flex items-start justify-between gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap mb-1">
                <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-[#AFD2FA]/30 text-[#182350]">
                  {TRIGGER_TYPE_LABELS[t.trigger_type] ?? t.trigger_type}
                </span>
                <SeverityBadge severity={t.severity} />
                <ConfidenceBar value={t.confidence} />
              </div>
              <h3 className="font-semibold text-slate-800 text-sm">{t.title}</h3>
              <p className="text-sm text-slate-500 mt-0.5">{t.what_detected}</p>
            </div>
          </div>

          {t.evidence.length > 0 && (
            <div className="mt-3 bg-slate-50 rounded-lg p-3">
              <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Evidence</p>
              <ul className="space-y-1">
                {t.evidence.map((e, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-sm text-slate-600">
                    <ChevronRight size={12} className="mt-0.5 text-slate-400 shrink-0" />
                    {e}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2">
            <div>
              <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Why it matters</p>
              <p className="text-sm text-slate-600 mt-0.5">{t.why_it_matters}</p>
            </div>
            <div>
              <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Recommended action</p>
              <p className="text-sm text-slate-600 mt-0.5">{t.recommended_action}</p>
            </div>
          </div>

          <div className="mt-4 flex items-center gap-2">
            <button
              onClick={() => acknowledge(t.id)}
              disabled={acting === t.id}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#182350] text-white text-sm font-medium hover:bg-[#1e2e6a] transition-colors disabled:opacity-50"
            >
              {acting === t.id ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
              Acknowledge
            </button>
            <button
              onClick={() => dismiss(t.id)}
              disabled={acting === t.id}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 text-sm font-medium hover:bg-slate-50 transition-colors disabled:opacity-50"
            >
              <XCircle size={13} />
              Dismiss
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Tab: Profiles ─────────────────────────────────────────────────────────────

function ProfilesTab() {
  const [profiles, setProfiles] = useState<ClientProfile[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.memory.listProfiles() as { data: { profiles: ClientProfile[] } };
        setProfiles(res.data?.profiles ?? []);
      } catch {
        setProfiles([]);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return (
    <div className="flex items-center justify-center py-20">
      <Loader2 size={24} className="animate-spin text-[#182350]" />
    </div>
  );

  if (profiles.length === 0) return (
    <div className="flex flex-col items-center justify-center py-20 text-slate-400 gap-3">
      <User size={40} className="text-slate-300" />
      <p className="font-medium text-slate-500">No client profiles yet</p>
      <p className="text-sm">Run the memory pipeline to generate profiles.</p>
    </div>
  );

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {profiles.map((p) => {
        const scoreColor =
          p.compliance_score >= 80 ? "text-emerald-600" :
          p.compliance_score >= 60 ? "text-yellow-600" : "text-red-600";
        return (
          <div key={p.id} className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-9 h-9 rounded-full bg-[#AFD2FA]/30 flex items-center justify-center">
                <User size={16} className="text-[#182350]" />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-800 truncate">{p.client_id}</p>
                <p className="text-[11px] text-slate-400">
                  Updated {new Date(p.last_computed_at).toLocaleDateString("en-IN")}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="bg-slate-50 rounded-lg p-3">
                <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Compliance</p>
                <p className={`text-xl font-bold mt-0.5 ${scoreColor}`}>{p.compliance_score.toFixed(0)}%</p>
              </div>
              <div className="bg-slate-50 rounded-lg p-3">
                <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Engagement</p>
                <p className="text-xl font-bold mt-0.5 text-[#182350]">{p.portal_engagement.toFixed(0)}%</p>
              </div>
              <div className="bg-slate-50 rounded-lg p-3">
                <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Doc Reliability</p>
                <p className="text-xl font-bold mt-0.5 text-slate-700">{p.doc_upload_reliability.toFixed(0)}%</p>
              </div>
              <div className="bg-slate-50 rounded-lg p-3">
                <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Response (days)</p>
                <p className="text-xl font-bold mt-0.5 text-slate-700">
                  {p.avg_response_time_days != null ? p.avg_response_time_days.toFixed(1) : "—"}
                </p>
              </div>
            </div>

            {p.recurring_issues.length > 0 && (
              <div className="mt-3">
                <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Recurring Issues</p>
                <div className="flex flex-wrap gap-1">
                  {p.recurring_issues.map((ri, i) => (
                    <span key={i} className="text-[11px] px-2 py-0.5 rounded-full bg-orange-100 text-orange-700 border border-orange-200">
                      {ri.type} ({ri.count}x)
                    </span>
                  ))}
                </div>
              </div>
            )}

            {p.missed_deadline_count > 0 && (
              <div className="mt-2 flex items-center gap-1.5 text-sm text-red-600">
                <AlertTriangle size={13} />
                <span>{p.missed_deadline_count} missed deadline{p.missed_deadline_count !== 1 ? "s" : ""}</span>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Tab: Anomalies ────────────────────────────────────────────────────────────

function AnomaliesTab() {
  const [anomalies, setAnomalies] = useState<PatternAnomaly[]>([]);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.memory.listAnomalies({ status: "open" }) as { data: { anomalies: PatternAnomaly[] } };
      setAnomalies(res.data?.anomalies ?? []);
    } catch {
      setAnomalies([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const markReviewed = async (id: string) => {
    setActing(id);
    try {
      await api.memory.updateAnomalyStatus(id, "reviewed");
      setAnomalies((prev) => prev.filter((a) => a.id !== id));
    } finally {
      setActing(null);
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center py-20">
      <Loader2 size={24} className="animate-spin text-[#182350]" />
    </div>
  );

  if (anomalies.length === 0) return (
    <div className="flex flex-col items-center justify-center py-20 text-slate-400 gap-3">
      <ShieldAlert size={40} className="text-slate-300" />
      <p className="font-medium text-slate-500">No open anomalies</p>
      <p className="text-sm">Pattern analysis shows no unusual deviations.</p>
    </div>
  );

  return (
    <div className="space-y-3">
      {anomalies.map((a) => {
        const isSpike = a.actual_value > a.baseline_value;
        const DeviationIcon = isSpike ? TrendingUp : TrendingDown;
        const deviationColor = isSpike ? "text-orange-600" : "text-red-600";
        return (
          <div key={a.id} className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-purple-100 text-purple-700 border border-purple-200">
                    {a.anomaly_type.replace(/_/g, " ")}
                  </span>
                  <span className="text-[11px] text-slate-400">{a.period}</span>
                </div>
                <h3 className="font-semibold text-slate-800 text-sm">{a.metric_name.replace(/_/g, " ")}</h3>
                <p className="text-sm text-slate-500 mt-0.5">{a.explanation}</p>
              </div>
              <div className={`flex items-center gap-1 font-bold text-lg ${deviationColor}`}>
                <DeviationIcon size={18} />
                {a.deviation_pct > 0 ? "+" : ""}{a.deviation_pct.toFixed(1)}%
              </div>
            </div>

            <div className="mt-3 grid grid-cols-3 gap-3">
              <div className="bg-slate-50 rounded-lg p-3 text-center">
                <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Baseline</p>
                <p className="text-lg font-bold text-slate-700 mt-0.5">{a.baseline_value.toFixed(1)}</p>
              </div>
              <div className="bg-slate-50 rounded-lg p-3 text-center">
                <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Actual</p>
                <p className={`text-lg font-bold mt-0.5 ${deviationColor}`}>{a.actual_value.toFixed(1)}</p>
              </div>
              <div className="bg-slate-50 rounded-lg p-3 text-center">
                <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Score</p>
                <p className="text-lg font-bold text-slate-700 mt-0.5">{a.deviation_score.toFixed(2)}</p>
              </div>
            </div>

            {a.evidence.length > 0 && (
              <div className="mt-3 bg-slate-50 rounded-lg p-3">
                <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Evidence</p>
                <ul className="space-y-1">
                  {a.evidence.map((e, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-sm text-slate-600">
                      <ChevronRight size={12} className="mt-0.5 text-slate-400 shrink-0" />
                      {e}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-4">
              <button
                onClick={() => markReviewed(a.id)}
                disabled={acting === a.id}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#182350] text-white text-sm font-medium hover:bg-[#1e2e6a] transition-colors disabled:opacity-50"
              >
                {acting === a.id ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
                Mark Reviewed
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

type Tab = "triggers" | "profiles" | "anomalies";

export default function MemoryPage() {
  const [activeTab, setActiveTab] = useState<Tab>("triggers");
  const [running, setRunning] = useState(false);
  const [pipelineMsg, setPipelineMsg] = useState<string | null>(null);

  const runPipeline = async () => {
    setRunning(true);
    setPipelineMsg(null);
    try {
      await api.memory.runPipeline();
      setPipelineMsg("Pipeline completed. Refresh to see updated data.");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Pipeline run failed";
      setPipelineMsg(msg);
    } finally {
      setRunning(false);
    }
  };

  const tabs: { id: Tab; label: string; icon: React.ElementType }[] = [
    { id: "triggers", label: "Triggers", icon: AlertTriangle },
    { id: "profiles", label: "Client Profiles", icon: User },
    { id: "anomalies", label: "Anomalies", icon: TrendingUp },
  ];

  return (
    <div className="min-h-screen bg-[#F8FAFC] p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6 flex-wrap gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-[#182350] flex items-center justify-center shadow">
            <Brain size={20} className="text-[#AFD2FA]" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-[#182350]">AI Memory Intelligence</h1>
            <p className="text-sm text-slate-500">Semantic memory, pattern triggers, and anomaly detection</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {pipelineMsg && (
            <p className="text-sm text-slate-600 bg-white px-3 py-1.5 rounded-lg border border-slate-200">
              {pipelineMsg}
            </p>
          )}
          <button
            onClick={runPipeline}
            disabled={running}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#182350] text-white text-sm font-medium hover:bg-[#1e2e6a] transition-colors disabled:opacity-60"
          >
            {running ? (
              <Loader2 size={15} className="animate-spin" />
            ) : (
              <RefreshCw size={15} />
            )}
            {running ? "Running..." : "Run Pipeline"}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-white border border-slate-200 rounded-xl p-1 w-fit mb-6 shadow-sm">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === id
                ? "bg-[#182350] text-white shadow"
                : "text-slate-500 hover:text-slate-700 hover:bg-slate-50"
            }`}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div>
        {activeTab === "triggers" && <TriggersTab />}
        {activeTab === "profiles" && <ProfilesTab />}
        {activeTab === "anomalies" && <AnomaliesTab />}
      </div>
    </div>
  );
}
