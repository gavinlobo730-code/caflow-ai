"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, CheckCircle, AlertTriangle } from "lucide-react";
import { Card } from "@/components/ui/card";
import { formatPaise } from "@/lib/services/formatting";
import type { TrialBalance, TrialBalanceLine, AccountType, ApiResponse } from "@/lib/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TYPE_COLORS: Record<AccountType, string> = {
  Asset: "text-blue-700",
  Liability: "text-red-700",
  Equity: "text-purple-700",
  Income: "text-green-700",
  Expense: "text-orange-700",
};

function LoadingSpinner() {
  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4 animate-pulse">
      <div className="h-6 bg-gray-200 rounded w-48" />
      <div className="h-10 bg-gray-100 rounded w-48" />
      <div className="h-64 bg-gray-100 rounded-xl" />
    </div>
  );
}

export default function TrialBalancePage() {
  const [asOfDate, setAsOfDate] = useState("2025-05-31");
  const [trialBalance, setTrialBalance] = useState<TrialBalance | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetch(`${BASE_URL}/api/accounting/trial-balance?as_of_date=${asOfDate}`)
      .then((r) => r.json())
      .then((res: ApiResponse<TrialBalance>) => {
        if (res.success) setTrialBalance(res.data);
        else setError(res.error ?? "Failed to load trial balance");
      })
      .catch(() => setError("Failed to load trial balance"))
      .finally(() => setLoading(false));
  }, [asOfDate]);

  if (loading) return <LoadingSpinner />;

  if (error || !trialBalance) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error ?? "No data"}</div>
      </div>
    );
  }

  const lines: TrialBalanceLine[] = trialBalance.lines.filter((l) => l.total_debit_paise > 0 || l.total_credit_paise > 0);
  const isBalanced = trialBalance.is_balanced;
  const totalDebit: number = trialBalance.total_debit_paise;
  const totalCredit: number = trialBalance.total_credit_paise;
  const difference: number = trialBalance.difference_paise;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft size={18} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Trial Balance</h1>
          <p className="text-sm text-gray-500 mt-0.5">As of {asOfDate}</p>
        </div>
      </div>

      {/* Controls */}
      <div>
        <label className="text-xs text-gray-500">As of Date</label>
        <input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)}
          className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </div>

      {/* Balance status banner */}
      <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm font-medium ${isBalanced ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
        {isBalanced
          ? <><CheckCircle size={16} /> Trial Balance is Balanced ✓</>
          : <><AlertTriangle size={16} /> Imbalanced — Difference: {formatPaise(Math.abs(difference))}</>
        }
      </div>

      {/* Table */}
      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-xs text-gray-400">
                <th className="px-5 py-3 text-left font-semibold">Code</th>
                <th className="px-3 py-3 text-left font-semibold">Account Name</th>
                <th className="px-3 py-3 text-left font-semibold">Type</th>
                <th className="px-5 py-3 text-right font-semibold">Debit</th>
                <th className="px-5 py-3 text-right font-semibold">Credit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {lines.map((line) => (
                <tr key={line.account_id} className="hover:bg-gray-50">
                  <td className="px-5 py-3 text-xs font-mono text-gray-400">{line.account_code}</td>
                  <td className="px-3 py-3 text-sm text-gray-900">{line.account_name}</td>
                  <td className={`px-3 py-3 text-xs font-medium ${TYPE_COLORS[line.account_type]}`}>{line.account_type}</td>
                  <td className="px-5 py-3 text-sm tabular-nums text-right text-gray-700">
                    {line.total_debit_paise > 0 ? formatPaise(line.total_debit_paise) : "—"}
                  </td>
                  <td className="px-5 py-3 text-sm tabular-nums text-right text-gray-700">
                    {line.total_credit_paise > 0 ? formatPaise(line.total_credit_paise) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-gray-300 bg-gray-50 font-bold text-sm">
                <td colSpan={3} className="px-5 py-3 text-gray-700">Total</td>
                <td className="px-5 py-3 text-right tabular-nums text-gray-900">{formatPaise(totalDebit)}</td>
                <td className="px-5 py-3 text-right tabular-nums text-gray-900">{formatPaise(totalCredit)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </Card>
    </div>
  );
}
