"use client";

import { useEffect, useState } from "react";
import {
  TrendingUp, Users, AlertTriangle, TrendingDown, Sparkles,
  RefreshCw, DollarSign, BarChart2,
  ArrowUpRight, ArrowDownRight, ShieldAlert, Clock, Star,
} from "lucide-react";
import { api } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ExecutiveDashboard {
  firm_id: string;
  revenue_insights: {
    outstanding_invoices: number;
    outstanding_amount_paise: number;
    avg_collection_days: number;
    billing_trend: string;
  };
  capacity_insights: {
    team_utilisation_percent: number;
    overloaded_staff: number;
    underutilised_staff: number;
    avg_tasks_per_staff: number;
  };
  client_risk_insights: {
    critical_clients: number;
    at_risk_clients: number;
    healthy_clients: number;
    compliance_failures: number;
  };
  churn_signals: Array<{ client_name: string; signal: string; risk: string }>;
  growth_opportunities: Array<{ type: string; description: string; estimated_value_paise?: number }>;
  firm_health_summary: {
    overall_score: number;
    compliance_coverage: number;
    active_automations: number;
    pending_approvals: number;
    ai_recommendations_pending: number;
    critical_actions: number;
  };
  ai_summary: string;
  generated_at: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtRupees(paise: number): string {
  const rupees = Math.floor(paise / 100);
  if (rupees >= 10000000) return `₹${(rupees / 10000000).toFixed(1)}Cr`;
  if (rupees >= 100000) return `₹${(rupees / 100000).toFixed(1)}L`;
  if (rupees >= 1000) return `₹${(rupees / 1000).toFixed(0)}K`;
  return `₹${rupees}`;
}

function healthColor(score: number): string {
  if (score >= 85) return "#16A34A";
  if (score >= 70) return "#D97706";
  if (score >= 55) return "#EA580C";
  return "#DC2626";
}

function healthLabel(score: number): string {
  if (score >= 85) return "Excellent";
  if (score >= 70) return "Good";
  if (score >= 55) return "Fair";
  return "Critical";
}

// ── Sub-components ────────────────────────────────────────────────────────────

function KPICard({ label, value, sub, icon, trend, color = "#182350" }: {
  label: string; value: string | number; sub?: string;
  icon: React.ReactNode; trend?: "up" | "down" | "neutral"; color?: string;
}) {
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-xl p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-[#64748B] font-medium uppercase tracking-wide mb-1">{label}</p>
          <p className="text-2xl font-bold" style={{ color }}>{value}</p>
          {sub && <p className="text-xs text-[#94A3B8] mt-1">{sub}</p>}
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

function HealthRing({ score }: { score: number }) {
  const r = 36;
  const circ = 2 * Math.PI * r;
  const fill = (score / 100) * circ;
  const color = healthColor(score);

  return (
    <div className="relative flex items-center justify-center">
      <svg width="96" height="96" viewBox="0 0 96 96">
        <circle cx="48" cy="48" r={r} fill="none" stroke="#F1F5F9" strokeWidth="8" />
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
        <p className="text-xl font-bold" style={{ color }}>{score}</p>
        <p className="text-[10px] text-[#94A3B8]">{healthLabel(score)}</p>
      </div>
    </div>
  );
}

function RiskBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-[#64748B]">{label}</span>
        <span className="font-semibold" style={{ color }}>{value}</span>
      </div>
      <div className="h-1.5 bg-[#F1F5F9] rounded-full overflow-hidden">
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

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = (await api.copilotV2.executiveDashboard()) as { data: ExecutiveDashboard };
      setData(res.data);
    } catch {
      setError("Failed to load executive dashboard");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center">
        <div className="text-center">
          <div className="w-12 h-12 rounded-full border-2 border-[#AFD2FA] border-t-[#182350] animate-spin mx-auto mb-4" />
          <p className="text-[#64748B] text-sm">Generating executive intelligence...</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center">
        <div className="text-center">
          <AlertTriangle size={40} className="mx-auto text-[#CBD5E1] mb-3" />
          <p className="text-[#64748B]">{error || "No data available"}</p>
          <button onClick={load} className="mt-4 text-sm text-[#182350] underline">Retry</button>
        </div>
      </div>
    );
  }

  const { revenue_insights, capacity_insights, client_risk_insights, churn_signals,
    growth_opportunities, firm_health_summary, ai_summary } = data;

  const totalClients = client_risk_insights.critical_clients + client_risk_insights.at_risk_clients + client_risk_insights.healthy_clients;

  return (
    <div className="min-h-screen bg-[#F8FAFC]">
      {/* Header */}
      <div className="bg-white border-b border-[#E2E8F0] px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ backgroundColor: "#182350" }}>
              <BarChart2 size={18} className="text-white" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-[#182350]">Executive Dashboard</h1>
              <p className="text-xs text-[#64748B]">AI-powered firm intelligence • {new Date(data.generated_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</p>
            </div>
          </div>
          <button onClick={load} disabled={loading}
            className="flex items-center gap-1.5 text-sm text-[#64748B] hover:text-[#182350] border border-[#E2E8F0] px-3 py-2 rounded-lg bg-white">
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      <div className="px-6 py-6 max-w-[1400px] mx-auto space-y-6">

        {/* Top KPI row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <KPICard
            label="Outstanding Invoices"
            value={fmtRupees(revenue_insights.outstanding_amount_paise)}
            sub={`${revenue_insights.outstanding_invoices} invoices`}
            icon={<DollarSign size={18} style={{ color: "#B9915E" }} />}
            color="#B9915E"
            trend="neutral"
          />
          <KPICard
            label="Team Utilisation"
            value={`${capacity_insights.team_utilisation_percent}%`}
            sub={`${capacity_insights.avg_tasks_per_staff} tasks/person`}
            icon={<Users size={18} style={{ color: "#182350" }} />}
            color="#182350"
            trend={capacity_insights.team_utilisation_percent > 90 ? "down" : "up"}
          />
          <KPICard
            label="At-Risk Clients"
            value={client_risk_insights.at_risk_clients + client_risk_insights.critical_clients}
            sub={`${client_risk_insights.critical_clients} critical`}
            icon={<ShieldAlert size={18} style={{ color: "#DC2626" }} />}
            color="#DC2626"
            trend="down"
          />
          <KPICard
            label="Avg Collection Days"
            value={revenue_insights.avg_collection_days}
            sub="days outstanding"
            icon={<Clock size={18} style={{ color: "#D97706" }} />}
            color="#D97706"
            trend="neutral"
          />
        </div>

        {/* Middle section */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

          {/* Firm Health */}
          <div className="bg-white border border-[#E2E8F0] rounded-xl p-5">
            <h3 className="font-semibold text-[#182350] mb-4">Firm Health</h3>
            <div className="flex items-center gap-4 mb-4">
              <HealthRing score={firm_health_summary.overall_score} />
              <div className="flex-1 space-y-3">
                <RiskBar label="Compliance Coverage" value={firm_health_summary.compliance_coverage} max={100} color="#16A34A" />
                <RiskBar label="Active Automations" value={firm_health_summary.active_automations} max={10} color="#182350" />
                <RiskBar label="Pending Actions" value={firm_health_summary.ai_recommendations_pending} max={20} color="#D97706" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="bg-[#FEF3C7] rounded-lg p-2.5 text-center">
                <p className="text-lg font-bold text-amber-700">{firm_health_summary.pending_approvals}</p>
                <p className="text-[10px] text-amber-600">Pending Approvals</p>
              </div>
              <div className="bg-[#FEE2E2] rounded-lg p-2.5 text-center">
                <p className="text-lg font-bold text-red-700">{firm_health_summary.critical_actions}</p>
                <p className="text-[10px] text-red-600">Critical Actions</p>
              </div>
            </div>
          </div>

          {/* Client Risk Breakdown */}
          <div className="bg-white border border-[#E2E8F0] rounded-xl p-5">
            <h3 className="font-semibold text-[#182350] mb-4">Client Portfolio Risk</h3>
            {totalClients > 0 && (
              <div className="h-3 rounded-full overflow-hidden flex mb-3">
                {[
                  { count: client_risk_insights.healthy_clients, color: "#16A34A" },
                  { count: client_risk_insights.at_risk_clients, color: "#D97706" },
                  { count: client_risk_insights.critical_clients, color: "#DC2626" },
                ].map(({ count, color }, i) => (
                  count > 0 && <div key={i} style={{ width: `${(count / totalClients) * 100}%`, backgroundColor: color }} />
                ))}
              </div>
            )}
            <div className="space-y-3">
              <RiskBar label={`Healthy (${client_risk_insights.healthy_clients})`} value={client_risk_insights.healthy_clients} max={totalClients} color="#16A34A" />
              <RiskBar label={`At Risk (${client_risk_insights.at_risk_clients})`} value={client_risk_insights.at_risk_clients} max={totalClients} color="#D97706" />
              <RiskBar label={`Critical (${client_risk_insights.critical_clients})`} value={client_risk_insights.critical_clients} max={totalClients} color="#DC2626" />
            </div>
            <div className="mt-4 pt-3 border-t border-[#F1F5F9]">
              <p className="text-xs text-[#64748B]">
                <span className="font-medium text-red-600">{client_risk_insights.compliance_failures}</span> compliance failures require immediate attention
              </p>
            </div>
          </div>

          {/* Capacity */}
          <div className="bg-white border border-[#E2E8F0] rounded-xl p-5">
            <h3 className="font-semibold text-[#182350] mb-4">Team Capacity</h3>
            {/* Utilisation gauge */}
            <div className="text-center mb-4">
              <div className="relative w-24 h-24 mx-auto">
                <svg viewBox="0 0 96 96" className="w-24 h-24">
                  <circle cx="48" cy="48" r="36" fill="none" stroke="#F1F5F9" strokeWidth="8" />
                  <circle
                    cx="48" cy="48" r="36"
                    fill="none"
                    stroke={capacity_insights.team_utilisation_percent > 90 ? "#DC2626" : capacity_insights.team_utilisation_percent > 75 ? "#D97706" : "#16A34A"}
                    strokeWidth="8"
                    strokeLinecap="round"
                    strokeDasharray={`${(capacity_insights.team_utilisation_percent / 100) * 226} 226`}
                    strokeDashoffset="56.5"
                    transform="rotate(-90 48 48)"
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <p className="text-xl font-bold text-[#182350]">{capacity_insights.team_utilisation_percent}%</p>
                  <p className="text-[9px] text-[#94A3B8]">utilised</p>
                </div>
              </div>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-[#64748B] text-xs">Overloaded staff</span>
                <span className="font-semibold text-red-600 text-xs">{capacity_insights.overloaded_staff}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#64748B] text-xs">Underutilised staff</span>
                <span className="font-semibold text-amber-600 text-xs">{capacity_insights.underutilised_staff}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#64748B] text-xs">Avg tasks per person</span>
                <span className="font-semibold text-[#182350] text-xs">{capacity_insights.avg_tasks_per_staff}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Bottom section */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

          {/* Churn Signals */}
          <div className="bg-white border border-[#E2E8F0] rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <TrendingDown size={16} className="text-red-500" />
              <h3 className="font-semibold text-[#182350]">Churn Signals</h3>
              <span className="ml-auto text-xs text-[#94A3B8]">{churn_signals.length} detected</span>
            </div>
            {churn_signals.length === 0 ? (
              <p className="text-sm text-[#94A3B8] text-center py-6">No churn signals detected</p>
            ) : (
              <div className="space-y-3">
                {churn_signals.map((sig: { client_name: string; signal: string; risk: string }, i: number) => (
                  <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-[#FFF7F7] border border-[#FEE2E2]">
                    <AlertTriangle size={14} className="text-red-400 mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="text-sm font-medium text-[#182350]">{sig.client_name}</p>
                      <p className="text-xs text-[#64748B] mt-0.5">{sig.signal}</p>
                    </div>
                    <span className={`ml-auto text-[10px] px-2 py-0.5 rounded-full font-semibold ${
                      sig.risk === "high" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"
                    }`}>
                      {sig.risk.toUpperCase()}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Growth Opportunities */}
          <div className="bg-white border border-[#E2E8F0] rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <TrendingUp size={16} className="text-green-500" />
              <h3 className="font-semibold text-[#182350]">Growth Opportunities</h3>
              <span className="ml-auto text-xs text-[#94A3B8]">{growth_opportunities.length} identified</span>
            </div>
            {growth_opportunities.length === 0 ? (
              <p className="text-sm text-[#94A3B8] text-center py-6">No opportunities detected</p>
            ) : (
              <div className="space-y-3">
                {growth_opportunities.map((opp: { type: string; description: string; estimated_value_paise?: number }, i: number) => (
                  <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-[#F0FDF4] border border-[#BBF7D0]">
                    <Star size={14} className="text-green-500 mt-0.5 flex-shrink-0" />
                    <div className="flex-1">
                      <p className="text-xs font-semibold text-green-700 uppercase tracking-wide">{opp.type}</p>
                      <p className="text-sm text-[#182350] mt-0.5">{opp.description}</p>
                      {opp.estimated_value_paise && (
                        <p className="text-xs text-green-600 mt-1 font-medium">
                          Estimated: {fmtRupees(opp.estimated_value_paise)}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* AI Summary */}
        {ai_summary && (
          <div className="bg-white border border-[#E2E8F0] rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <Sparkles size={16} style={{ color: "#182350" }} />
              <h3 className="font-semibold text-[#182350]">AI Executive Summary</h3>
              <span className="ml-auto text-[10px] text-[#94A3B8] flex items-center gap-1">
                <Clock size={9} /> Generated {new Date(data.generated_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
              </span>
            </div>
            <div className="prose prose-sm max-w-none text-[#334155] text-sm leading-relaxed">
              {ai_summary.split("\n").filter(Boolean).map((para: string, i: number) => (
                <p key={i} className="mb-2">{para}</p>
              ))}
            </div>
            <p className="text-[10px] text-[#CBD5E1] mt-3">
              AI analysis is advisory. Verify all figures with source records before decisions.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
