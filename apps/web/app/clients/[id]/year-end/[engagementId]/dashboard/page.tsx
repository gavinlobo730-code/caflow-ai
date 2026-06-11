"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  CheckSquare2,
  SlidersHorizontal,
  BarChart3,
  Clock,
  ArrowRight,
  TrendingUp,
  User,
} from "lucide-react";
import { yearEndApi, type EngagementStatus, type YearEndEvent } from "@/lib/api/yearEnd";

/** Format paise → ₹ Indian number format */
function fmt(paise: number): string {
  if (paise === 0) return "₹0";
  return (
    "₹" +
    new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(paise / 100)
  );
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

const STATUS_ICON: Record<EngagementStatus, string> = {
  draft: "📝",
  in_review: "🔍",
  approved: "✅",
  locked: "🔒",
};

const STATUS_LABEL: Record<EngagementStatus, string> = {
  draft: "Draft",
  in_review: "In Review",
  approved: "Approved",
  locked: "Locked",
};

const STATUS_COLOR: Record<EngagementStatus, string> = {
  draft: "text-[#64748B] bg-[#F1F5F9]",
  in_review: "text-amber-700 bg-amber-50",
  approved: "text-green-700 bg-green-50",
  locked: "text-blue-700 bg-blue-50",
};

interface DashboardData {
  engagement: {
    id: string;
    financial_year: string;
    status: EngagementStatus;
    version: number;
    updated_at: string;
  };
  checklist_total: number;
  checklist_complete: number;
  adjustments_count: number;
  adjustments_total_paise: number;
  current_version: number | null;
  statements_generated_at: string | null;
  recent_events: YearEndEvent[];
}

export default function YearEndDashboardPage() {
  const params = useParams<{ id: string; engagementId: string }>();
  const router = useRouter();
  const { id: clientId, engagementId } = params;

  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await yearEndApi.dashboard.get(engagementId);
      if (!res.success) throw new Error(res.error ?? "Failed to load dashboard");
      setData(res.data as DashboardData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [engagementId]);

  useEffect(() => { load(); }, [load]);

  const base = `/clients/${clientId}/year-end/${engagementId}`;

  if (loading) {
    return (
      <div className="p-6 space-y-4 max-w-4xl">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-24 rounded-xl bg-[#F8FAFC] animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-4 text-sm text-red-700">
          {error}
          <button onClick={load} className="ml-3 underline text-xs">Retry</button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const { engagement, checklist_total, checklist_complete, adjustments_count,
    adjustments_total_paise, current_version, statements_generated_at, recent_events } = data;

  const checklistPct = checklist_total > 0
    ? Math.round((checklist_complete / checklist_total) * 100)
    : 0;

  const statementsGeneratedDate = statements_generated_at
    ? new Date(statements_generated_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
    : null;

  return (
    <div className="p-6 space-y-5 max-w-4xl">

      {/* Status card */}
      <div className={`rounded-xl px-5 py-4 flex items-center gap-4 ${STATUS_COLOR[engagement.status]}`}>
        <span className="text-3xl">{STATUS_ICON[engagement.status]}</span>
        <div className="flex-1">
          <p className="text-sm font-semibold">{STATUS_LABEL[engagement.status]}</p>
          <p className="text-xs opacity-70 mt-0.5">
            FY {engagement.financial_year} · Version {engagement.version} · Last updated {timeAgo(engagement.updated_at)}
          </p>
        </div>
      </div>

      {/* Summary cards grid */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {/* Checklist progress */}
        <div
          className="bg-white rounded-xl border border-[#F1F5F9] p-4 cursor-pointer hover:shadow-sm transition-shadow"
          onClick={() => router.push(`${base}/checklist`)}
        >
          <div className="flex items-center gap-2 mb-3">
            <CheckSquare2 size={15} className="text-[#64748B]" />
            <p className="text-xs font-semibold text-[#334155]">Checklist</p>
          </div>
          <p className="text-lg font-bold text-[#0F172A] tabular-nums">
            {checklist_complete} <span className="text-[#94A3B8] text-sm font-normal">of {checklist_total}</span>
          </p>
          <p className="text-[10px] text-[#94A3B8] mb-2">items complete</p>
          {/* Progress bar */}
          <div className="w-full h-1.5 bg-[#F1F5F9] rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all"
              style={{ width: `${checklistPct}%` }}
            />
          </div>
          <p className="text-[10px] text-[#94A3B8] mt-1">{checklistPct}%</p>
        </div>

        {/* Adjustments */}
        <div
          className="bg-white rounded-xl border border-[#F1F5F9] p-4 cursor-pointer hover:shadow-sm transition-shadow"
          onClick={() => router.push(`${base}/adjustments`)}
        >
          <div className="flex items-center gap-2 mb-3">
            <SlidersHorizontal size={15} className="text-[#64748B]" />
            <p className="text-xs font-semibold text-[#334155]">Adjustments</p>
          </div>
          <p className="text-lg font-bold text-[#0F172A] tabular-nums">{adjustments_count}</p>
          <p className="text-[10px] text-[#94A3B8] mb-1">adjustments</p>
          <p className="text-xs font-semibold text-[#334155]">{fmt(adjustments_total_paise)}</p>
          <p className="text-[10px] text-[#94A3B8]">total value</p>
        </div>

        {/* Financial Statements */}
        <div
          className="bg-white rounded-xl border border-[#F1F5F9] p-4 cursor-pointer hover:shadow-sm transition-shadow"
          onClick={() => router.push(`${base}/financial-statements`)}
        >
          <div className="flex items-center gap-2 mb-3">
            <BarChart3 size={15} className="text-[#64748B]" />
            <p className="text-xs font-semibold text-[#334155]">Financial Statements</p>
          </div>
          {current_version ? (
            <>
              <p className="text-lg font-bold text-[#0F172A]">Version {current_version}</p>
              <p className="text-[10px] text-[#94A3B8]">
                Generated {statementsGeneratedDate ?? "—"}
              </p>
            </>
          ) : (
            <>
              <p className="text-sm text-[#94A3B8]">Not generated yet</p>
              <p className="text-[10px] text-[#94A3B8] mt-1">Click to generate</p>
            </>
          )}
        </div>
      </div>

      {/* Quick actions */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
        <p className="text-xs font-semibold text-[#334155] mb-3">Quick Actions</p>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => router.push(`${base}/checklist`)}
            className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#475569]"
          >
            <CheckSquare2 size={12} /> Go to Checklist <ArrowRight size={10} />
          </button>
          <button
            onClick={() => router.push(`${base}/adjustments`)}
            className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#475569]"
          >
            <SlidersHorizontal size={12} /> Pass Adjustment <ArrowRight size={10} />
          </button>
          <button
            onClick={() => router.push(`${base}/financial-statements`)}
            className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700"
          >
            <TrendingUp size={12} /> Generate Statements <ArrowRight size={10} />
          </button>
        </div>
      </div>

      {/* Recent activity */}
      {recent_events.length > 0 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-4 py-3 border-b border-[#F8FAFC]">
            <p className="text-xs font-semibold text-[#334155]">Recent Activity</p>
          </div>
          <div className="divide-y divide-[#F8FAFC]">
            {recent_events.map((event) => (
              <div key={event.id} className="px-4 py-2.5 flex items-start gap-3">
                <div className="w-6 h-6 rounded-full bg-[#F1F5F9] flex items-center justify-center flex-shrink-0 mt-0.5">
                  {event.actor ? (
                    <User size={10} className="text-[#64748B]" />
                  ) : (
                    <Clock size={10} className="text-[#64748B]" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-[#334155]">{event.description}</p>
                  <p className="text-[10px] text-[#94A3B8] mt-0.5">
                    {event.actor && <span>{event.actor} · </span>}
                    {timeAgo(event.created_at)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
