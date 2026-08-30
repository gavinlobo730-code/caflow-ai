"use client";

/**
 * Year-End workspace — all eight stages on one route.
 *
 * WHY THIS IS ONE PAGE NOW
 *   It was already a single workspace: layout.tsx rendered a fixed eight-item
 *   nav rail and each stage was a nine-line page.tsx shim around a sibling
 *   _page.tsx client component. So the tabs were real, but they cost eight
 *   Next.js routes — and every dynamic route costs two of Cloudflare Pages'
 *   hard limit of 100 dynamic _redirects rules (see
 *   scripts/generate-redirects.js). Sixteen rules for what is one screen with
 *   a rail. Collapsing them frees fourteen and takes the route budget from
 *   99/100 back to a workable margin.
 *
 *   Nothing about the stages themselves changed: the same eight _page.tsx
 *   components render, unmodified, in the same order behind the same rail.
 *
 * DEEP LINKS
 *   The old form was a path segment (.../year-end/<id>/checklist). That is now
 *   a query param (.../year-end/<id>?tab=checklist), which keeps every stage
 *   individually linkable — a year-end runs over days and "here is the review
 *   screen" is a real thing people send each other. Query params are not
 *   routes, so this costs nothing against the redirect budget. Old path-form
 *   bookmarks do not survive; they were internal navigation, and the two
 *   in-app links that used them have been updated.
 */

import { useEffect, useState, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  CheckSquare2,
  SlidersHorizontal,
  Table2,
  BarChart3,
  FileText,
  ClipboardCheck,
  Download,
} from "lucide-react";
import { yearEndApi, type YearEndEngagement, type EngagementStatus } from "@/lib/api/yearEnd";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { Skeleton } from "@/components/ui/skeleton";
import { useEngagementId } from "./_engagementId";

import DashboardStage from "./dashboard/_page";
import ChecklistStage from "./checklist/_page";
import AdjustmentsStage from "./adjustments/_page";
import SchedulesStage from "./schedules/_page";
import FinancialStatementsStage from "./financial-statements/_page";
import NotesStage from "./notes/_page";
import ReviewStage from "./review/_page";
import ExportsStage from "./exports/_page";

// ── Stages, in the order a year-end is actually worked ─────────────────────
// `id` doubles as the ?tab= value and matches the old path segment, so a
// muscle-memory URL edit still lands on the right stage.

const STAGES = [
  { id: "dashboard",            label: "Dashboard",      icon: LayoutDashboard,   Component: DashboardStage },
  { id: "checklist",            label: "Checklist",      icon: CheckSquare2,      Component: ChecklistStage },
  { id: "adjustments",          label: "Adjustments",    icon: SlidersHorizontal, Component: AdjustmentsStage },
  { id: "schedules",            label: "Schedules",      icon: Table2,            Component: SchedulesStage },
  { id: "financial-statements", label: "Fin Statements", icon: BarChart3,         Component: FinancialStatementsStage },
  { id: "notes",                label: "Notes",          icon: FileText,          Component: NotesStage },
  { id: "review",               label: "Review",         icon: ClipboardCheck,    Component: ReviewStage },
  { id: "exports",              label: "Exports",        icon: Download,          Component: ExportsStage },
] as const;

type StageId = (typeof STAGES)[number]["id"];

const DEFAULT_STAGE: StageId = "dashboard";

function isStageId(v: string | null): v is StageId {
  return !!v && STAGES.some((s) => s.id === v);
}

// ── Status badge ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: EngagementStatus }) {
  const map: Record<EngagementStatus, { label: string; className: string }> = {
    draft: { label: "Draft", className: "bg-slate-100 text-slate-600" },
    in_review: { label: "In Review", className: "bg-yellow-100 text-yellow-700" },
    approved: { label: "Approved", className: "bg-green-100 text-green-700" },
    locked: { label: "Locked", className: "bg-blue-100 text-blue-700" },
  };
  const { label, className } = map[status];
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${className}`}>
      {label}
    </span>
  );
}

// ── Workspace ──────────────────────────────────────────────────────────────

function YearEndWorkspaceInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  // Neither id comes from useParams(), and the tab URL is not built from
  // usePathname(): under `output: export` plus Cloudflare's
  // rewrite-to-_placeholder hosting all of those are the build-time
  // "_placeholder" shell, not this engagement (see _engagementId.ts and
  // lib/workspace/ClientNavContext.tsx). Opening a stage off usePathname()
  // rewrote the address bar to /clients/_placeholder/year-end/_placeholder,
  // which then broke every id on the screen.
  const { clientId } = useClientNav();
  const engagementId = useEngagementId();

  const [engagement, setEngagement] = useState<YearEndEngagement | null>(null);

  // The URL is the source of truth for which stage is open, so a link or a
  // browser Back lands where the reader expects.
  const tabParam = searchParams.get("tab");
  const stage: StageId = isStageId(tabParam) ? tabParam : DEFAULT_STAGE;

  const basePath = `/clients/${clientId}/year-end/${engagementId}/`;

  function openStage(next: StageId) {
    const q = new URLSearchParams(searchParams.toString());
    if (next === DEFAULT_STAGE) q.delete("tab");
    else q.set("tab", next);
    const qs = q.toString();
    router.replace(qs ? `${basePath}?${qs}` : basePath, { scroll: false });
  }

  // `engagement` starts null and the header renders skeleton chips while it is
  // null, so every path out of this effect has to reach a terminal state —
  // otherwise the header keeps the exact permanent-skeleton defect this whole
  // change set exists to remove, just in a smaller box.
  const [headerResolved, setHeaderResolved] = useState(false);
  useEffect(() => {
    // Never query the static-export placeholder id.
    if (!engagementId || engagementId === "_placeholder") { setHeaderResolved(true); return; }
    yearEndApi.engagements
      .get(engagementId)
      .then((res) => { if (res.success) setEngagement(res.data); })
      .catch(() => { /* header degrades to its plain title below */ })
      .finally(() => setHeaderResolved(true));
  }, [engagementId]);

  const ActiveStage = (STAGES.find((s) => s.id === stage) ?? STAGES[0]).Component;

  return (
    <div className="flex h-full min-h-screen bg-[#F8FAFC]">
      {/* Left nav rail */}
      <aside className="w-[72px] bg-white border-r border-slate-100 flex flex-col items-center py-4 gap-1 shrink-0">
        {STAGES.map(({ id, label, icon: Icon }) => {
          const isActive = id === stage;
          return (
            <button
              key={id}
              onClick={() => openStage(id)}
              title={label}
              className={`w-full flex flex-col items-center py-2.5 px-1 gap-1 text-[10px] font-medium transition-colors rounded-none
                ${isActive
                  ? "bg-indigo-50 text-indigo-700 border-r-2 border-indigo-600"
                  : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
                }`}
            >
              <Icon className="w-4.5 h-4.5" />
              <span className="text-center leading-tight">{label}</span>
            </button>
          );
        })}
      </aside>

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-12 bg-white border-b border-slate-100 flex items-center px-5 gap-3 shrink-0">
          {engagement ? (
            <>
              <span className="text-sm font-semibold text-slate-800 truncate max-w-[180px]">
                Year End
              </span>
              <span className="text-slate-300">|</span>
              <span className="text-xs bg-slate-100 text-slate-700 px-2 py-0.5 rounded font-medium">
                FY {engagement.financial_year}
              </span>
              <StatusBadge status={engagement.status} />
              {engagement.version > 1 && (
                <span className="text-xs bg-indigo-50 text-indigo-600 px-2 py-0.5 rounded font-medium">
                  Version {engagement.version}
                </span>
              )}
            </>
          ) : headerResolved ? (
            // Resolved, but there is no engagement to describe. Say nothing
            // rather than animating a row that will never fill.
            <span className="text-xs text-[#94A3B8]">Year End</span>
          ) : (
            <div className="flex items-center gap-3">
              <Skeleton className="h-3.5 w-16" />
              <Skeleton className="h-4 w-14 rounded" />
              <Skeleton className="h-4 w-16 rounded" />
            </div>
          )}
        </header>

        <main className="flex-1 overflow-auto">
          <ActiveStage />
        </main>
      </div>
    </div>
  );
}

export default function YearEndWorkspace() {
  // useSearchParams needs a Suspense boundary to be statically rendered.
  return (
    <Suspense fallback={<div className="p-6"><Skeleton className="h-8 w-48" /></div>}>
      <YearEndWorkspaceInner />
    </Suspense>
  );
}
