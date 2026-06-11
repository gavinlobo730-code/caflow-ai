"use client";

/**
 * Phase 1.3 Intelligence panels — compliance risk, relationship health and
 * proactive recommendations from the /api/intelligence endpoints.
 * Read-only insights: nothing here submits anything to any government portal.
 */

import { useState, useEffect } from "react";
import Link from "next/link";
import { ShieldAlert, HeartPulse, Lightbulb, Loader2 } from "lucide-react";
import { api } from "@/lib/api";

interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: string | null;
}

interface RiskClient {
  client_id: string;
  client_name: string;
  risk_score: number;
  risk_level: "low" | "medium" | "high" | "critical";
  overdue_count: number;
  due_soon_count: number;
}

interface HealthClient {
  client_id: string;
  client_name: string;
  health_score: number;
  health_level: string;
  outstanding_paise: number;
  overdue_invoices: number;
}

interface Recommendation {
  category: string;
  priority: "high" | "medium" | "low";
  title: string;
  detail: string;
  client_id?: string;
}

const RISK_BADGE: Record<string, string> = {
  critical: "bg-red-100 text-red-700",
  high: "bg-orange-100 text-orange-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-green-100 text-green-700",
};

const PRIORITY_BADGE: Record<string, string> = {
  high: "bg-red-100 text-red-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-[#F1F5F9] text-[#475569]",
};

const CATEGORY_CHIP: Record<string, string> = {
  compliance: "bg-indigo-50 text-blue-600",
  client: "bg-violet-50 text-violet-600",
  operational: "bg-sky-50 text-sky-600",
};

/** Display-only ₹ formatting from integer paise — no float arithmetic on money */
function fmtPaise(paise: number): string {
  const rupees = Math.floor(paise / 100);
  return "₹" + rupees.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function PanelShell({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-2xl shadow-sm border border-[#F1F5F9] overflow-hidden">
      <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
        {icon}
        <h3 className="text-sm font-semibold text-[#0F172A]">{title}</h3>
      </div>
      <div className="px-5 py-3">{children}</div>
    </div>
  );
}

export function IntelligencePanels() {
  const [risk, setRisk] = useState<RiskClient[]>([]);
  const [health, setHealth] = useState<HealthClient[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [riskRes, healthRes, recRes] = await Promise.all([
          api.intelligence.complianceRisk() as Promise<ApiResponse<{ clients: RiskClient[] }>>,
          api.intelligence.relationshipHealth() as Promise<ApiResponse<{ clients: HealthClient[] }>>,
          api.intelligence.recommendations() as Promise<ApiResponse<{ recommendations: Recommendation[] }>>,
        ]);
        setRisk((riskRes.data?.clients ?? []).filter(c => c.risk_score > 0).slice(0, 5));
        setHealth(
          (healthRes.data?.clients ?? [])
            .slice()
            .sort((a, b) => a.health_score - b.health_score)
            .slice(0, 5)
        );
        setRecommendations((recRes.data?.recommendations ?? []).slice(0, 6));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load intelligence data");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-10 text-[#94A3B8] text-sm">
        <Loader2 className="animate-spin mr-2" size={16} /> Loading intelligence…
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
        Intelligence data unavailable: {error}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h2 className="text-base font-semibold text-[#0F172A]">Intelligence</h2>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Compliance Risk */}
        <PanelShell
          icon={<ShieldAlert size={15} className="text-red-500" />}
          title="Compliance Risk"
        >
          {risk.length === 0 ? (
            <p className="text-xs text-[#94A3B8] py-3">No at-risk clients detected</p>
          ) : (
            <div className="divide-y divide-[#E2E8F0]">
              {risk.map(c => (
                <div key={c.client_id} className="flex items-center justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <Link href={`/clients/${c.client_id}`} className="text-sm font-medium text-[#1E293B] hover:text-blue-600 truncate block">
                      {c.client_name}
                    </Link>
                    <p className="text-[11px] text-[#94A3B8]">
                      {c.overdue_count} overdue · {c.due_soon_count} due soon
                    </p>
                  </div>
                  <span className={`text-[11px] px-2 py-0.5 rounded-full font-semibold shrink-0 ${RISK_BADGE[c.risk_level]}`}>
                    {c.risk_score}
                  </span>
                </div>
              ))}
            </div>
          )}
        </PanelShell>

        {/* Relationship Health */}
        <PanelShell
          icon={<HeartPulse size={15} className="text-violet-500" />}
          title="Relationship Health"
        >
          {health.length === 0 ? (
            <p className="text-xs text-[#94A3B8] py-3">No client health data yet</p>
          ) : (
            <div className="divide-y divide-[#E2E8F0]">
              {health.map(c => (
                <div key={c.client_id} className="flex items-center justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <Link href={`/clients/${c.client_id}`} className="text-sm font-medium text-[#1E293B] hover:text-blue-600 truncate block">
                      {c.client_name}
                    </Link>
                    <p className="text-[11px] text-[#94A3B8]">
                      {fmtPaise(c.outstanding_paise)} outstanding
                      {c.overdue_invoices > 0 ? ` · ${c.overdue_invoices} overdue inv` : ""}
                    </p>
                  </div>
                  <span className={`text-[11px] px-2 py-0.5 rounded-full font-semibold shrink-0 ${
                    c.health_score < 40 ? "bg-red-100 text-red-700" :
                    c.health_score < 70 ? "bg-amber-100 text-amber-700" :
                    "bg-green-100 text-green-700"
                  }`}>
                    {c.health_score}
                  </span>
                </div>
              ))}
            </div>
          )}
        </PanelShell>

        {/* Recommendations */}
        <PanelShell
          icon={<Lightbulb size={15} className="text-amber-500" />}
          title="Recommendations"
        >
          {recommendations.length === 0 ? (
            <p className="text-xs text-[#94A3B8] py-3">No recommendations right now</p>
          ) : (
            <div className="divide-y divide-[#E2E8F0]">
              {recommendations.map((r, i) => (
                <div key={i} className="py-2.5 space-y-1">
                  <div className="flex items-center gap-1.5">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${CATEGORY_CHIP[r.category] ?? "bg-[#F8FAFC] text-[#64748B]"}`}>
                      {r.category}
                    </span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${PRIORITY_BADGE[r.priority]}`}>
                      {r.priority}
                    </span>
                  </div>
                  <p className="text-sm font-medium text-[#1E293B] leading-snug">{r.title}</p>
                  <p className="text-[11px] text-[#94A3B8] leading-snug">{r.detail}</p>
                </div>
              ))}
            </div>
          )}
        </PanelShell>
      </div>
    </div>
  );
}
