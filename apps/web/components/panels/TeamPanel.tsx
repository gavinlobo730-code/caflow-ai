"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserCheck, LayoutGrid, Users, Link2, ShieldCheck, History } from "lucide-react";
import { cn, isExactPath } from "@/lib/utils";
import { usePermissions } from "@/lib/auth/AuthContext";

// `requires` names the backend permission that the page's OWN data calls need,
// so the link disappears for anyone who would only reach a 403. It is set only
// where the page is API-backed and the requirement was read off the endpoint:
// an item with no `requires` is a claim that no FastAPI permission governs it,
// not that nobody checked.
//
// Work Allocation and Attendance query Supabase directly (RLS, not rbac()), so
// there is no matrix entry to gate them on — inventing one here would hide a
// page that actually works.
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
  { href: "/payroll/attendance", label: "Attendance", icon: Users },
];

export function TeamPanel() {
  const pathname = usePathname();
  const { can } = usePermissions();
  const items = TEAM_ITEMS.filter((i) => !i.requires || can(i.requires[0], i.requires[1]));

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 shrink-0">
        <p className="text-[13px] font-semibold text-[#182350]">Team</p>
        <p className="text-[11px] text-gray-500 mt-0.5">
          Staff & task management
        </p>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-400 px-2 mb-1.5 mt-1">
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
                  "flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] text-[12.5px] font-medium transition-all duration-75",
                  active
                    ? "bg-[#182350] text-white"
                    : "text-gray-600 hover:bg-[#F8FAFC] hover:text-[#182350]"
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
