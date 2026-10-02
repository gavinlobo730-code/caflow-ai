"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  TrendingUp, AlertTriangle, TrendingDown, Sparkles,
  RefreshCw, DollarSign, BarChart2,
  ArrowUpRight, ArrowDownRight, ShieldAlert, Clock, Star, ListChecks,
} from "lucide-react";
import { api } from "@/lib/api";
import { objectOrNull, objectWithLists } from "@/lib/api/shape";
import { gradeForScore } from "@/lib/health/vocabulary";
import { formatDateTime, formatTime } from "@/lib/dates/format";
import { ATTENTION, BRAND, GOLD, MUTED, PROBLEM, READY } from "@/lib/design/tokens";
import { PageHeader } from "@/components/ui/page-header";

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * Every figure here is COMPUTED by `get_executive_dashboard`, or null and
 * explained. A null is "not known" and renders as "No data" — never as 0, which
 * would say "nothing is outstanding" (ai-08). The server's own header says what
 * each block refuses (`domain/practice/executive_dashboard.py`).
 */
interface ExecutiveDashboard {
  firm_id: string;
  /** True when the figures are narrowed to the caller's assigned clients. */
  scoped?: boolean;
  /** The practice's OWN fee ledger. `available: false` carries the reason. */
  revenue_insights: {
    available: boolean;
    reason?: string | null;
    outstanding_invoices?: number;
    outstanding_amount_paise?: number;
    overdue_invoices?: number;
    overdue_amount_paise?: number;
    avg_collection_days?: number | null;
    collection_basis?: { window_days: number; allocations: number; skipped: number; settled_paise: number };
  };
  capacity_insights: {
    overdue_tasks: number;
    unassigned_overdue_tasks: number;
    staff_holding_overdue: number;
    utilisation_percent: number | null;
    utilisation_note?: string;
  };
  client_risk_insights: {
    critical_clients: number;
    at_risk_clients: number;
    healthy_clients: number;
    unscored_clients?: number;
    compliance_failures: number;
  };
  churn_signals: Array<{ client_name: string; signal: string; risk: string }>;
  growth_opportunities: Array<{ type: string; description: string; count?: number; basis?: string }>;
  firm_health_summary: {
    overall_score: number | null;
    compliance_coverage: number | null;
    compliance_coverage_basis?: { due: number; filed: number; basis: string };
    active_automations: number;
    pending_approvals: number;
    critical_actions: number;
  };
  ai_summary: string;
  /** "model" only when a model wrote the sentence; "template" when it is the
   *  plain sentence built from the same figures. Absent on a backend one deploy
   *  behind, which reads as unknown — not as AI. */
  summary_source?: "model" | "template";
  model_used?: string | null;
  generated_at: string;
}

const NO_DATA = "No data";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtRupees(paise: number): string {
  const rupees = Math.floor(paise / 100);
  if (rupees >= 10000000) return `₹${(rupees / 10000000).toFixed(1)}Cr`;
  if (rupees >= 100000) return `₹${(rupees / 100000).toFixed(1)}L`;
  if (rupees >= 1000) return `₹${(rupees / 1000).toFixed(0)}K`;
  return `₹${rupees}`;
}

// The firm's figure is the average of its clients' health scores, on the same
// 0–100 scale, so it takes the SAME bands (`lib/health/vocabulary`, pinned to
// `domain/health/scoring.GRADE_BANDS`). It had a ladder of its own — 85/70/55,
// "Excellent / Good / Fair / Critical" — the third in the browser beside the
// client badge's and the engine's, so one number read three ways.
function healthColor(score: number): string {
  const band = gradeForScore(score);
  if (band === "Healthy") return READY;
  if (band === "Good" || band === "Needs Attention") return ATTENTION;
  return PROBLEM;
}

function healthLabel(score: number): string {
  return gradeForScore(score);
}

// ── Sub-components ────────────────────────────────────────────────────────────

function KPICard({ label, value, sub, icon, trend, color = BRAND }: {
  label: string; value: string | number; sub?: string;
  icon: React.ReactNode; trend?: "up" | "down" | "neutral"; color?: string;
}) {
  return (
    <div className="bg-white border border-ps-border rounded-xl p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-ps-label font-medium uppercase tracking-wide mb-1">{label}</p>
          <p className="text-2xl font-bold" style={{ color }}>{value}</p>
          {sub && <p className="text-xs text-ps-hint mt-1">{sub}</p>}
        </div>
        <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ backgroundColor: `${color}15` }}>
          {icon}
        </div>
      </div>
      {trend && trend !== "neutral" && (
        <div className={`flex items-center gap-1 mt-2 text-xs font-medium ${trend === "up" ? "text-green-600" : "text-red-600"}`}>
          {trend === "up" ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
          <span>{trend === "up" ? "Trending up" : "Needs attention"}</span>
        </div>
      )}
    </div>
  );
}

/** A score, or an empty ring that says there is none. An absent score is not a
 *  0 and not a 75 — it is the absence of one. */
function HealthRing({ score }: { score: number | null }) {
  const r = 36;
  const circ = 2 * Math.PI * r;
  const known = typeof score === "number";
  const fill = known ? (score / 100) * circ : 0;
  const color = known ? healthColor(score) : MUTED;

  return (
    <div className="relative flex items-center justify-center">
      <svg width="96" height="96" viewBox="0 0 96 96">
        <circle cx="48" cy="48" r={r} fill="none" stroke={MUTED} strokeWidth="8" />
        <circle
          cx="48" cy="48" r={r}
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={`${fill} ${circ - fill}`}
          strokeDashoffset={circ * 0.25}
          transform="rotate(-90 48 48)"
          style={{ transition: "stroke-dasharray 0.8s ease" }}
        />
      </svg>
      <div className="absolute text-center">
        {known ? (
          <>
            <p className="text-xl font-bold" style={{ color }}>{score}</p>
            <p className="text-3xs text-ps-hint">{healthLabel(score)}</p>
          </>
        ) : (
          <p className="text-xs font-medium text-ps-hint">{NO_DATA}</p>
        )}
      </div>
    </div>
  );
}

function RiskBar({ label, value, max, color }: { label: string; value: number | null; max: number; color: string }) {
  const known = typeof value === "number";
  const pct = known && max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-ps-label">{label}</span>
        <span className="font-semibold" style={{ color: known ? color : undefined }}>
          {known ? value : <span className="text-ps-hint font-normal">{NO_DATA}</span>}
        </span>
      </div>
      <div className="h-1.5 bg-ps-muted rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ExecutiveDashboardPage() {
  const [data, setData] = useState<ExecutiveDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // This row's request is in flight. These handlers had no loading state at
  // all, so the button was never disabled and a second click sent it again.
  const [rowBusy, setRowBusy] = useState(false);

  const load = async () => {
    setRowBusy(true);
    try {
    setLoading(true);
    setError(null);
    try {
      const res = (await api.copilotV2.executiveDashboard()) as { data: unknown };
      // The server returns the dashboard payload itself, cached or fresh. It
      // used to return the raw `ai_summaries` row on a cache hit, with every
      // field under `metadata`, so this reads `metadata` first and falls back to
      // the top level — kept for the redeploy window where the browser is ahead
      // of the backend, and so either shape renders. The two list fields are
      // narrowed in the same call: `objectOrNull` alone would leave them
      // `undefined` if either shape omits them.
      const payload = objectOrNull<Record<string, unknown>>(res.data);
      const dashboard = objectWithLists<ExecutiveDashboard>(
        objectOrNull(payload?.metadata) ?? payload,
        "churn_signals",
        "growth_opportunities",
      );
      setData(dashboard);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load executive dashboard");
    } finally {
      setLoading(false);
    }
  } finally { setRowBusy(false); }
  };

  useEffect(() => { load(); }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-ps-bg flex items-center justify-center">
        <div className="text-center">
          <div className="w-12 h-12 rounded-full border-2 border-brand-light border-t-brand animate-spin mx-auto mb-4" />
          <p className="text-ps-label text-sm">Reading your practice records...</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-ps-bg flex items-center justify-center">
        <div className="text-center">
          <AlertTriangle size={40} className="mx-auto text-ps-disabled mb-3" />
          <p className="text-ps-label">{error || "No data available"}</p>
          <button disabled={rowBusy} onClick={load} className="mt-4 text-sm text-brand underline">Retry</button>
        </div>
      </div>
    );
  }

  // `objectOrNull` at the setter answers whether `data` is the right KIND of
  // thing; it does not make each nested object well-formed — `{}` passes
  // straight through, same as `objectWithLists` for a list field
  // (lib/api/shape.ts). A block that arrives without its object (a partial
  // cache row, a backend one deploy behind) is NO DATA, rendered as such: this
  // used to degrade to zeroes, which read as "nothing is wrong".
  const risk = objectOrNull<ExecutiveDashboard["client_risk_insights"]>(
    data.client_risk_insights);
  const revenue = objectOrNull<ExecutiveDashboard["revenue_insights"]>(
    data.revenue_insights);
  const capacity = objectOrNull<ExecutiveDashboard["capacity_insights"]>(
    data.capacity_insights);
  const health = objectOrNull<ExecutiveDashboard["firm_health_summary"]>(
    data.firm_health_summary);
  const { churn_signals, growth_opportunities, ai_summary } = data;
  const summaryIsModel = data.summary_source === "model";

  const revenueOk = !!revenue && revenue.available === true;
  const revenueWhy = revenue?.reason ?? "The practice's fee receivables could not be read.";
  const collectionDays = revenueOk && typeof revenue?.avg_collection_days === "number"
    ? revenue.avg_collection_days : null;
  const coverage = typeof health?.compliance_coverage === "number" ? health.compliance_coverage : null;
  const totalClients = risk
    ? risk.critical_clients + risk.at_risk_clients + risk.healthy_clients
    : 0;

  return (
    <div className="min-h-screen bg-ps-bg">
      {/* Header */}
      <div className="bg-white border-b border-ps-border px-6 py-4">
        <PageHeader
          icon={
            <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ backgroundColor: BRAND }}>
              <BarChart2 size={18} className="text-white" />
            </div>
          }
          title="Executive Dashboard"
          subtitle={<>Computed from your practice records • {formatDateTime(data.generated_at)}</>}
          actions={
            <button onClick={load} disabled={loading}
              className="flex items-center gap-1.5 text-sm text-ps-label hover:text-brand border border-ps-border px-3 py-2 rounded-lg bg-white">
              <RefreshCw size={13} /> Refresh
            </button>
          }
        />
      </div>

      <div className="px-6 py-6 max-w-[1400px] mx-auto space-y-6">

        {/* A narrowed view says so, once, at the top. */}
        {data.scoped && (
          <p className="text-xs text-ps-label bg-white border border-ps-border rounded-lg px-4 py-2">
            This view covers the clients assigned to you, not the whole practice.
          </p>
        )}

        {/* Top KPI row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <KPICard
            label="Outstanding Fee Invoices"
            value={revenueOk && typeof revenue?.outstanding_amount_paise === "number"
              ? fmtRupees(revenue.outstanding_amount_paise) : NO_DATA}
            sub={revenueOk ? `${revenue?.outstanding_invoices ?? 0} invoices — the practice's own fees` : revenueWhy}
            icon={<DollarSign size={18} style={{ color: GOLD }} />}
            color={GOLD}
            trend="neutral"
          />
          <KPICard
            label="Overdue Tasks"
            value={capacity ? capacity.overdue_tasks : NO_DATA}
            sub={capacity ? `${capacity.unassigned_overdue_tasks} with nobody assigned` : undefined}
            icon={<ListChecks size={18} style={{ color: BRAND }} />}
            color={BRAND}
            trend={capacity && capacity.overdue_tasks > 0 ? "down" : "neutral"}
          />
          <KPICard
            label="At-Risk Clients"
            value={risk ? risk.at_risk_clients + risk.critical_clients : NO_DATA}
            sub={risk ? `${risk.critical_clients} critical${risk.unscored_clients ? ` • ${risk.unscored_clients} not yet scored` : ""}` : undefined}
            icon={<ShieldAlert size={18} style={{ color: PROBLEM }} />}
            color={PROBLEM}
            trend="down"
          />
          <KPICard
            label="Avg Days to Collect"
            value={collectionDays !== null ? collectionDays : NO_DATA}
            sub={collectionDays !== null && revenue?.collection_basis
              ? `weighted by amount, over the last ${revenue.collection_basis.window_days} days of receipts`
              : revenueOk ? "no fee receipts in the last 12 months" : revenueWhy}
            icon={<Clock size={18} style={{ color: ATTENTION }} />}
            color={ATTENTION}
            trend="neutral"
          />
        </div>

        {/* Middle section */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

          {/* Firm Health */}
          <div className="bg-white border border-ps-border rounded-xl p-5">
            <h3 className="font-semibold text-brand mb-4">Firm Health</h3>
            <div className="flex items-center gap-4 mb-4">
              <HealthRing score={health ? health.overall_score : null} />
              <div className="flex-1 space-y-3">
                <RiskBar label="Filed of those due this FY (%)" value={coverage} max={100} color={READY} />
                <RiskBar label="Active Automations" value={health ? health.active_automations : null} max={10} color={BRAND} />
              </div>
            </div>
            {health?.compliance_coverage_basis && coverage !== null && (
              <p className="text-3xs text-ps-hint mb-3">
                {health.compliance_coverage_basis.filed} of {health.compliance_coverage_basis.due} {health.compliance_coverage_basis.basis}
              </p>
            )}
            <div className="grid grid-cols-2 gap-2">
              <div className="bg-[#FEF3C7] rounded-lg p-2.5 text-center">
                <p className="text-lg font-bold text-state-attention">{health ? health.pending_approvals : NO_DATA}</p>
                <p className="text-3xs text-amber-600">Pending Approvals</p>
              </div>
              <div className="bg-[#FEE2E2] rounded-lg p-2.5 text-center">
                <p className="text-lg font-bold text-state-problem">{health ? health.critical_actions : NO_DATA}</p>
                <p className="text-3xs text-red-600">Critical Actions</p>
              </div>
            </div>
          </div>

          {/* Client Risk Breakdown */}
          <div className="bg-white border border-ps-border rounded-xl p-5">
            <h3 className="font-semibold text-brand mb-4">Client Portfolio Risk</h3>
            {!risk ? (
              <p className="text-sm text-ps-hint text-center py-6">{NO_DATA}</p>
            ) : (
              <>
                {totalClients > 0 && (
                  <div className="h-3 rounded-full overflow-hidden flex mb-3">
                    {[
                      { count: risk.healthy_clients, color: READY },
                      { count: risk.at_risk_clients, color: ATTENTION },
                      { count: risk.critical_clients, color: PROBLEM },
                    ].map(({ count, color }, i) => (
                      count > 0 && <div key={i} style={{ width: `${(count / totalClients) * 100}%`, backgroundColor: color }} />
                    ))}
                  </div>
                )}
                <div className="space-y-3">
                  <RiskBar label={`Healthy (${risk.healthy_clients})`} value={risk.healthy_clients} max={totalClients} color={READY} />
                  <RiskBar label={`At Risk (${risk.at_risk_clients})`} value={risk.at_risk_clients} max={totalClients} color={ATTENTION} />
                  <RiskBar label={`Critical (${risk.critical_clients})`} value={risk.critical_clients} max={totalClients} color={PROBLEM} />
                </div>
                {!!risk.unscored_clients && (
                  <p className="text-3xs text-ps-hint mt-3">
                    {risk.unscored_clients} client{risk.unscored_clients === 1 ? "" : "s"} not yet scored — counted in none of the bars above.
                  </p>
                )}
                <div className="mt-4 pt-3 border-t border-ps-border">
                  <p className="text-xs text-ps-label">
                    <span className="font-medium text-red-600">{risk.compliance_failures}</span> overdue compliance filings
                  </p>
                </div>
              </>
            )}
          </div>

          {/* Capacity — what the tasks themselves say. Utilisation is not
              computed here: it is time logged against a weekly capacity and
              the Workload screen owns it. */}
          <div className="bg-white border border-ps-border rounded-xl p-5">
            <h3 className="font-semibold text-brand mb-4">Team Workload</h3>
            {!capacity ? (
              <p className="text-sm text-ps-hint text-center py-6">{NO_DATA}</p>
            ) : (
              <>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-ps-label text-xs">Overdue tasks</span>
                    <span className="font-semibold text-red-600 text-xs">{capacity.overdue_tasks}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-ps-label text-xs">…of which nobody owns</span>
                    <span className="font-semibold text-amber-600 text-xs">{capacity.unassigned_overdue_tasks}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-ps-label text-xs">People holding the rest</span>
                    <span className="font-semibold text-brand text-xs">{capacity.staff_holding_overdue}</span>
                  </div>
                </div>
                <p className="text-xs text-ps-hint mt-4">
                  {capacity.utilisation_note ?? "Utilisation is shown on the Workload screen."}
                </p>
                <Link href="/team/workload" className="inline-block mt-2 text-xs text-brand underline">
                  Open team workload
                </Link>
              </>
            )}
          </div>
        </div>

        {/* Bottom section */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

          {/* Churn Signals */}
          <div className="bg-white border border-ps-border rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <TrendingDown size={16} className="text-state-problem" />
              <h3 className="font-semibold text-brand">Churn Signals</h3>
              <span className="ml-auto text-xs text-ps-hint">{churn_signals.length} detected</span>
            </div>
            {churn_signals.length === 0 ? (
              <p className="text-sm text-ps-hint text-center py-6">No churn signals detected</p>
            ) : (
              <div className="space-y-3">
                {churn_signals.map((sig: { client_name: string; signal: string; risk: string }, i: number) => (
                  <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-[#FFF7F7] border border-[#FEE2E2]">
                    <AlertTriangle size={14} className="text-red-400 mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="text-sm font-medium text-brand">{sig.client_name}</p>
                      <p className="text-xs text-ps-label mt-0.5">{sig.signal}</p>
                    </div>
                    <span className={`ml-auto text-3xs px-2 py-0.5 rounded-full font-semibold ${
                      sig.risk === "high" ? "bg-state-problem-surface text-state-problem" : "bg-state-attention-surface text-state-attention"
                    }`}>
                      {sig.risk.toUpperCase()}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Growth Opportunities — counts of clients matching a rule, with the
              rule stated. No rupee value: nothing here measures what a client
              is worth. */}
          <div className="bg-white border border-ps-border rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <TrendingUp size={16} className="text-green-500" />
              <h3 className="font-semibold text-brand">Worth a Look</h3>
              <span className="ml-auto text-xs text-ps-hint">{growth_opportunities.length} flagged</span>
            </div>
            {growth_opportunities.length === 0 ? (
              <p className="text-sm text-ps-hint text-center py-6">Nothing flagged by these rules</p>
            ) : (
              <div className="space-y-3">
                {growth_opportunities.map((opp: { type: string; description: string; count?: number; basis?: string }, i: number) => (
                  <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-[#F0FDF4] border border-[#BBF7D0]">
                    <Star size={14} className="text-green-500 mt-0.5 flex-shrink-0" />
                    <div className="flex-1">
                      <p className="text-xs font-semibold text-green-700 uppercase tracking-wide">{opp.type}</p>
                      <p className="text-sm text-brand mt-0.5">{opp.description}</p>
                      {opp.basis && (
                        <p className="text-3xs text-ps-hint mt-1">{opp.basis}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Summary — labelled for what wrote it. A model's wording of the
            figures above carries the AI label; the plain sentence built from
            the same figures does not, because nothing AI wrote it. */}
        {ai_summary && (
          <div className="bg-white border border-ps-border rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <Sparkles size={16} style={{ color: BRAND }} />
              <h3 className="font-semibold text-brand">
                {summaryIsModel ? "AI Executive Summary" : "Summary"}
              </h3>
              <span className="ml-auto text-3xs text-ps-hint flex items-center gap-1">
                <Clock size={9} /> Generated {formatTime(data.generated_at)}
              </span>
            </div>
            <div className="prose prose-sm max-w-none text-ps-body text-sm leading-relaxed">
              {ai_summary.split("\n").filter(Boolean).map((para: string, i: number) => (
                <p key={i} className="mb-2">{para}</p>
              ))}
            </div>
            <p className="text-3xs text-ps-disabled mt-3">
              {summaryIsModel
                ? "Worded by an AI model from the figures above; every figure in it is one of them. Verify against source records before decisions."
                : "Written by the application from the figures above — no AI model was used for this sentence."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
