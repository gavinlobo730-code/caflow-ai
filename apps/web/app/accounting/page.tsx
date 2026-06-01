"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { BookOpen, FileText, BarChart2, Scale, TrendingUp, List, ArrowUpRight, ArrowDownRight, Building2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatPaise, formatDate } from "@/lib/services/formatting";
import type { JournalEntry, Account, TrialBalance, ApiResponse } from "@/lib/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const NAV_CARDS = [
  { label: "Chart of Accounts", description: "View and manage your account tree", href: "/accounting/chart-of-accounts", icon: List },
  { label: "Journal Entries", description: "Record and post accounting entries", href: "/accounting/journal", icon: FileText },
  { label: "General Ledger", description: "Transaction history per account", href: "/accounting/ledger", icon: BookOpen },
  { label: "Trial Balance", description: "Verify debit/credit totals", href: "/accounting/trial-balance", icon: Scale },
  { label: "Profit & Loss", description: "Revenue, expenses and net profit", href: "/accounting/profit-loss", icon: TrendingUp },
  { label: "Balance Sheet", description: "Assets, liabilities and equity", href: "/accounting/balance-sheet", icon: BarChart2 },
  { label: "Bank Statement Import", description: "Import CSV statements from any Indian bank", href: "/accounting/bank-import", icon: ArrowDownRight },
  { label: "Bank Statements", description: "Allocate and post bank transactions", href: "/accounting/bank-statements", icon: Building2 },
];

const statusBadge: Record<string, string> = {
  posted: "bg-green-100 text-green-700",
  draft: "bg-amber-100 text-amber-700",
};

export default function AccountingHubPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [trialBalance, setTrialBalance] = useState<TrialBalance | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch(`${BASE_URL}/api/accounting/accounts`).then((r) => r.json()) as Promise<ApiResponse<Account[]>>,
      fetch(`${BASE_URL}/api/accounting/journal`).then((r) => r.json()) as Promise<ApiResponse<JournalEntry[]>>,
      fetch(`${BASE_URL}/api/accounting/trial-balance`).then((r) => r.json()) as Promise<ApiResponse<TrialBalance>>,
    ])
      .then(([aRes, jRes, tbRes]) => {
        if (aRes.success) setAccounts(aRes.data);
        if (jRes.success) setEntries(jRes.data);
        if (tbRes.success) setTrialBalance(tbRes.data);
      })
      .catch(() => { /* silently degrade */ })
      .finally(() => setLoading(false));
  }, []);

  const recentEntries = entries.slice(0, 5);
  const tbStatus = trialBalance ? (trialBalance.is_balanced ? "Balanced" : "Imbalanced") : "—";
  const tbColor = trialBalance ? (trialBalance.is_balanced ? "green" : "red") : undefined;

  const STATS = [
    { label: "Total Accounts", value: loading ? "…" : String(accounts.length), icon: List },
    { label: "Journal Entries", value: loading ? "…" : String(entries.length), icon: FileText },
    { label: "Trial Balance", value: loading ? "…" : tbStatus, icon: Scale, highlight: tbColor },
    { label: "Cash & Bank Balance", value: loading ? "…" : (accounts.length > 0 ? "—" : "—"), icon: BarChart2 },
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
              <p className={`text-xl font-bold ${s.highlight === "green" ? "text-green-600" : s.highlight === "red" ? "text-red-600" : "text-gray-900"}`}>{s.value}</p>
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
            {recentEntries.map((entry) => (
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
                <p className="text-sm font-semibold tabular-nums text-gray-700 shrink-0">
                  {formatPaise(entry.total_debit_paise)}
                </p>
              </div>
            ))}
            {recentEntries.length === 0 && (
              <div className="px-5 py-6 text-sm text-gray-400 text-center">No entries yet</div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
