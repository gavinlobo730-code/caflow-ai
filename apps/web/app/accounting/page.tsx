"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { BookOpen, FileText, BarChart2, Scale, TrendingUp, List, ArrowUpRight, ArrowDownRight, Building2, Receipt, RefreshCw, Target, IndianRupee, ClipboardCheck, Lock, Layers, Landmark } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";
import type { JournalEntry, Account } from "@/lib/types";

const NAV_CARDS = [
  { label: "Invoices", description: "Sales & purchase invoices with GST tracking", href: "/accounting/invoices", icon: Receipt },
  { label: "Chart of Accounts", description: "View and manage your account tree", href: "/accounting/chart-of-accounts", icon: List },
  { label: "Journal Entries", description: "Record and post accounting entries", href: "/accounting/journal", icon: FileText },
  { label: "General Ledger", description: "Transaction history per account", href: "/accounting/ledger", icon: BookOpen },
  { label: "Trial Balance", description: "Verify debit/credit totals", href: "/accounting/trial-balance", icon: Scale },
  { label: "Profit & Loss", description: "Revenue, expenses and net profit", href: "/accounting/profit-loss", icon: TrendingUp },
  { label: "Balance Sheet", description: "Assets, liabilities and equity", href: "/accounting/balance-sheet", icon: BarChart2 },
  { label: "Bank Statement Import", description: "Import CSV statements from any Indian bank", href: "/accounting/bank-import", icon: ArrowDownRight },
  { label: "Bank Statements", description: "Allocate and post bank transactions", href: "/accounting/bank-statements", icon: Building2 },
  { label: "Recurring Transactions", description: "Automate monthly, quarterly & yearly entries", href: "/accounting/recurring", icon: RefreshCw },
  { label: "Budget vs Actuals", description: "Compare budgeted amounts with posted entries", href: "/accounting/budget", icon: Target },
  { label: "MSME 43B(h) Tracker", description: "Track MSME vendor payments to avoid IT Act Section 43B(h) disallowance", href: "/accounting/msme-tracker", icon: FileText },
  { label: "Schedule III Statements", description: "Balance Sheet & P&L in Companies Act 2013 Schedule III format for MCA/ROC filing", href: "/accounting/schedule-iii", icon: ClipboardCheck },
  { label: "Retainer Tracker", description: "Track monthly retainer clients, work done, and generate GST invoices", href: "/accounting/retainer", icon: IndianRupee },
  { label: "Bank Reconciliation", description: "Match bank statement transactions with journal ledger entries", href: "/accounting/bank-reconciliation", icon: ArrowUpRight },
  { label: "Trial Balance Import", description: "Import opening balances from Tally, Busy, QuickBooks, Zoho, Excel CSV", href: "/accounting/trial-balance-import", icon: Scale },
  { label: "Lock Financial Year", description: "Lock closed years to prevent accidental edits — Partner only", href: "/accounting/lock-year", icon: Lock },
  { label: "Fixed Assets", description: "Asset register with SL/WDV depreciation per IT Act 1961 Schedule II", href: "/accounting/fixed-assets", icon: Layers },
  { label: "Loans & FD", description: "Track client loans, EMI schedules and FD investments with maturity alerts and TDS flags", href: "/accounting/loans", icon: Landmark },
];

const statusBadge: Record<string, string> = {
  posted: "bg-green-100 text-green-700",
  draft: "bg-amber-100 text-amber-700",
};

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found — please complete onboarding");
  return data.firm_id as string;
}

export default function AccountingHubPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const sb = getSupabaseClient();
    getFirmId()
      .then(async (fid) => {
        const [{ data: accs }, { data: jes }] = await Promise.all([
          sb.from("accounts").select("*").eq("firm_id", fid),
          sb.from("journal_entries").select("*").eq("firm_id", fid).order("entry_date", { ascending: false }).limit(5),
        ]);
        setAccounts((accs ?? []) as Account[]);
        setEntries((jes ?? []) as JournalEntry[]);
      })
      .catch(() => { /* silently degrade */ })
      .finally(() => setLoading(false));
  }, []);

  const STATS = [
    { label: "Total Accounts", value: loading ? "…" : String(accounts.length), icon: List },
    { label: "Journal Entries", value: loading ? "…" : String(entries.length), icon: FileText },
    { label: "Posted Entries", value: loading ? "…" : String(entries.filter(e => e.status === "posted").length), icon: Scale, highlight: undefined as string | undefined },
    { label: "Draft Entries", value: loading ? "…" : String(entries.filter(e => e.status === "draft").length), icon: BarChart2 },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Accounting</h1>
          <p className="text-sm text-gray-500 mt-0.5">Double-entry books — FY 2025-26</p>
        </div>
        <Link href="/accounting/journal" className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700 transition-colors">
          + New Journal Entry
        </Link>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {STATS.map((s) => (
          <Card key={s.label}>
            <CardContent className="pt-5 pb-4">
              <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center mb-3">
                <s.icon size={16} className="text-blue-600" />
              </div>
              <p className="text-xl font-bold text-gray-900">{s.value}</p>
              <p className="text-xs text-gray-500 mt-0.5">{s.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Navigation cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {NAV_CARDS.map((card) => (
          <Link key={card.href} href={card.href}>
            <Card className="hover:shadow-md transition-shadow cursor-pointer h-full">
              <CardContent className="pt-5 pb-4 flex items-start gap-3">
                <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
                  <card.icon size={18} className="text-blue-600" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-gray-900">{card.label}</p>
                  <p className="text-xs text-gray-500 mt-0.5 leading-tight">{card.description}</p>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      {/* Recent journal entries */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <CardTitle className="text-sm">Recent Journal Entries</CardTitle>
          <Link href="/accounting/journal" className="text-xs text-blue-600 hover:underline">View all →</Link>
        </CardHeader>
        {loading ? (
          <div className="px-5 py-6 text-sm text-gray-400 text-center animate-pulse">Loading…</div>
        ) : (
          <div className="divide-y divide-gray-50">
            {entries.map((entry) => (
              <div key={entry.id} className="flex items-center gap-4 px-5 py-3.5">
                <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${entry.entry_type === "Receipt" || entry.entry_type === "Sales" ? "bg-green-50" : "bg-blue-50"}`}>
                  {entry.entry_type === "Receipt" || entry.entry_type === "Sales"
                    ? <ArrowUpRight size={14} className="text-green-600" />
                    : <ArrowDownRight size={14} className="text-blue-500" />}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-900 truncate">{entry.narration}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{formatDate(entry.entry_date)} · {entry.reference_no} · {entry.entry_type}</p>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${statusBadge[entry.status]}`}>{entry.status}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 font-medium ${entry.is_posted ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-700"}`}>
                  {entry.is_posted ? "Posted" : "Draft"}
                </span>
              </div>
            ))}
            {entries.length === 0 && (
              <div className="px-5 py-6 text-sm text-gray-400 text-center">No entries yet</div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
