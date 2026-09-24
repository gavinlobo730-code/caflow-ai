"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserCheck, LayoutGrid, Link2, ShieldCheck, History, Gauge } from "lucide-react";
import { cn, isExactPath } from "@/lib/utils";
import { usePermissions } from "@/lib/auth/AuthContext";

// `requires` names the backend permission that the page's OWN data calls need,
// so the link disappears for anyone who would only reach a 403. It is set only
// where the page is API-backed and the requirement was read off the endpoint:
// an item with no `requires` is a claim that no FastAPI permission governs it,
// not that nobody checked.
//
// Work Allocation queries Supabase directly (RLS, not rbac()), so there is no
// matrix entry to gate it on — inventing one here would hide a page that
// actually works.
//
// ⚠️ `/payroll/attendance` WAS HERE AND LEFT ON 24-09 (PAY-28). It was listed
// as a cross-module convenience — attendance is staff-shaped — while the panel
// that owns `/payroll` did not list it at all, so payroll's screens sat across
// three top-level areas and attendance was the one nobody could find from
// payroll. It is in `PayrollPanel` now, under "This month", where the LOP it
// records is an input to the run. Do not add it back: two panels listing one
// screen is the defect, not the fix.
const TEAM_ITEMS: Array<{
  href: string;
  label: string;
  icon: typeof UserCheck;
  requires?: [resource: string, action: string];
}> = [
  // identity.list_users → rbac("team", "read")
  { href: "/team", label: "Team", icon: UserCheck, requires: ["team", "read"] },
  // assignments.list_* → rbac("assignment", "read")
  { href: "/team/assignments", label: "Assignments", icon: Link2, requires: ["assignment", "read"] },
  // approvals.list_approvals → rbac("approval", "read")
  { href: "/approvals", label: "Approvals", icon: ShieldCheck, requires: ["approval", "read"] },
  // identity.login_history → rbac("team", "read")
  { href: "/team/login-history", label: "Login History", icon: History, requires: ["team", "read"] },
  { href: "/team/work-allocation", label: "Work Allocation", icon: LayoutGrid },
  // workload.get_team_workload → rbac("workload", "read"). It was in NEITHER
  // this panel nor any landing page — one of exactly two named screens in the
  // product reachable only by typing its name into ⌘K.
  { href: "/team/workload", label: "Workload", icon: Gauge, requires: ["workload", "read"] },
];

export function TeamPanel() {
  const pathname = usePathname();
  const { can } = usePermissions();
  const items = TEAM_ITEMS.filter((i) => !i.requires || can(i.requires[0], i.requires[1]));

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 shrink-0">
        <p className="text-sm font-semibold text-brand">Team</p>
        <p className="text-2xs text-gray-500 mt-0.5">
          Staff & task management
        </p>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        <p className="text-3xs font-semibold uppercase tracking-[0.08em] text-gray-400 px-2 mb-1.5 mt-1">
          Navigate
        </p>
        <div className="space-y-0.5">
          {items.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/team"
                ? isExactPath(pathname, "/team")
                : pathname === href || pathname.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] text-xs font-medium transition-all duration-75",
                  active
                    ? "bg-brand text-white"
                    : "text-gray-600 hover:bg-ps-bg hover:text-brand"
                )}
              >
                <Icon
                  size={15}
                  className={cn(
                    "shrink-0",
                    active ? "text-white" : "text-gray-500"
                  )}
                />
                <span className="truncate">{label}</span>
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
