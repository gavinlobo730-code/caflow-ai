"use client";

import { Suspense } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  Calendar,
  Receipt,
  Calculator,
  Landmark,
  Building2,
  KeyRound,
  Info,
  QrCode,
} from "lucide-react";
import { cn, isExactPath } from "@/lib/utils";

const DEADLINE_ITEMS = [
  { href: "/deadlines", label: "All Deadlines", icon: Calendar, typeParam: null },
  { href: "/deadlines?type=GSTR1",  label: "GSTR-1",      icon: Receipt,    typeParam: "GSTR1"  },
  { href: "/deadlines?type=GSTR3B", label: "GSTR-3B",     icon: Receipt,    typeParam: "GSTR3B" },
  { href: "/deadlines?type=ITR",    label: "Income Tax",  icon: Calculator, typeParam: "ITR"    },
  { href: "/deadlines?type=TDS",    label: "TDS",         icon: Landmark,   typeParam: "TDS"    },
  { href: "/deadlines?type=MCA",    label: "MCA",         icon: Building2,  typeParam: "MCA"    },
];

// R3.3c — the actual statutory filing tools (GST/Income Tax/TDS/MCA/e-invoice
// workspaces), as opposed to DEADLINE_ITEMS above, which only filter the
// deadlines triage view by type. Each hub links to its own sub-pages.
const FILING_WORKSPACE_ITEMS = [
  { href: "/gst", label: "GST", icon: Receipt },
  { href: "/einvoice", label: "e-Invoice", icon: QrCode },
  { href: "/income-tax", label: "Income Tax", icon: Calculator },
  { href: "/tds", label: "TDS", icon: Landmark },
  { href: "/mca", label: "MCA / ROC", icon: Building2 },
];

function DeadlinesPanelInner() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const activeType = searchParams.get("type"); // null when on /deadlines with no param

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-gray-200 shrink-0">
        <p className="text-[13px] font-semibold text-[#182350]">Deadlines</p>
        <p className="text-[11px] text-gray-500 mt-0.5">Cross-client monitoring</p>
      </div>

      <div className="mx-2 mt-2 shrink-0">
        <div className="flex items-start gap-2 p-2.5 rounded-[7px] bg-amber-50 border border-amber-500/20">
          <Info size={11} className="text-amber-600 mt-0.5 shrink-0" />
          <p className="text-[11px] text-amber-700 leading-relaxed">
            Triage view. To file, open a{" "}
            <Link
              href="/clients"
              className="text-amber-600 hover:underline font-medium"
            >
              Client
            </Link>{" "}
            and use their Compliance tab.
          </p>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto py-2 px-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-400 px-2 mb-1.5 mt-2">
          By Type
        </p>
        <div className="space-y-0.5">
          {DEADLINE_ITEMS.map(({ href, label, icon: Icon, typeParam }) => {
            const active =
              typeParam === null
                ? isExactPath(pathname, "/deadlines") && !activeType  // "All Deadlines"
                : activeType === typeParam;                            // type-specific items
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
                  className={cn("shrink-0", active ? "text-white" : "text-gray-500")}
                />
                <span className="truncate">{label}</span>
              </Link>
            );
          })}
        </div>

        <div className="mt-4">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-400 px-2 mb-1.5">
            Filing Workspaces
          </p>
          <div className="space-y-0.5">
            {FILING_WORKSPACE_ITEMS.map(({ href, label, icon: Icon }) => {
              const active = pathname === href || pathname.startsWith(`${href}/`);
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
                    className={cn("shrink-0", active ? "text-white" : "text-gray-500")}
                  />
                  <span className="truncate">{label}</span>
                </Link>
              );
            })}
          </div>
        </div>

        <div className="mt-4">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-400 px-2 mb-1.5">
            Critical Tools
          </p>
          <Link
            href="/settings/dsc-tracker"
            className={cn(
              "flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] text-[12.5px] font-medium transition-all duration-75",
              pathname.startsWith("/settings/dsc-tracker")
                ? "bg-[#182350] text-white"
                : "text-gray-600 hover:bg-[#F8FAFC] hover:text-[#182350]"
            )}
          >
            <KeyRound
              size={15}
              className={cn(
                "shrink-0",
                pathname.startsWith("/settings/dsc-tracker") ? "text-white" : "text-gray-500"
              )}
            />
            <span className="truncate">DSC Tracker</span>
          </Link>
        </div>
      </nav>
    </div>
  );
}

export function DeadlinesPanel() {
  return (
    <Suspense fallback={<div className="flex flex-col h-full" />}>
      <DeadlinesPanelInner />
    </Suspense>
  );
}
