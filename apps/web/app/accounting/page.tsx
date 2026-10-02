"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { RefreshCw, Target, FileText, ClipboardCheck, IndianRupee, Scale, Lock, Landmark, Users, Clock, Building2, ArrowRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { api } from "@/lib/api";
import { NAV_GROUPS } from "@/components/panels/AccountingPanel";
import { usePermissions, useAuth } from "@/lib/auth/AuthContext";
import { PageHeader } from "@/components/ui/page-header";

// Phase 3 consolidation: this is the firm ADMINISTRATION hub only. Day-to-day
// accounting — journals, ledger, trial balance, P&L, balance sheet, cash flow,
// banking and reconciliation — happens inside each client's workspace
// (Client → Accounting), powered by the single backend reporting engine. The
// firm's own books are the internal "practice" client. The old duplicate
// firm-level accounting screens have been retired.
const ADMIN_CARDS: {
  label: string; description: string; href: string;
  icon: typeof Users; notShared?: boolean;
}[] = [
  { label: "Supplier Master", description: "Manage supplier TDS sections, credit limits and payment terms", href: "/accounting/suppliers", icon: Users },
  // The PRACTICE's fee invoices, not a client's customers — the Sales hub tile
  // once linked here for those (accounting-hub-2-05); they are the Sales
  // worklist at /accounting/invoices.
  { label: "Fee Receivables", description: "What clients owe the practice — your own unpaid fee invoices, by age", href: "/accounting/receivables", icon: Clock },
  { label: "Loans & FD", description: "Loans, EMI schedules and FD investments with maturity & TDS flags", href: "/accounting/loans", icon: Landmark },
  // ACC-06 is closed. All three of these kept the CA's work in this browser's
  // localStorage; all three are on the database now — recurring journals on
  // `recurring_journal_templates` (migration 377), budgets on
  // `account_budgets` (376), and the retainer tracker on `billing_schedules`,
  // which was already built and had no caller. The `notShared` flag below is
  // kept in the TYPE with no card using it, so the next screen that needs to
  // admit the same thing has the vocabulary — but a card carrying it now
  // would be a warning that is no longer true.
  { label: "Recurring Journals", description: "Templates that generate a draft journal each period", href: "/accounting/recurring", icon: RefreshCw },
  { label: "Budget vs Actuals", description: "Compare budgeted amounts with posted entries", href: "/accounting/budget", icon: Target },
  { label: "Retainer Tracker", description: "Fixed-fee arrangements, and a draft invoice per period", href: "/accounting/retainer", icon: IndianRupee },
  { label: "MSME 43B(h) Tracker", description: "Track MSME vendor payments to avoid IT Act §43B(h) disallowance", href: "/accounting/msme-tracker", icon: FileText },
  { label: "Schedule III Statements", description: "Balance Sheet & P&L in Companies Act 2013 Schedule III format for MCA/ROC", href: "/accounting/schedule-iii", icon: ClipboardCheck },
  { label: "Trial Balance Import", description: "Import opening balances from Tally, Busy, QuickBooks, Zoho, Excel CSV", href: "/accounting/trial-balance-import", icon: Scale },
  { label: "Lock Financial Year", description: "Lock closed years to prevent accidental edits — Partner only", href: "/accounting/lock-year", icon: Lock },
];

// sweep-accounting-hub-1-04: the sidebar (AccountingPanel's NAV_GROUPS) has
// five groups — Chart of accounts, Registers, Across clients, Period close,
// Firm — and this page had a card for Registers and Period close only, so a
// CA landing here (rather than arriving already inside the sidebar) had no
// way to reach Schedule III Mapping, Account Groups, COA import/export, the
// cross-client worklists, Fee Billing or Data Migration. These three groups'
// labels, hrefs, icons and permissions are read straight off NAV_GROUPS below
// rather than copied into a second ADMIN_CARDS-shaped list, so a screen added
// to one of them shows up here too. Only the one-line description is local —
// NAV_GROUPS carries none, because the sidebar has no room for one.
const EXTRA_SECTIONS = ["Chart of accounts", "Across clients", "Firm"] as const;

const EXTRA_SECTION_DESCRIPTIONS: Record<string, string> = {
  "/accounting/schedule-iii-mapping": "Map each account to its Schedule III caption for the balance sheet and P&L",
  "/accounting/account-groups": "Organise the chart of accounts into groups and sub-groups",
  "/accounting/coa-import": "Import a chart of accounts from Tally, Busy, QuickBooks, Zoho or Excel CSV",
  "/accounting/coa-export": "Export the firm's chart of accounts",
  "/accounting/banking": "Clients whose bank lines still need review or matching",
  "/accounting/invoices": "Clients whose sales invoices need attention",
  "/accounting/purchases": "Clients whose purchase bills need attention",
  "/accounting/fixed-assets": "Clients with depreciation or fixed-asset items outstanding",
  "/accounting/year-end": "Clients whose year-end closing needs attention",
  "/billing": "Manage CA firm fee engagements and invoices",
  "/migration": "Import a client's books from Tally, Busy, QuickBooks or Zoho",
};

export default function AccountingHubPage() {
  const [practiceId, setPracticeId] = useState<string | null>(null);
  const { can } = usePermissions();
  const { userRole } = useAuth();

  // Same filter AccountingPanel applies to the same NAV_GROUPS, so a card
  // never offers a link its own sidebar would have hidden.
  const extraGroups = NAV_GROUPS.filter(
    (g) => g.heading !== null && (EXTRA_SECTIONS as readonly string[]).includes(g.heading),
  ).map((g) => ({
    heading: g.heading as string,
    items: g.items.filter(
      (i) =>
        (!i.requires || can(i.requires[0], i.requires[1])) &&
        (!i.partnerOnly || userRole === "Partner"),
    ),
  })).filter((g) => g.items.length > 0);

  useEffect(() => {
    api.practice.get()
      .then((r) => {
        const res = r as { success: boolean; data: { internal_client_id: string | null } };
        if (res.success) setPracticeId(res.data?.internal_client_id ?? null);
      })
      .catch(() => { /* practice not provisioned / no access — silently degrade */ });
  }, []);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <PageHeader
        title="Accounting — Administration"
        subtitle="Firm-level setup & registers. Day-to-day accounting happens in each client&apos;s workspace."
      />

      {/* Gateway: accounting flows through clients; the practice is just another client */}
      <Card>
        <CardContent className="pt-5 pb-4 flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
            <Building2 className="w-5 h-5 text-blue-600" />
          </div>
          <div className="flex-1">
            <p className="text-sm font-semibold text-ps-ink">Accounting runs through clients</p>
            <p className="text-xs text-ps-label mt-0.5">
              Journals, ledger, trial balance, financial statements, banking and reconciliation are all in the client workspace — backend-driven. The firm&apos;s own books are the practice client.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {practiceId && (
              <Link href={`/clients/${practiceId}/accounting`} className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-2 border border-ps-border rounded-lg hover:bg-ps-bg text-ps-label">
                Practice books
              </Link>
            )}
            <Link href="/clients" className="inline-flex items-center gap-1.5 text-xs font-medium px-4 py-2 bg-brand text-white rounded-lg hover:bg-brand-dark">
              Go to Clients <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </CardContent>
      </Card>

      {/* Firm administration registers (no duplicate accounting data-entry/reporting) */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {ADMIN_CARDS.map((card) => (
          <Link key={card.href} href={card.href}>
            <Card className="hover:shadow-md transition-shadow cursor-pointer h-full">
              <CardContent className="pt-5 pb-4 flex items-start gap-3">
                <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
                  <card.icon size={18} className="text-blue-600" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-ps-ink">{card.label}</p>
                  <p className="text-xs text-ps-label mt-0.5 leading-tight">{card.description}</p>
                  {card.notShared && (
                    <p className="text-2xs text-state-attention mt-1 leading-tight">
                      Saved in this browser only — not shared with the firm, and not
                      posted automatically.
                    </p>
                  )}
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      {/* sweep-accounting-hub-1-04: the sidebar's Chart of accounts, Across
          clients and Firm sections, with no card here until now. */}
      {extraGroups.map((group) => (
        <div key={group.heading}>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-ps-hint mb-2">{group.heading}</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {group.items.map((item) => (
              <Link key={item.href} href={item.href}>
                <Card className="hover:shadow-md transition-shadow cursor-pointer h-full">
                  <CardContent className="pt-5 pb-4 flex items-start gap-3">
                    <div className="w-9 h-9 rounded-lg bg-brand/10 flex items-center justify-center shrink-0">
                      <item.icon size={18} className="text-brand" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-ps-ink">{item.label}</p>
                      <p className="text-xs text-ps-label mt-0.5 leading-tight">
                        {EXTRA_SECTION_DESCRIPTIONS[item.href] ?? ""}
                      </p>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
