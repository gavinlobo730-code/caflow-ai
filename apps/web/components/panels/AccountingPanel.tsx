"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  GitBranch,
  Layers,
  Upload,
  Download,
  BookOpen,
  Receipt,
  Briefcase,
  ShieldCheck,
  DatabaseZap,
} from "lucide-react";
import { cn } from "@/lib/utils";

// Firm administration only. Chart of Accounts, statements and cash flow now live
// in the client workspace (Client → Accounting); the duplicate firm-level screens
// were retired in the Phase 3 consolidation. Payroll & Fee Billing map to the
// accounting workspace, so they are surfaced here.
const NAV_ITEMS = [
  { label: "Schedule III Mapping", href: "/accounting/schedule-iii-mapping", icon: GitBranch },
  { label: "Account Groups",      href: "/accounting/account-groups",        icon: Layers },
  { label: "Import COA",          href: "/accounting/coa-import",            icon: Upload },
  { label: "Export COA",          href: "/accounting/coa-export",            icon: Download },
  { label: "Fee Billing",         href: "/billing",                          icon: Receipt },
  { label: "Payroll",             href: "/payroll",                          icon: Briefcase },
  { label: "Payroll Statutory",   href: "/payroll/statutory",                icon: ShieldCheck },
  { label: "Data Migration",      href: "/migration",                        icon: DatabaseZap },
];

export function AccountingPanel() {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full text-[#182350]">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-4 border-b border-gray-200 shrink-0">
        <div className="w-6 h-6 rounded-md bg-[#182350]/10 flex items-center justify-center">
          <BookOpen size={12} className="text-[#182350]" />
        </div>
        <div>
          <p className="text-[12px] font-semibold text-[#182350] leading-none">Accounting</p>
          <p className="text-[10px] text-gray-500 mt-0.5 leading-none">Firm administration</p>
        </div>
      </div>

      {/* Nav items */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        {NAV_ITEMS.map(({ label, href, icon: Icon }) => {
          const isActive = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-colors mb-0.5",
                isActive
                  ? "bg-[#182350] text-white"
                  : "text-gray-600 hover:text-[#182350] hover:bg-[#F8FAFC]"
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
