"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, TrendingUp, TrendingDown } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatPaise } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";

// Default: current FY April 1 to today
const CURRENT_FY_START = "2025-04-01";
const TODAY = new Date().toISOString().split("T")[0];

interface PLLine {
  account_name: string;
  amount_paise: number;
}

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

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).single();
  if (!data) throw new Error("User not found");
  return data.firm_id as string;
}

export default function ProfitLossPage() {
  const [startDate, setStartDate] = useState(CURRENT_FY_START);
  const [endDate, setEndDate] = useState(TODAY);
  const [incomeLines, setIncomeLines] = useState<PLLine[]>([]);
  const [expenseLines, setExpenseLines] = useState<PLLine[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const sb = getSupabaseClient();
    getFirmId()
      .then(async (fid) => {
        // Fetch income and expense accounts for this firm
        const { data: accs, error: accErr } = await sb
          .from("accounts")
          .select("id, account_name, account_type")
          .eq("firm_id", fid)
          .in("account_type", ["Revenue", "Expense"]);
        if (accErr) throw new Error(accErr.message);

        // Fetch journal entry lines for posted entries in the date range
        const { data: entryLines, error: lineErr } = await sb
          .from("journal_entry_lines")
          .select("account_id, debit_paise, credit_paise, journal_entries!inner(firm_id, entry_date, status)")
          .eq("journal_entries.firm_id", fid)
          .eq("journal_entries.status", "posted")
          .gte("journal_entries.entry_date", startDate)
          .lte("journal_entries.entry_date", endDate);
        if (lineErr) throw new Error(lineErr.message);

        // Aggregate net per account in integer paise — no floating point
        const map = new Map<string, number>();
        for (const line of (entryLines ?? [])) {
          const prev = map.get(line.account_id) ?? 0;
          // For income: credit increases, debit decreases
          map.set(line.account_id, prev + (line.credit_paise ?? 0) - (line.debit_paise ?? 0));
        }

        const income: PLLine[] = [];
        const expenses: PLLine[] = [];
        for (const acc of (accs ?? [])) {
          const net = Math.abs(map.get(acc.id) ?? 0);
          if (net === 0) continue;
          if (acc.account_type === "Revenue") {
            income.push({ account_name: acc.account_name, amount_paise: net });
          } else {
            expenses.push({ account_name: acc.account_name, amount_paise: net });
          }
        }

        setIncomeLines(income);
        setExpenseLines(expenses);
      })
      .catch((e) => setError(e.message ?? "Failed to load P&L"))
      .finally(() => setLoading(false));
  }, [startDate, endDate]);

  // All paise arithmetic — integers only
  const totalRevenuePaise: number = incomeLines.reduce((s, l) => s + l.amount_paise, 0);
  const totalExpensesPaise: number = expenseLines.reduce((s, l) => s + l.amount_paise, 0);
  const netProfitPaise: number = totalRevenuePaise - totalExpensesPaise;

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

      {!loading && !error && (
        <>
          {incomeLines.length === 0 && expenseLines.length === 0 ? (
            <div className="bg-gray-50 rounded-xl border border-gray-100 p-12 text-center">
              <p className="text-sm text-gray-500">No posted transactions found for this period.</p>
            </div>
          ) : (
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
                    {incomeLines.map((l) => (
                      <div key={l.account_name} className="flex items-center justify-between py-2">
                        <span className="text-sm text-gray-700">{l.account_name}</span>
                        <span className="text-sm tabular-nums font-medium text-gray-900">{formatPaise(l.amount_paise)}</span>
                      </div>
                    ))}
                    {incomeLines.length === 0 && <p className="text-sm text-gray-400 py-2">No revenue accounts</p>}
                  </div>
                  <div className="flex items-center justify-between pt-3 border-t border-gray-200 font-semibold">
                    <span className="text-sm text-gray-900">Total Revenue</span>
                    <span className="text-sm tabular-nums text-green-700">{formatPaise(totalRevenuePaise)}</span>
                  </div>
                </CardContent>
              </Card>

              {/* Operating Expenses */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2 text-red-700">
                    <TrendingDown size={15} /> Operating Expenses
                  </CardTitle>
                </CardHeader>
                <CardContent className="pb-4">
                  <div className="divide-y divide-gray-50">
                    {expenseLines.map((l) => (
                      <div key={l.account_name} className="flex items-center justify-between py-2">
                        <span className="text-sm text-gray-700">{l.account_name}</span>
                        <span className="text-sm tabular-nums font-medium text-gray-900">{formatPaise(l.amount_paise)}</span>
                      </div>
                    ))}
                    {expenseLines.length === 0 && <p className="text-sm text-gray-400 py-2">No expense accounts</p>}
                  </div>
                  <div className="flex items-center justify-between pt-3 border-t border-gray-200 font-semibold">
                    <span className="text-sm text-gray-900">Total Expenses</span>
                    <span className="text-sm tabular-nums text-red-600">{formatPaise(totalExpensesPaise)}</span>
                  </div>
                </CardContent>
              </Card>

              {/* Net Profit / Loss */}
              <div className={`rounded-lg px-5 py-4 flex items-center justify-between ${netProfitPaise >= 0 ? "bg-green-50" : "bg-red-50"}`}>
                <span className={`text-base font-bold ${netProfitPaise >= 0 ? "text-green-900" : "text-red-900"}`}>
                  {netProfitPaise >= 0 ? "Net Profit" : "Net Loss"}
                </span>
                <span className={`text-lg font-bold tabular-nums ${netProfitPaise >= 0 ? "text-green-700" : "text-red-700"}`}>
                  {formatPaise(Math.abs(netProfitPaise))}
                </span>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
