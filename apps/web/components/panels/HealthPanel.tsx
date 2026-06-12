"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  LayoutDashboard,
  AlertOctagon,
  AlertTriangle,
  Bell,
  SlidersHorizontal,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { label: "Health Dashboard",   href: "/health",                  icon: LayoutDashboard },
  { label: "Critical Clients",   href: "/health/critical",         icon: AlertOctagon },
  { label: "At-Risk Clients",    href: "/health/at-risk",          icon: AlertTriangle },
  { label: "Health Alerts",      href: "/health/alerts",           icon: Bell },
  { label: "Override Controls",  href: "/health/overrides",        icon: SlidersHorizontal },
];

export function HealthPanel() {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full text-white">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-4 border-b border-white/10 shrink-0">
        <div className="w-6 h-6 rounded-md bg-emerald-600/30 flex items-center justify-center">
          <Activity size={12} className="text-emerald-400" />
        </div>
        <div>
          <p className="text-[12px] font-semibold text-white leading-none">Health</p>
          <p className="text-[10px] text-slate-400 mt-0.5 leading-none">Client health monitor</p>
        </div>
      </div>

      {/* Nav items */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        {NAV_ITEMS.map(({ label, href, icon: Icon }) => {
          const isActive =
            href === "/health"
              ? pathname === "/health"
              : pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-colors mb-0.5",
                isActive
                  ? "bg-emerald-600 text-white"
                  : "text-slate-400 hover:text-white hover:bg-white/10"
              )}
            >
              <Icon size={13} className="shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
