"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Sparkles, ShieldAlert, BarChart3, MessageSquare, Brain, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

// `/reports/cash-flow` was on the Reports landing page and nowhere else, so
// from inside it there was no way back to any sibling — the rule in
// `components/panels/AccountingPanel.tsx`'s header, held by
// `scripts/a-module-shows-all-of-itself.test.ts`. It reads the ledger straight
// over PostgREST (RLS, not rbac()), so there is no permission to gate it on.
const AI_ITEMS = [
  { href: "/ai-assistant", label: "AI Assistant", icon: Sparkles },
  { href: "/copilot", label: "AI Copilot", icon: MessageSquare },
  { href: "/memory", label: "Memory & Signals", icon: Brain },
  { href: "/risks", label: "Risk Intelligence", icon: ShieldAlert },
  { href: "/reports", label: "Reports", icon: BarChart3 },
  { href: "/reports/cash-flow", label: "Cash Flow Forecast", icon: TrendingUp },
];

export function AIPanel() {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 shrink-0">
        <p className="text-sm font-semibold text-brand">AI</p>
        <p className="text-2xs text-gray-500 mt-0.5">
          Intelligence & reports
        </p>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        <p className="text-3xs font-semibold uppercase tracking-[0.08em] text-gray-400 px-2 mb-1.5 mt-1">
          Tools
        </p>
        <div className="space-y-0.5">
          {AI_ITEMS.map(({ href, label, icon: Icon }) => {
            const active =
              pathname === href || pathname.startsWith(href + "/");
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
