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
  DatabaseZap,
  LayoutDashboard,
  Users,
  Clock,
  Landmark,
  FileText,
  Target,
  IndianRupee,
  RefreshCw,
  ClipboardCheck,
  Scale,
  Lock,
} from "lucide-react";
import { cn, isExactPath } from "@/lib/utils";
import { usePermissions, useAuth } from "@/lib/auth/AuthContext";

/**
 * The Accounting workspace's browse surface.
 *
 * ⚠️ IT USED TO LIST FOUR OF THIS MODULE'S FOURTEEN SCREENS, AND
 * `app/accounting/page.tsx` LISTED TEN — DISJOINT SETS. Not one screen
 * appeared in both, so which half of their own module a CA could see depended
 * on which surface they happened to navigate by: from the sidebar there was no
 * Budgets, Loans, Receivables, MSME §43B(h), Retainers, Recurring Journals,
 * Lock Financial Year, Schedule III Statements, Supplier Master or Trial
 * Balance Import; from the landing page there was no Schedule III Mapping,
 * Account Groups or COA import/export. And a CA standing ON one of those
 * screens had no way back to its neighbour at all, because the landing page is
 * not on the screen and this panel is.
 *
 * So the rule is: THE PANEL LISTS THE WHOLE MODULE. It is the surface present
 * on every page of the workspace, which is what makes it the one that has to be
 * complete; a landing page may additionally feature whatever it likes.
 * `scripts/a-module-shows-all-of-itself.test.ts` holds it for every workspace.
 *
 * `requires` names the backend permission the page's own data calls need, READ
 * OFF THE ENDPOINT rather than guessed — each one below was checked against the
 * `rbac(...)` on the route it calls. An absent `requires` means "no FastAPI
 * permission governs this page", never "nobody checked": the four Chart-of-
 * Accounts screens and Loans and Receivables query Supabase directly, so RLS
 * governs them and no entry in the rbac matrix applies.
 *
 * `partnerOnly` mirrors a page's OWN `RoleGuard allowed={["Partner"]}` and is
 * used once, on Lock Financial Year. It is not a second permission system —
 * `rbac()` remains the boundary — it stops the panel offering a link that can
 * only bounce.
 *
 * Fee Billing and Data Migration map to this workspace (see routeOwnership.ts),
 * so their screens are grouped here rather than left unreachable from the rail.
 *
 * ⚠️ PAYROLL LEFT ON 24-09 AND THAT IS PAY-28, not a deletion. Its six screens
 * were listed here under a "Payroll" heading; payroll is now the thirteenth
 * top-level workspace with its own panel (`PayrollPanel`), because a bureau
 * running payroll for a dozen clients needs a home for the service rather than
 * a sub-heading inside somebody else's module. `routeOwnership.ts` asks
 * `/payroll` BEFORE `/accounting`, so nothing here owns those routes any more
 * and re-adding one would put payroll in two places again.
 */
type NavItem = {
  label: string;
  href: string;
  icon: typeof GitBranch;
  exact?: boolean;
  requires?: [resource: string, action: string];
  partnerOnly?: boolean;
};

const NAV_GROUPS: Array<{ heading: string | null; items: NavItem[] }> = [
  {
    heading: null,
    items: [
      { label: "Overview", href: "/accounting", icon: LayoutDashboard, exact: true },
    ],
  },
  {
    heading: "Chart of accounts",
    items: [
      { label: "Schedule III Mapping", href: "/accounting/schedule-iii-mapping", icon: GitBranch },
      { label: "Account Groups", href: "/accounting/account-groups", icon: Layers },
      { label: "Import COA", href: "/accounting/coa-import", icon: Upload },
      { label: "Export COA", href: "/accounting/coa-export", icon: Download },
    ],
  },
  {
    heading: "Registers",
    items: [
      // vendors.py list_vendors → rbac("client", "read").
      { label: "Supplier Master", href: "/accounting/suppliers", icon: Users,
        requires: ["client", "read"] },
      { label: "Receivables Ageing", href: "/accounting/receivables", icon: Clock },
      { label: "Loans & FD", href: "/accounting/loans", icon: Landmark },
      // income_tax.py msme_section_43bh → rbac("income_tax", "compute").
      { label: "MSME §43B(h)", href: "/accounting/msme-tracker", icon: FileText,
        requires: ["income_tax", "compute"] },
      // accounting.py get_budgets → rbac("accounting", "read").
      { label: "Budget vs Actuals", href: "/accounting/budget", icon: Target,
        requires: ["accounting", "read"] },
      // billing.py is Partner-only throughout ("exposes fee economics"); the
      // retainer screen's first call is api.billing.listSchedules.
      { label: "Retainers", href: "/accounting/retainer", icon: IndianRupee,
        requires: ["billing", "read"] },
      // recurring_journals.py list → rbac("accounting", "read").
      { label: "Recurring Journals", href: "/accounting/recurring", icon: RefreshCw,
        requires: ["accounting", "read"] },
    ],
  },
  {
    heading: "Period close",
    items: [
      // accounting.py get_schedule_iii → rbac("accounting", "read").
      { label: "Schedule III Statements", href: "/accounting/schedule-iii", icon: ClipboardCheck,
        requires: ["accounting", "read"] },
      // accounting.py import_trial_balance_endpoint → rbac("accounting", "write").
      // The call is on submit rather than on load, so the gate is the write one:
      // a Reviewer offered this link could only fill the form in and be refused.
      { label: "Trial Balance Import", href: "/accounting/trial-balance-import", icon: Scale,
        requires: ["accounting", "write"] },
      { label: "Lock Financial Year", href: "/accounting/lock-year", icon: Lock,
        partnerOnly: true },
    ],
  },
  {
    heading: "Firm",
    items: [
      { label: "Fee Billing", href: "/billing", icon: Receipt,
        requires: ["billing", "read"] },
      // tally_migration.py list_jobs → rbac("accounting", "read"), which
      // excludes Reviewer; the page's first call is that list.
      { label: "Data Migration", href: "/migration", icon: DatabaseZap,
        requires: ["accounting", "read"] },
    ],
  },
];

export function AccountingPanel() {
  const pathname = usePathname();
  const { can } = usePermissions();
  const { userRole } = useAuth();

  const groups = NAV_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter(
      (i) =>
        (!i.requires || can(i.requires[0], i.requires[1])) &&
        (!i.partnerOnly || userRole === "Partner"),
    ),
  })).filter((g) => g.items.length > 0);

  return (
    <div className="flex flex-col h-full text-brand">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-4 border-b border-gray-200 shrink-0">
        <div className="w-6 h-6 rounded-md bg-brand/10 flex items-center justify-center">
          <BookOpen size={12} className="text-brand" />
        </div>
        <div>
          <p className="text-xs font-semibold text-brand leading-none">Accounting</p>
          <p className="text-3xs text-gray-500 mt-0.5 leading-none">Firm administration</p>
        </div>
      </div>

      {/* Nav items. Grouped because the whole module is 17 entries and an
          ungrouped list of 17 is a wall — the headings are how it stays
          scannable at the 220px the panel gets. (It was 22 before payroll's
          six moved out to their own workspace; grouping still earns its
          keep, and the headings are the module's own shape rather than a
          length threshold.) */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        {groups.map(({ heading, items }) => (
          <div key={heading ?? "_"} className={heading ? "mt-3 first:mt-0" : ""}>
            {heading && (
              <p className="px-3 pb-1 text-3xs font-semibold uppercase tracking-wider text-ps-hint">
                {heading}
              </p>
            )}
            {items.map(({ label, href, icon: Icon, exact }) => {
              const isActive = exact
                ? isExactPath(pathname, href)
                : pathname === href || pathname.startsWith(href + "/");
              return (
                <Link
                  key={href}
                  href={href}
                  className={cn(
                    "flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors mb-0.5",
                    isActive
                      ? "bg-brand text-white"
                      : "text-gray-600 hover:text-brand hover:bg-ps-bg"
                  )}
                >
                  <Icon size={13} className="shrink-0" />
                  {label}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
    </div>
  );
}
