"use client";
export const runtime = "edge";

import { useState } from "react";
import Link from "next/link";
import { ChevronLeft, CheckCircle, AlertTriangle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatPaise } from "@/lib/services/formatting";
import type { BalanceSheet, BalanceSheetSection } from "@/lib/types";

// Mock balance sheet — all amounts in paise (integer), never float
const MOCK_BS: BalanceSheet = {
  as_of_date: "2025-05-31",
  assets: [
    {
      label: "Assets",
      lines: [
        { account_name: "Bank — HDFC Current Account", balance_paise: 44300000 },
        { account_name: "Trade Receivables", balance_paise: 3540000 },
        { account_name: "GST Input Tax Credit", balance_paise: 0 },
        { account_name: "Advance Tax Paid", balance_paise: 0 },
        { account_name: "Office Equipment", balance_paise: 0 },
        { account_name: "Furniture & Fixtures", balance_paise: 0 },
      ].filter((l) => l.balance_paise > 0),
      total_paise: 47840000,
    },
  ],
  liabilities: [
    {
      label: "Liabilities",
      lines: [
        { account_name: "GST Output Tax Payable", balance_paise: 1080000 },
        { account_name: "TDS Payable", balance_paise: 350000 },
      ],
      total_paise: 1430000,
    },
  ],
  equity: [
    {
      label: "Equity",
      lines: [
        { account_name: "Capital Account", balance_paise: 50000000 },
        { account_name: "Net Loss (Current Year)", balance_paise: -3590000 },
      ],
      total_paise: 46410000,
    },
  ],
  total_assets_paise: 47840000,
  total_liabilities_equity_paise: 47840000,
  is_balanced: true,
};

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
  const [asOfDate, setAsOfDate] = useState("2025-05-31");
  const bs = MOCK_BS;

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
