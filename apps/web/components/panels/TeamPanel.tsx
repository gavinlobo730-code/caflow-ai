"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserCheck, LayoutGrid, Users, Link2, ShieldCheck, History } from "lucide-react";
import { cn, isExactPath } from "@/lib/utils";

const TEAM_ITEMS = [
  { href: "/team", label: "Team", icon: UserCheck },
  { href: "/team/assignments", label: "Assignments", icon: Link2 },
  { href: "/approvals", label: "Approvals", icon: ShieldCheck },
  { href: "/team/login-history", label: "Login History", icon: History },
  { href: "/team/work-allocation", label: "Work Allocation", icon: LayoutGrid },
  { href: "/payroll/attendance", label: "Attendance", icon: Users },
];

export function TeamPanel() {
  const pathname = usePathname();

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
          {TEAM_ITEMS.map(({ href, label, icon: Icon }) => {
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
