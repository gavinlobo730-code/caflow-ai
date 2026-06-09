"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Shield,
  Receipt,
  Calculator,
  Landmark,
  Building2,
  KeyRound,
  Lock,
} from "lucide-react";
import { cn } from "@/lib/utils";

const COMPLIANCE_ITEMS = [
  { href: "/compliance", label: "Compliance Overview", icon: Shield },
  { href: "/gst", label: "GST", icon: Receipt },
  { href: "/gst/gstr3b", label: "GSTR-3B", icon: Receipt },
  { href: "/gst/gstr1", label: "GSTR-1", icon: Receipt },
  { href: "/income-tax", label: "Income Tax", icon: Calculator },
  { href: "/tds", label: "TDS", icon: Landmark },
  { href: "/tds/returns", label: "TDS Returns", icon: Landmark },
  { href: "/mca", label: "MCA", icon: Building2 },
];

export function CompliancePanel() {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-white/[0.06] shrink-0">
        <p className="text-[13px] font-semibold text-white/90">Compliance</p>
        <p className="text-[11px] text-white/30 mt-0.5">Deadline overview</p>
      </div>

      {/* Read-only notice */}
      <div className="mx-2 mt-2 shrink-0">
        <div className="flex items-start gap-2 p-2.5 rounded-[7px] bg-amber-500/10 border border-amber-500/20">
          <Lock size={11} className="text-amber-400 mt-0.5 shrink-0" />
          <p className="text-[11px] text-amber-300/80 leading-relaxed">
            View-only. To file, open a{" "}
            <Link
              href="/clients"
              className="text-amber-400 hover:underline font-medium"
            >
              Client
            </Link>{" "}
            and use their tabs.
          </p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-white/30 px-2 mb-1.5 mt-2">
          Filing Areas
        </p>
        <div className="space-y-0.5">
          {COMPLIANCE_ITEMS.map(({ href, label, icon: Icon }) => {
            const active =
              pathname === href || pathname.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] text-[12.5px] font-medium transition-all duration-75",
                  active
                    ? "bg-indigo-500/15 text-white/90"
                    : "text-white/50 hover:text-white/80 hover:bg-white/[0.04]"
                )}
              >
                <Icon
                  size={15}
                  className={cn(
                    "shrink-0",
                    active ? "text-indigo-400" : "text-white/30"
                  )}
                />
                <span className="truncate">{label}</span>
              </Link>
            );
          })}
        </div>

        {/* DSC Tracker — critical compliance tool */}
        <div className="mt-4">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-white/30 px-2 mb-1.5">
            Critical Tools
          </p>
          <Link
            href="/settings/dsc-tracker"
            className={cn(
              "flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] text-[12.5px] font-medium transition-all duration-75",
              pathname.startsWith("/settings/dsc-tracker")
                ? "bg-indigo-500/15 text-white/90"
                : "text-white/50 hover:text-white/80 hover:bg-white/[0.04]"
            )}
          >
            <KeyRound
              size={15}
              className={cn(
                "shrink-0",
                pathname.startsWith("/settings/dsc-tracker")
                  ? "text-indigo-400"
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
