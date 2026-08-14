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
import { usePermissions } from "@/lib/auth/AuthContext";

// Firm administration only. Chart of Accounts, statements and cash flow now live
// in the client workspace (Client → Accounting); the duplicate firm-level screens
// were retired in the Phase 3 consolidation. Payroll & Fee Billing map to the
// accounting workspace, so they are surfaced here.
//
// `requires` names the backend permission the page's own data calls need, read
// off the endpoint rather than guessed, so a link disappears for anyone who
// would only reach a 403. The four Chart-of-Accounts screens carry none: they
// query Supabase directly (`sb.from("chart_of_accounts")`), so RLS governs them
// and no entry in the rbac matrix applies. An absent `requires` means "no
// FastAPI permission governs this page", never "nobody checked".
const NAV_ITEMS: Array<{
  label: string;
  href: string;
  icon: typeof GitBranch;
  requires?: [resource: string, action: string];
}> = [
  { label: "Schedule III Mapping", href: "/accounting/schedule-iii-mapping", icon: GitBranch },
  { label: "Account Groups",      href: "/accounting/account-groups",        icon: Layers },
  { label: "Import COA",          href: "/accounting/coa-import",            icon: Upload },
  { label: "Export COA",          href: "/accounting/coa-export",            icon: Download },
  // billing.py is Partner-only throughout ("exposes fee economics").
  { label: "Fee Billing",         href: "/billing",                          icon: Receipt,
    requires: ["billing", "read"] },
  // payroll.py: every endpoint the page calls is rbac("payroll", read|write).
  { label: "Payroll",             href: "/payroll",                          icon: Briefcase,
    requires: ["payroll", "read"] },
  { label: "Payroll Statutory",   href: "/payroll/statutory",                icon: ShieldCheck },
  // tally_migration.py list_jobs → rbac("accounting", "read"), which excludes
  // Reviewer; the page's first call is that list, so it renders nothing for one.
  { label: "Data Migration",      href: "/migration",                        icon: DatabaseZap,
    requires: ["accounting", "read"] },
];

export function AccountingPanel() {
  const pathname = usePathname();
  const { can } = usePermissions();
  const items = NAV_ITEMS.filter((i) => !i.requires || can(i.requires[0], i.requires[1]));

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
        {items.map(({ label, href, icon: Icon }) => {
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
