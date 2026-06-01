"use client";
export const runtime = "edge";

import Link from "next/link";
import { BookOpen, FileText, BarChart2, Scale, TrendingUp, List, ArrowUpRight, ArrowDownRight } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatPaise, formatDate } from "@/lib/services/formatting";
import type { JournalEntry } from "@/lib/types";

// Mock summary stats — wire to /api/accounting/* once backend is running
const STATS = [
  { label: "Total Accounts", value: "22", icon: List },
  { label: "Journal Entries", value: "10", icon: FileText },
  { label: "Trial Balance", value: "Balanced", icon: Scale, highlight: "green" },
  { label: "Cash & Bank Balance", value: formatPaise(43360000), icon: BarChart2 },
];

const NAV_CARDS = [
  { label: "Chart of Accounts", description: "View and manage your account tree", href: "/accounting/chart-of-accounts", icon: List },
  { label: "Journal Entries", description: "Record and post accounting entries", href: "/accounting/journal", icon: FileText },
  { label: "General Ledger", description: "Transaction history per account", href: "/accounting/ledger", icon: BookOpen },
  { label: "Trial Balance", description: "Verify debit/credit totals", href: "/accounting/trial-balance", icon: Scale },
  { label: "Profit & Loss", description: "Revenue, expenses and net profit", href: "/accounting/profit-loss", icon: TrendingUp },
  { label: "Balance Sheet", description: "Assets, liabilities and equity", href: "/accounting/balance-sheet", icon: BarChart2 },
];

const RECENT_ENTRIES: JournalEntry[] = [
  {
    id: "je-010", client_id: "c-001", entry_date: "2025-05-31", reference_no: "BNK/2025-26/001",
    narration: "Bank charges — HDFC May 2025", entry_type: "Journal", status: "posted",
    lines: [], total_debit_paise: 50000, total_credit_paise: 50000, created_at: "2025-05-31T18:00:00+05:30",
  },
  {
    id: "je-008", client_id: "c-001", entry_date: "2025-05-01", reference_no: "EXP/2025-26/002",
    narration: "Software subscription — Winman, Tally", entry_type: "Payment", status: "posted",
    lines: [], total_debit_paise: 500000, total_credit_paise: 500000, created_at: "2025-05-01T09:00:00+05:30",
  },
  {
    id: "je-007", client_id: "c-001", entry_date: "2025-05-20", reference_no: "GST/2025-26/001",
    narration: "GST payment — April 2025 GSTR-3B", entry_type: "Payment", status: "posted",
    lines: [], total_debit_paise: 540000, total_credit_paise: 540000, created_at: "2025-05-20T14:00:00+05:30",
  },
  {
    id: "je-006", client_id: "c-005", entry_date: "2025-05-15", reference_no: "REC/2025-26/001",
    narration: "Receipt from Joshi Textiles — ITR fees", entry_type: "Receipt", status: "posted",
    lines: [], total_debit_paise: 2360000, total_credit_paise: 2360000, created_at: "2025-05-15T12:00:00+05:30",
  },
  {
    id: "je-005", client_id: "c-005", entry_date: "2025-05-10", reference_no: "INV/2025-26/002",
    narration: "ITR filing fees — Joshi Textiles", entry_type: "Sales", status: "posted",
    lines: [], total_debit_paise: 2360000, total_credit_paise: 2360000, created_at: "2025-05-10T10:00:00+05:30",
  },
];

const statusBadge: Record<string, string> = {
  posted: "bg-green-100 text-green-700",
  draft: "bg-amber-100 text-amber-700",
};

export default function AccountingHubPage() {
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
              <p className={`text-xl font-bold ${s.highlight === "green" ? "text-green-600" : "text-gray-900"}`}>{s.value}</p>
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
        <div className="divide-y divide-gray-50">
          {RECENT_ENTRIES.map((entry) => (
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
        </div>
      </Card>
    </div>
  );
}
