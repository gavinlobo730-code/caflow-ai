"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { RefreshCw, Target, FileText, ClipboardCheck, IndianRupee, Scale, Lock, Landmark, Users, Clock, Building2, ArrowRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { api } from "@/lib/api";

// Phase 3 consolidation: this is the firm ADMINISTRATION hub only. Day-to-day
// accounting — journals, ledger, trial balance, P&L, balance sheet, cash flow,
// banking and reconciliation — happens inside each client's workspace
// (Client → Accounting), powered by the single backend reporting engine. The
// firm's own books are the internal "practice" client. The old duplicate
// firm-level accounting screens have been retired.
const ADMIN_CARDS = [
  { label: "Supplier Master", description: "Manage supplier TDS sections, credit limits and payment terms", href: "/accounting/suppliers", icon: Users },
  { label: "Receivables Aging", description: "Outstanding invoices grouped by aging bucket", href: "/accounting/receivables", icon: Clock },
  { label: "Loans & FD", description: "Loans, EMI schedules and FD investments with maturity & TDS flags", href: "/accounting/loans", icon: Landmark },
  { label: "Recurring Transactions", description: "Automate monthly, quarterly & yearly entries", href: "/accounting/recurring", icon: RefreshCw },
  { label: "Budget vs Actuals", description: "Compare budgeted amounts with posted entries", href: "/accounting/budget", icon: Target },
  { label: "Retainer Tracker", description: "Track monthly retainer clients and generate GST invoices", href: "/accounting/retainer", icon: IndianRupee },
  { label: "MSME 43B(h) Tracker", description: "Track MSME vendor payments to avoid IT Act §43B(h) disallowance", href: "/accounting/msme-tracker", icon: FileText },
  { label: "Schedule III Statements", description: "Balance Sheet & P&L in Companies Act 2013 Schedule III format for MCA/ROC", href: "/accounting/schedule-iii", icon: ClipboardCheck },
  { label: "Trial Balance Import", description: "Import opening balances from Tally, Busy, QuickBooks, Zoho, Excel CSV", href: "/accounting/trial-balance-import", icon: Scale },
  { label: "Lock Financial Year", description: "Lock closed years to prevent accidental edits — Partner only", href: "/accounting/lock-year", icon: Lock },
];

export default function AccountingHubPage() {
  const [practiceId, setPracticeId] = useState<string | null>(null);

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
      <div>
        <h1 className="text-xl font-semibold text-[#0F172A]">Accounting — Administration</h1>
        <p className="text-sm text-[#64748B] mt-0.5">Firm-level setup & registers. Day-to-day accounting happens in each client&apos;s workspace.</p>
      </div>

      {/* Gateway: accounting flows through clients; the practice is just another client */}
      <Card>
        <CardContent className="pt-5 pb-4 flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
            <Building2 className="w-5 h-5 text-blue-600" />
          </div>
          <div className="flex-1">
            <p className="text-sm font-semibold text-[#0F172A]">Accounting runs through clients</p>
            <p className="text-xs text-[#64748B] mt-0.5">
              Journals, ledger, trial balance, financial statements, banking and reconciliation are all in the client workspace — backend-driven. The firm&apos;s own books are the practice client.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {practiceId && (
              <Link href={`/clients/${practiceId}/accounting`} className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569]">
                Practice books
              </Link>
            )}
            <Link href="/clients" className="inline-flex items-center gap-1.5 text-xs font-medium px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
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
                  <p className="text-sm font-semibold text-[#0F172A]">{card.label}</p>
                  <p className="text-xs text-[#64748B] mt-0.5 leading-tight">{card.description}</p>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
