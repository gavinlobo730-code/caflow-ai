"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Calendar,
  Receipt,
  Calculator,
  Landmark,
  Building2,
  KeyRound,
  Info,
} from "lucide-react";
import { cn } from "@/lib/utils";

const DEADLINE_ITEMS = [
  { href: "/deadlines", label: "All Deadlines", icon: Calendar, exact: true },
  { href: "/deadlines?type=GSTR1", label: "GSTR-1", icon: Receipt, exact: false },
  { href: "/deadlines?type=GSTR3B", label: "GSTR-3B", icon: Receipt, exact: false },
  { href: "/deadlines?type=ITR", label: "Income Tax", icon: Calculator, exact: false },
  { href: "/deadlines?type=TDS", label: "TDS", icon: Landmark, exact: false },
  { href: "/deadlines?type=MCA", label: "MCA", icon: Building2, exact: false },
];

export function DeadlinesPanel() {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-white/[0.06] shrink-0">
        <p className="text-[13px] font-semibold text-white/90">Deadlines</p>
        <p className="text-[11px] text-white/30 mt-0.5">Cross-client monitoring</p>
      </div>

      <div className="mx-2 mt-2 shrink-0">
        <div className="flex items-start gap-2 p-2.5 rounded-[7px] bg-amber-500/10 border border-amber-500/20">
          <Info size={11} className="text-amber-400 mt-0.5 shrink-0" />
          <p className="text-[11px] text-amber-300/80 leading-relaxed">
            Triage view. To file, open a{" "}
            <Link
              href="/clients"
              className="text-amber-400 hover:underline font-medium"
            >
              Client
            </Link>{" "}
            and use their Compliance tab.
          </p>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto py-2 px-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-white/30 px-2 mb-1.5 mt-2">
          By Type
        </p>
        <div className="space-y-0.5">
          {DEADLINE_ITEMS.map(({ href, label, icon: Icon, exact }) => {
            const active = exact
              ? pathname === "/deadlines"
              : false;
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] text-[12.5px] font-medium transition-all duration-75",
                  active
                    ? "bg-blue-500/15 text-white/90"
                    : "text-white/50 hover:text-white/80 hover:bg-[#131620]/[0.04]"
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

        <div className="mt-4">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-white/30 px-2 mb-1.5">
            Critical Tools
          </p>
          <Link
            href="/settings/dsc-tracker"
            className={cn(
              "flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] text-[12.5px] font-medium transition-all duration-75",
              pathname.startsWith("/settings/dsc-tracker")
                ? "bg-blue-500/15 text-white/90"
                : "text-white/50 hover:text-white/80 hover:bg-[#131620]/[0.04]"
            )}
          >
            <KeyRound
              size={15}
              className={cn(
                "shrink-0",
                pathname.startsWith("/settings/dsc-tracker")
                  ? "text-blue-400"
                  : "text-white/30"
              )}
            />
            <span className="truncate">DSC Tracker</span>
          </Link>
        </div>
      </nav>
    </div>
  );
}
