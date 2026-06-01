"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, CheckCircle, AlertTriangle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatPaise } from "@/lib/services/formatting";
import type { BalanceSheet, BalanceSheetSection, ApiResponse } from "@/lib/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TODAY = new Date().toISOString().split("T")[0];

function LoadingSpinner() {
  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4 animate-pulse">
      <div className="h-6 bg-gray-200 rounded w-48" />
      <div className="h-10 bg-gray-100 rounded w-48" />
      <div className="grid grid-cols-2 gap-6">
        <div className="h-64 bg-gray-100 rounded-xl" />
        <div className="h-64 bg-gray-100 rounded-xl" />
      </div>
    </div>
  );
}

function BSSection({ section }: { section: BalanceSheetSection }) {
  return (
    <div className="divide-y divide-gray-50">
      {section.lines.map((l) => (
        <div key={l.account_name} className="flex items-center justify-between py-2">
          <span className="text-sm text-gray-700">{l.account_name}</span>
          <span className={`text-sm tabular-nums font-medium ${l.balance_paise < 0 ? "text-red-600" : "text-gray-900"}`}>
            {l.balance_paise < 0 ? `(${formatPaise(Math.abs(l.balance_paise))})` : formatPaise(l.balance_paise)}
          </span>
        </div>
      ))}
      <div className="flex items-center justify-between py-2.5 font-semibold border-t border-gray-200 mt-1">
        <span className="text-sm text-gray-900">Total {section.label}</span>
        <span className="text-sm tabular-nums text-gray-900">{formatPaise(section.total_paise)}</span>
      </div>
    </div>
  );
}

export default function BalanceSheetPage() {
  const [asOfDate, setAsOfDate] = useState(TODAY);
  const [bs, setBs] = useState<BalanceSheet | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetch(`${BASE_URL}/api/accounting/balance-sheet?as_of_date=${asOfDate}`)
      .then((r) => r.json())
      .then((res: ApiResponse<BalanceSheet>) => {
        if (res.success) setBs(res.data);
        else setError(res.error ?? "Failed to load balance sheet");
      })
      .catch(() => setError("Failed to load balance sheet"))
      .finally(() => setLoading(false));
  }, [asOfDate]);

  if (loading) return <LoadingSpinner />;

  if (error || !bs) {
    return (
      <div className="p-6 max-w-4xl mx-auto">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error ?? "No data"}</div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft size={18} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Balance Sheet</h1>
          <p className="text-sm text-gray-500 mt-0.5">As of {asOfDate}</p>
        </div>
      </div>

      {/* Controls */}
      <div>
        <label className="text-xs text-gray-500">As of Date</label>
        <input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)}
          className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </div>

      {/* Balance check */}
      <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm font-medium ${bs.is_balanced ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
        {bs.is_balanced
          ? <><CheckCircle size={16} /> Balance Sheet balances ✓ — Assets = Liabilities + Equity</>
          : <><AlertTriangle size={16} /> Balance Sheet does not balance — check entries</>
        }
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Left: Assets */}
        <div className="space-y-4">
          {bs.assets.map((section) => (
            <Card key={section.label}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm text-blue-700">{section.label}</CardTitle>
              </CardHeader>
              <CardContent className="pb-4">
                <BSSection section={section} />
              </CardContent>
            </Card>
          ))}

          {/* Total Assets */}
          <div className="bg-blue-50 rounded-lg px-5 py-3 flex items-center justify-between">
            <span className="text-sm font-bold text-blue-900">Total Assets</span>
            <span className="text-sm font-bold tabular-nums text-blue-700">{formatPaise(bs.total_assets_paise)}</span>
          </div>
        </div>

        {/* Right: Liabilities + Equity */}
        <div className="space-y-4">
          {bs.liabilities.map((section) => (
            <Card key={section.label}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm text-red-700">{section.label}</CardTitle>
              </CardHeader>
              <CardContent className="pb-4">
                <BSSection section={section} />
              </CardContent>
            </Card>
          ))}
          {bs.equity.map((section) => (
            <Card key={section.label}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm text-purple-700">{section.label}</CardTitle>
              </CardHeader>
              <CardContent className="pb-4">
                <BSSection section={section} />
              </CardContent>
            </Card>
          ))}

          {/* Total Liabilities + Equity */}
          <div className="bg-purple-50 rounded-lg px-5 py-3 flex items-center justify-between">
            <span className="text-sm font-bold text-purple-900">Total Liabilities + Equity</span>
            <span className="text-sm font-bold tabular-nums text-purple-700">{formatPaise(bs.total_liabilities_equity_paise)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
