"use client";
export const runtime = "edge";

import { TrendingUp, TrendingDown, DollarSign, CreditCard, ArrowUpRight, ArrowDownRight, Building } from "lucide-react";
import { StatCard } from "@/components/stat-card";
import { AIInsightBanner } from "@/components/ai-insight-banner";

const STATS = [
  { label: "Revenue (This Month)", value: "₹8,42,500", icon: TrendingUp, iconColor: "text-green-600", iconBg: "bg-green-50" },
  { label: "Expenses (This Month)", value: "₹3,18,200", icon: TrendingDown, iconColor: "text-red-500", iconBg: "bg-red-50" },
  { label: "Net Profit", value: "₹5,24,300", icon: DollarSign, iconColor: "text-blue-600", iconBg: "bg-blue-50" },
  { label: "GST Collected", value: "₹1,51,650", icon: CreditCard, iconColor: "text-purple-600", iconBg: "bg-purple-50" },
  { label: "GST Paid (ITC)", value: "₹57,276", icon: CreditCard, iconColor: "text-indigo-600", iconBg: "bg-indigo-50" },
  { label: "Outstanding Receivables", value: "₹2,10,000", icon: Building, iconColor: "text-amber-600", iconBg: "bg-amber-50", alert: true },
];

const TRANSACTIONS = [
  { id: 1, date: "01 Jun 2025", description: "Sales Invoice — Sharma Enterprises", type: "credit", amount: "₹1,18,000", category: "Sales" },
  { id: 2, date: "01 Jun 2025", description: "Purchase — Hindustan Goods Suppliers", type: "debit", amount: "₹45,500", category: "Purchase" },
  { id: 3, date: "31 May 2025", description: "Office Rent — MG Road", type: "debit", amount: "₹35,000", category: "Expense" },
  { id: 4, date: "31 May 2025", description: "Sales Invoice — Patel & Sons", type: "credit", amount: "₹2,36,000", category: "Sales" },
  { id: 5, date: "30 May 2025", description: "GST Payment — CGST/SGST", type: "debit", amount: "₹18,500", category: "Tax" },
];

const INSIGHTS = [
  { type: "high" as const, message: "Outstanding receivables of ₹2,10,000 pending for >30 days", action: "Review and send payment reminders to 3 clients" },
  { type: "info" as const, message: "Profit margin at 62% — above industry average for CA firms" },
];

const TABS = ["Overview", "Sales", "Purchases", "Expenses", "Bank Transactions", "Trial Balance", "P&L", "Balance Sheet"];

export default function AccountingPage() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Accounting</h1>
        <p className="text-sm text-gray-500 mt-0.5">Financial overview — FY 2024-25</p>
      </div>

      <AIInsightBanner insights={INSIGHTS} />

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {STATS.map((s) => <StatCard key={s.label} {...s} />)}
      </div>

      {/* Tab strip */}
      <div className="flex gap-1 border-b border-gray-100">
        {TABS.map((tab, i) => (
          <button key={tab} className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${i === 0 ? "border-blue-600 text-blue-700" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
            {tab}
          </button>
        ))}
      </div>

      {/* Recent transactions */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <h2 className="text-sm font-semibold text-gray-900">Recent Transactions</h2>
        </div>
        <div className="divide-y divide-gray-50">
          {TRANSACTIONS.map((tx) => (
            <div key={tx.id} className="flex items-center gap-4 px-5 py-3.5">
              <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${tx.type === "credit" ? "bg-green-50" : "bg-red-50"}`}>
                {tx.type === "credit" ? <ArrowUpRight size={14} className="text-green-600" /> : <ArrowDownRight size={14} className="text-red-500" />}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-900 truncate">{tx.description}</p>
                <p className="text-xs text-gray-400 mt-0.5">{tx.date} · {tx.category}</p>
              </div>
              <p className={`text-sm font-semibold tabular-nums ${tx.type === "credit" ? "text-green-700" : "text-red-600"}`}>
                {tx.type === "credit" ? "+" : "-"}{tx.amount}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
