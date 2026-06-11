"use client";

import { useEffect, useState } from "react";
import { useParams, usePathname, useRouter } from "next/navigation";
import Link from "next/link";
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

// ── Nav config ─────────────────────────────────────────────────────────────

const NAV_ITEMS = [
  { label: "Dashboard", icon: LayoutDashboard, path: "dashboard" },
  { label: "Checklist", icon: CheckSquare2, path: "checklist" },
  { label: "Adjustments", icon: SlidersHorizontal, path: "adjustments" },
  { label: "Schedules", icon: Table2, path: "schedules" },
  { label: "Fin Statements", icon: BarChart3, path: "financial-statements" },
  { label: "Notes", icon: FileText, path: "notes" },
  { label: "Review", icon: ClipboardCheck, path: "review" },
  { label: "Exports", icon: Download, path: "exports" },
];

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

// ── Layout ─────────────────────────────────────────────────────────────────

export default function YearEndWorkspaceLayout({ children }: { children: React.ReactNode }) {
  const params = useParams();
  const pathname = usePathname();
  const clientId = params.id as string;
  const engagementId = params.engagementId as string;

  const [engagement, setEngagement] = useState<YearEndEngagement | null>(null);

  useEffect(() => {
    yearEndApi.engagements.get(engagementId).then((res) => {
      if (res.success) setEngagement(res.data);
    });
  }, [engagementId]);

  const basePath = `/clients/${clientId}/year-end/${engagementId}`;

  return (
    <div className="flex h-full min-h-screen bg-[#F8FAFC]">
      {/* Left nav rail */}
      <aside className="w-[72px] bg-white border-r border-slate-100 flex flex-col items-center py-4 gap-1 shrink-0">
        {NAV_ITEMS.map(({ label, icon: Icon, path }) => {
          const href = `${basePath}/${path}`;
          const isActive = pathname.startsWith(href);
          return (
            <Link
              key={path}
              href={href}
              title={label}
              className={`w-full flex flex-col items-center py-2.5 px-1 gap-1 text-[10px] font-medium transition-colors rounded-none
                ${isActive
                  ? "bg-indigo-50 text-indigo-700 border-r-2 border-indigo-600"
                  : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
                }`}
            >
              <Icon className="w-4.5 h-4.5" />
              <span className="text-center leading-tight">{label}</span>
            </Link>
          );
        })}
      </aside>

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top header */}
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
          ) : (
            <div className="h-4 w-48 animate-pulse rounded bg-slate-100" />
          )}
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
