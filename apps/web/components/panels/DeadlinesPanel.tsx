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
  FileText,
  Wallet,
  ArrowLeftRight,
  TrendingUp,
  PiggyBank,
  Mail,
  Percent,
  ClipboardCheck,
  FileSpreadsheet,
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
// deadlines triage view by type.
//
// ⚠️ "EACH HUB LINKS TO ITS OWN SUB-PAGES" IS WHAT THIS COMMENT USED TO SAY,
// and it was true of the hub PAGE and not of this panel — so all eleven of
// them (both GSTR screens, the eight income-tax ones and the TDS return
// screen) existed only on a landing page a CA has to navigate back to. From
// `/income-tax/capital-gains` there was no way to `/income-tax/tax-audit`
// except the browser's Back button. The panel is the surface that is on every
// page of the module, so it is the one that has to be complete.
//
// The children render only INSIDE their own hub, which is progressive
// disclosure rather than a gap: a CA looking at GST does not need the eight
// income-tax screens in front of them, and a flat list of sixteen would be a
// wall at 220px. Every href is nonetheless declared here, which is what
// `scripts/a-module-shows-all-of-itself.test.ts` reads.
const FILING_WORKSPACE_ITEMS: Array<{
  href: string;
  label: string;
  icon: typeof Receipt;
  children?: Array<{ href: string; label: string; icon: typeof Receipt }>;
}> = [
  {
    href: "/gst",
    label: "GST",
    icon: Receipt,
    children: [
      { href: "/gst/gstr1", label: "GSTR-1", icon: FileText },
      { href: "/gst/gstr3b", label: "GSTR-3B", icon: FileSpreadsheet },
    ],
  },
  { href: "/einvoice", label: "e-Invoice", icon: QrCode },
  {
    href: "/income-tax",
    label: "Income Tax",
    icon: Calculator,
    children: [
      { href: "/income-tax/advance-tax", label: "Advance Tax", icon: Wallet },
      { href: "/income-tax/book-to-tax", label: "Book to Tax", icon: ArrowLeftRight },
      { href: "/income-tax/capital-gains", label: "Capital Gains", icon: TrendingUp },
      { href: "/income-tax/section-32", label: "Depreciation (§32)", icon: Percent },
      { href: "/income-tax/deductions", label: "Chapter VI-A", icon: PiggyBank },
      { href: "/income-tax/tax-audit", label: "Tax Audit (§44AB)", icon: ClipboardCheck },
      { href: "/income-tax/tax-audit/form-3cd", label: "Form 3CD", icon: FileText },
      { href: "/income-tax/ais", label: "AIS", icon: FileText },
      { href: "/income-tax/notices", label: "Notices", icon: Mail },
    ],
  },
  {
    href: "/tds",
    label: "TDS",
    icon: Landmark,
    children: [
      { href: "/tds/returns", label: "TDS Returns", icon: FileSpreadsheet },
    ],
  },
  { href: "/mca", label: "MCA / ROC", icon: Building2 },
];

function DeadlinesPanelInner() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const activeType = searchParams.get("type"); // null when on /deadlines with no param

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-gray-200 shrink-0">
        <p className="text-sm font-semibold text-brand">Deadlines</p>
        <p className="text-2xs text-gray-500 mt-0.5">Cross-client monitoring</p>
      </div>

      <div className="mx-2 mt-2 shrink-0">
        <div className="flex items-start gap-2 p-2.5 rounded-[7px] bg-state-attention-surface border border-amber-500/20">
          <Info size={11} className="text-amber-600 mt-0.5 shrink-0" />
          <p className="text-2xs text-state-attention leading-relaxed">
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
        <p className="text-3xs font-semibold uppercase tracking-[0.08em] text-gray-400 px-2 mb-1.5 mt-2">
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
                  "flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] text-xs font-medium transition-all duration-75",
                  active
                    ? "bg-brand text-white"
                    : "text-gray-600 hover:bg-ps-bg hover:text-brand"
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
          <p className="text-3xs font-semibold uppercase tracking-[0.08em] text-gray-400 px-2 mb-1.5">
            Filing Workspaces
          </p>
          <div className="space-y-0.5">
            {FILING_WORKSPACE_ITEMS.map(({ href, label, icon: Icon, children }) => {
              const inside = pathname === href || pathname.startsWith(`${href}/`);
              const active = isExactPath(pathname, href);
              return (
                <div key={href}>
                  <Link
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
                      className={cn("shrink-0", active ? "text-white" : "text-gray-500")}
                    />
                    <span className="truncate">{label}</span>
                  </Link>
                  {inside && children && (
                    <div className="ml-3 pl-2 border-l border-gray-200 mt-0.5 space-y-0.5">
                      {children.map((c) => {
                        const on = pathname === c.href || pathname.startsWith(`${c.href}/`);
                        return (
                          <Link
                            key={c.href}
                            href={c.href}
                            className={cn(
                              "flex items-center gap-2 px-2.5 py-1.5 rounded-[7px] text-2xs font-medium transition-all duration-75",
                              on
                                ? "bg-brand text-white"
                                : "text-gray-600 hover:bg-ps-bg hover:text-brand"
                            )}
                          >
                            <c.icon
                              size={13}
                              className={cn("shrink-0", on ? "text-white" : "text-gray-500")}
                            />
                            <span className="truncate">{c.label}</span>
                          </Link>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="mt-4">
          <p className="text-3xs font-semibold uppercase tracking-[0.08em] text-gray-400 px-2 mb-1.5">
            Critical Tools
          </p>
          <Link
            href="/settings/dsc-tracker"
            className={cn(
              "flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] text-xs font-medium transition-all duration-75",
              pathname.startsWith("/settings/dsc-tracker")
                ? "bg-brand text-white"
                : "text-gray-600 hover:bg-ps-bg hover:text-brand"
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
