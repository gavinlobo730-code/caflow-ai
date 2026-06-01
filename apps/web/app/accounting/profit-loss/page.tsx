"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, TrendingUp, TrendingDown } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatPaise } from "@/lib/services/formatting";
import type { ProfitLoss, ApiResponse } from "@/lib/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Default: current FY April 1 to today
const CURRENT_FY_START = "2025-04-01";
const TODAY = new Date().toISOString().split("T")[0];

function LoadingSpinner() {
  return (
    <div className="p-6 max-w-3xl mx-auto space-y-4 animate-pulse">
      <div className="h-6 bg-gray-200 rounded w-48" />
      <div className="h-32 bg-gray-100 rounded-xl" />
      <div className="h-32 bg-gray-100 rounded-xl" />
      <div className="h-20 bg-gray-100 rounded-xl" />
    </div>
  );
}

export default function ProfitLossPage() {
  const [startDate, setStartDate] = useState(CURRENT_FY_START);
  const [endDate, setEndDate] = useState(TODAY);
  const [pl, setPl] = useState<ProfitLoss | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
    fetch(`${BASE_URL}/api/accounting/profit-loss?${params}`)
      .then((r) => r.json())
      .then((res: ApiResponse<ProfitLoss>) => {
        if (res.success) setPl(res.data);
        else setError(res.error ?? "Failed to load P&L");
      })
      .catch(() => setError("Failed to load P&L"))
      .finally(() => setLoading(false));
  }, [startDate, endDate]);

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

      {loading && <LoadingSpinner />}

      {error && (
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>
      )}

      {!loading && !error && pl && (
        <>
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
          <div className={`rounded-lg px-5 py-4 flex items-center justify-between ${pl.net_profit_paise >= 0 ? "bg-green-50" : "bg-red-50"}`}>
            <span className={`text-base font-bold ${pl.net_profit_paise >= 0 ? "text-green-900" : "text-red-900"}`}>
              {pl.net_profit_paise >= 0 ? "Net Profit" : "Net Loss"}
            </span>
            <span className={`text-lg font-bold tabular-nums ${pl.net_profit_paise >= 0 ? "text-green-700" : "text-red-700"}`}>
              {formatPaise(Math.abs(pl.net_profit_paise))}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
