"use client";
export const runtime = "edge";

import { useState } from "react";
import Link from "next/link";
import { ChevronLeft, TrendingUp, TrendingDown } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatPaise } from "@/lib/services/formatting";
import type { ProfitLoss } from "@/lib/types";

// Mock P&L data — all amounts in paise (integer), never float
const MOCK_PL: ProfitLoss = {
  start_date: "2025-04-01",
  end_date: "2025-05-31",
  revenue: {
    label: "Revenue",
    lines: [
      { account_name: "Professional Fees — GST Clients", amount_paise: 1000000 },
      { account_name: "Professional Fees — ITR Clients", amount_paise: 2000000 },
      { account_name: "Audit Fees", amount_paise: 3000000 },
    ],
    total_paise: 6000000,
  },
  cost_of_sales: {
    label: "Cost of Sales",
    lines: [],
    total_paise: 0,
  },
  gross_profit_paise: 6000000,
  operating_expenses: {
    label: "Operating Expenses",
    lines: [
      { account_name: "Salary Expense", amount_paise: 5000000 },
      { account_name: "Office Rent", amount_paise: 3500000 },
      { account_name: "Software Subscriptions", amount_paise: 500000 },
      { account_name: "Bank Charges", amount_paise: 50000 },
    ],
    total_paise: 9050000,
  },
  net_profit_paise: -3050000,
};

export default function ProfitLossPage() {
  const [startDate, setStartDate] = useState("2025-04-01");
  const [endDate, setEndDate] = useState("2025-05-31");
  const pl = MOCK_PL;
  const isProfit = pl.net_profit_paise >= 0;

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft size={18} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Profit & Loss Statement</h1>
          <p className="text-sm text-gray-500 mt-0.5">{startDate} to {endDate}</p>
        </div>
      </div>

      {/* Date range */}
      <div className="flex gap-3">
        <div>
          <label className="text-xs text-gray-500">From</label>
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
            className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label className="text-xs text-gray-500">To</label>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
            className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
      </div>

      {/* Revenue */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2 text-green-700">
            <TrendingUp size={15} /> Revenue
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-4">
          <div className="divide-y divide-gray-50">
            {pl.revenue.lines.map((l) => (
              <div key={l.account_name} className="flex items-center justify-between py-2">
                <span className="text-sm text-gray-700">{l.account_name}</span>
                <span className="text-sm tabular-nums font-medium text-gray-900">{formatPaise(l.amount_paise)}</span>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between pt-3 border-t border-gray-200 font-semibold">
            <span className="text-sm text-gray-900">Total Revenue</span>
            <span className="text-sm tabular-nums text-green-700">{formatPaise(pl.revenue.total_paise)}</span>
          </div>
        </CardContent>
      </Card>

      {/* Cost of Sales */}
      {pl.cost_of_sales.lines.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-gray-700">Cost of Sales</CardTitle>
          </CardHeader>
          <CardContent className="pb-4">
            {pl.cost_of_sales.lines.map((l) => (
              <div key={l.account_name} className="flex items-center justify-between py-2">
                <span className="text-sm text-gray-700">{l.account_name}</span>
                <span className="text-sm tabular-nums font-medium text-gray-900">{formatPaise(l.amount_paise)}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Gross Profit */}
      <div className="bg-blue-50 rounded-lg px-5 py-3 flex items-center justify-between">
        <span className="text-sm font-semibold text-blue-900">Gross Profit</span>
        <span className="text-sm font-bold tabular-nums text-blue-700">{formatPaise(pl.gross_profit_paise)}</span>
      </div>

      {/* Operating Expenses */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2 text-red-700">
            <TrendingDown size={15} /> Operating Expenses
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-4">
          <div className="divide-y divide-gray-50">
            {pl.operating_expenses.lines.map((l) => (
              <div key={l.account_name} className="flex items-center justify-between py-2">
                <span className="text-sm text-gray-700">{l.account_name}</span>
                <span className="text-sm tabular-nums font-medium text-gray-900">{formatPaise(l.amount_paise)}</span>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between pt-3 border-t border-gray-200 font-semibold">
            <span className="text-sm text-gray-900">Total Expenses</span>
            <span className="text-sm tabular-nums text-red-600">{formatPaise(pl.operating_expenses.total_paise)}</span>
          </div>
        </CardContent>
      </Card>

      {/* Net Profit / Loss */}
      <div className={`rounded-lg px-5 py-4 flex items-center justify-between ${isProfit ? "bg-green-50" : "bg-red-50"}`}>
        <span className={`text-base font-bold ${isProfit ? "text-green-900" : "text-red-900"}`}>
          {isProfit ? "Net Profit" : "Net Loss"}
        </span>
        <span className={`text-lg font-bold tabular-nums ${isProfit ? "text-green-700" : "text-red-700"}`}>
          {formatPaise(Math.abs(pl.net_profit_paise))}
        </span>
      </div>
    </div>
  );
}
