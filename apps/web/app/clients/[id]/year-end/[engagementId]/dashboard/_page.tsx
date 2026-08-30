"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  CheckSquare2,
  SlidersHorizontal,
  BarChart3,
  Clock,
  ArrowRight,
  TrendingUp,
  User,
} from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import type { EngagementStatus, YearEndEvent } from "@/lib/api/yearEnd";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { Skeleton, DashboardSkeleton } from "@/components/ui/skeleton";
import { useEngagementId } from "../_engagementId";

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

// Human-readable text for the event_type values written by
// apps/api/routers/year_end_reviews.py's _record_review_event() into
// year_end_reviews.event_type. Falls back to a title-cased version of the
// raw event_type for anything not in this list (defensive — new review
// actions shouldn't make the dashboard render a blank description).
const EVENT_DESCRIPTIONS: Record<string, string> = {
  submitted_for_review: "Submitted for review",
  approved: "Review approved",
  revision_requested: "Revision requested",
  final_approved_and_locked: "Final approval — engagement locked",
};

function describeEvent(eventType: string): string {
  return (
    EVENT_DESCRIPTIONS[eventType] ??
    eventType.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())
  );
}

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
  const router = useRouter();
  // Both ids come from window.location, not useParams(): the static export is
  // served from a shell whose every dynamic segment is "_placeholder" (see
  // ../_engagementId.ts and lib/workspace/ClientNavContext.tsx).
  const { clientId } = useClientNav();
  const engagementId = useEngagementId();

  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const supabase = getSupabaseClient();

      const [
        { data: engRow, error: engErr },
        { data: checklistRows, error: checklistErr },
        { data: adjRows, error: adjErr },
        { data: versionRows, error: versionErr },
        { data: eventRows, error: eventErr },
        { data: selfRows },
      ] = await Promise.all([
        // year_end_engagements — firm-scoped RLS (migration 154: yee_firm_isolation).
        // No `version` column exists on this table (grep-confirmed against every
        // year_end migration and router) — defaulted below.
        supabase
          .from("year_end_engagements")
          .select("id, financial_year, status, updated_at")
          .eq("id", engagementId)
          .maybeSingle(),
        // year_end_checklists — same table checklist/_page.tsx's backend call
        // (routers/year_end_checklist.py) reads from. Only "complete" is used
        // for the completion count, so the not_started/pending naming drift
        // between that table's CHECK constraint and yearEnd.ts's
        // ChecklistItemStatus type doesn't affect this computation.
        supabase
          .from("year_end_checklists")
          .select("id, status")
          .eq("engagement_id", engagementId),
        // year_end_adjustments — same table adjustments/_page.tsx's backend call
        // (routers/year_end_adjustments.py) reads from. amount_paise is the one
        // column name that matches the frontend Adjustment type exactly.
        supabase
          .from("year_end_adjustments")
          .select("id, amount_paise")
          .eq("engagement_id", engagementId),
        // financial_statement_versions — latest snapshot. Column is created_at,
        // not generated_at (routers/year_end_statements.py never writes a
        // generated_at column); used as statements_generated_at below since
        // that's the moment the snapshot was produced.
        supabase
          .from("financial_statement_versions")
          .select("version_number, created_at")
          .eq("engagement_id", engagementId)
          .order("version_number", { ascending: false })
          .limit(1),
        // year_end_reviews — the review-workflow audit trail written by
        // _record_review_event() in routers/year_end_reviews.py (submit /
        // approve / request-revision / final-approve). This is the existing
        // "recent_events"-shaped source for this engagement; the general
        // audit_log table (services/audit_service.log_event) was considered
        // but rejected — see note below.
        // `year_end_review_events`, NOT `year_end_reviews` — same repository-vs-
        // production name split as the Notes tab above; see migration 252's
        // header. The routers were repointed; this query was not, so the
        // dashboard's recent-activity list has been failing in production.
        supabase
          .from("year_end_review_events")
          .select("id, engagement_id, event_type, comment, actor_id, created_at")
          .eq("engagement_id", engagementId)
          .order("created_at", { ascending: false })
          .limit(10),
        // users — RLS restricts SELECT to the caller's own row (migration 153/
        // 009: "users_own_row"), so this can only ever resolve the CURRENT
        // user's display name, never other actors'. Used below to label an
        // event as performed by name when the viewer is that actor; other
        // actors' events fall back to actor: null (matches team/page.tsx's
        // documented workaround for the same RLS limit).
        supabase.from("users").select("auth_user_id, full_name"),
      ]);

      if (engErr) throw new Error(engErr.message);
      if (!engRow) throw new Error("Engagement not found");
      if (checklistErr) throw new Error(checklistErr.message);
      if (adjErr) throw new Error(adjErr.message);
      if (versionErr) throw new Error(versionErr.message);
      if (eventErr) throw new Error(eventErr.message);

      const checklist = (checklistRows ?? []) as { id: string; status: string }[];
      const adjustments = (adjRows ?? []) as { id: string; amount_paise: number }[];
      const latestVersion = ((versionRows ?? []) as { version_number: number; created_at: string }[])[0];
      const events = (eventRows ?? []) as {
        id: string;
        engagement_id: string;
        event_type: string;
        comment: string | null;
        actor_id: string | null;
        created_at: string;
      }[];
      const selfNameByAuthId = new Map(
        ((selfRows ?? []) as { auth_user_id: string; full_name: string | null }[]).map(
          (r) => [r.auth_user_id, r.full_name]
        )
      );

      const dashboard: DashboardData = {
        engagement: {
          id: engRow.id as string,
          financial_year: engRow.financial_year as string,
          status: engRow.status as EngagementStatus,
          // No `version` column on year_end_engagements — see comment above.
          version: 1,
          updated_at: engRow.updated_at as string,
        },
        checklist_total: checklist.length,
        checklist_complete: checklist.filter((i) => i.status === "complete").length,
        adjustments_count: adjustments.length,
        adjustments_total_paise: adjustments.reduce((s, a) => s + (a.amount_paise ?? 0), 0),
        current_version: latestVersion?.version_number ?? null,
        statements_generated_at: latestVersion?.created_at ?? null,
        recent_events: events.map(
          (e): YearEndEvent => ({
            id: e.id,
            engagement_id: e.engagement_id,
            event_type: e.event_type,
            description: e.comment
              ? `${describeEvent(e.event_type)} — ${e.comment}`
              : describeEvent(e.event_type),
            actor: (e.actor_id && selfNameByAuthId.get(e.actor_id)) || null,
            created_at: e.created_at,
          })
        ),
      };

      setData(dashboard);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [engagementId]);

  useEffect(() => { load(); }, [load]);

  // Stage shortcuts below go to `${base}/?tab=<stage>`, not `${base}/<stage>`.
  // The eight stage routes were collapsed into this one route behind ?tab=
  // (see _workspace.tsx's DEEP LINKS note); the old path form no longer exists
  // and Cloudflare serves 404.html for it. The placeholder-id bug hid that —
  // the links were dead for a different reason — so fixing the ids alone would
  // have turned every card on this dashboard into an honest 404.
  const base = `/clients/${clientId}/year-end/${engagementId}`;

  if (loading) {
    return (
      <div className="p-6 space-y-5 max-w-4xl">
        <Skeleton className="h-16 rounded-xl" />
        <DashboardSkeleton cards={3} className="grid-cols-1 sm:grid-cols-3" />
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
          onClick={() => router.push(`${base}/?tab=checklist`)}
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
          onClick={() => router.push(`${base}/?tab=adjustments`)}
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
          onClick={() => router.push(`${base}/?tab=financial-statements`)}
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
            onClick={() => router.push(`${base}/?tab=checklist`)}
            className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#475569]"
          >
            <CheckSquare2 size={12} /> Go to Checklist <ArrowRight size={10} />
          </button>
          <button
            onClick={() => router.push(`${base}/?tab=adjustments`)}
            className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#475569]"
          >
            <SlidersHorizontal size={12} /> Pass Adjustment <ArrowRight size={10} />
          </button>
          <button
            onClick={() => router.push(`${base}/?tab=financial-statements`)}
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
