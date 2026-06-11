"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CheckSquare,
  ListTodo,
  Receipt,
  Briefcase,
  BarChart3,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";

const WORK_SECTIONS = [
  {
    label: "Work Queue",
    items: [
      { href: "/work", label: "All Work", icon: CheckSquare },
      { href: "/tasks", label: "Tasks", icon: ListTodo },
    ],
  },
  {
    label: "Payroll & Billing",
    items: [
      { href: "/payroll", label: "Payroll", icon: Briefcase },
      { href: "/billing", label: "Fee Billing", icon: Receipt },
    ],
  },
  {
    label: "Reports",
    items: [
      { href: "/reports", label: "Reports", icon: BarChart3 },
      { href: "/team/work-allocation", label: "Work Allocation", icon: Users },
    ],
  },
];

export function WorkPanel() {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-white/[0.06] shrink-0">
        <p className="text-[13px] font-semibold text-white/85">Work</p>
        <p className="text-[11px] text-white/30 mt-0.5">Firm-wide queue</p>
      </div>

      <nav className="flex-1 overflow-y-auto py-2 px-2 space-y-4">
        {WORK_SECTIONS.map((section) => (
          <div key={section.label}>
            <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-white/30 px-2 mb-1.5">
              {section.label}
            </p>
            <div className="space-y-0.5">
              {section.items.map(({ href, label, icon: Icon }) => {
                const active =
                  href === "/work"
                    ? pathname === "/work"
                    : href === "/tasks"
                    ? pathname === "/tasks"
                    : pathname === href || pathname.startsWith(href + "/");
                return (
                  <Link
                    key={href}
                    href={href}
                    className={cn(
                      "flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] text-[12.5px] font-medium transition-all duration-75",
                      active
                        ? "bg-blue-500/15 text-white/85"
                        : "text-white/50 hover:text-white/75 hover:bg-[#0F172A]/[0.04]"
                    )}
                  >
                    <Icon
                      size={15}
                      className={cn(
                        "shrink-0",
                        active ? "text-blue-400" : "text-white/30"
                      )}
                    />
                    <span className="truncate">{label}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
    </div>
  );
}
