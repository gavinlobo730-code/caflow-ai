"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, CheckCircle, AlertTriangle, Download } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { formatPaise } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";
import * as XLSX from "xlsx";
import type { AccountType } from "@/lib/types";

interface TrialBalanceLine {
  account_id: string;
  account_code: string;
  account_name: string;
  account_type: AccountType;
  total_debit_paise: number;
  total_credit_paise: number;
}

const TYPE_COLORS: Record<AccountType, string> = {
  Asset: "text-blue-700",
  Liability: "text-red-700",
  Equity: "text-purple-700",
  Revenue: "text-green-700",
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

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found — please complete onboarding");
  return data.firm_id as string;
}

export default function TrialBalancePage() {
  const [asOfDate, setAsOfDate] = useState("2025-05-31");
  const [lines, setLines] = useState<TrialBalanceLine[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const sb = getSupabaseClient();
    getFirmId()
      .then(async (fid) => {
        // Fetch all accounts for this firm
        const { data: accs, error: accErr } = await sb
          .from("accounts")
          .select("id, account_code, account_name, account_type")
          .eq("firm_id", fid);
        if (accErr) throw new Error(accErr.message);

        // Fetch all journal entry lines for entries up to asOfDate
        const { data: entryLines, error: lineErr } = await sb
          .from("journal_entry_lines")
          .select("account_id, debit_paise, credit_paise, journal_entries!inner(firm_id, entry_date, status)")
          .eq("journal_entries.firm_id", fid)
          .eq("journal_entries.status", "posted")
          .lte("journal_entries.entry_date", asOfDate);
        if (lineErr) throw new Error(lineErr.message);

        // Aggregate debit/credit per account in integer paise — no floating point
        const map = new Map<string, { debit: number; credit: number }>();
        for (const line of (entryLines ?? [])) {
          const existing = map.get(line.account_id) ?? { debit: 0, credit: 0 };
          map.set(line.account_id, {
            debit: existing.debit + (line.debit_paise ?? 0),
            credit: existing.credit + (line.credit_paise ?? 0),
          });
        }

        const result: TrialBalanceLine[] = (accs ?? [])
          .map((a) => {
            const totals = map.get(a.id) ?? { debit: 0, credit: 0 };
            return {
              account_id: a.id,
              account_code: a.account_code,
              account_name: a.account_name,
              account_type: a.account_type as AccountType,
              total_debit_paise: totals.debit,
              total_credit_paise: totals.credit,
            };
          })
          .filter((l) => l.total_debit_paise > 0 || l.total_credit_paise > 0);

        setLines(result);
      })
      .catch((e) => setError(e.message ?? "Failed to load trial balance"))
      .finally(() => setLoading(false));
  }, [asOfDate]);

  // Compute totals in integer paise
  const totalDebit: number = lines.reduce((s, l) => s + l.total_debit_paise, 0);
  const totalCredit: number = lines.reduce((s, l) => s + l.total_credit_paise, 0);
  const difference: number = totalDebit - totalCredit;
  const isBalanced = difference === 0 && lines.length > 0;

  function exportToExcel() {
    const rows = lines.map((l) => ({
      Code: l.account_code,
      "Account Name": l.account_name,
      Type: l.account_type,
      "Debit (₹)": (l.total_debit_paise / 100).toFixed(2),
      "Credit (₹)": (l.total_credit_paise / 100).toFixed(2),
    }));
    rows.push({
      Code: "",
      "Account Name": "TOTAL",
      Type: "Asset" as AccountType,
      "Debit (₹)": (totalDebit / 100).toFixed(2),
      "Credit (₹)": (totalCredit / 100).toFixed(2),
    });
    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Trial Balance");
    XLSX.writeFile(wb, `trial_balance_${asOfDate}.xlsx`);
  }

  if (loading) return <LoadingSpinner />;

  if (error) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>
      </div>
    );
  }

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
      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <label className="text-xs text-gray-500">As of Date</label>
          <input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)}
            className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <Button variant="outline" size="sm" onClick={exportToExcel} disabled={lines.length === 0}>
          <Download size={14} className="mr-1" /> Export Excel
        </Button>
      </div>

      {lines.length === 0 ? (
        <div className="bg-gray-50 rounded-xl border border-gray-100 p-12 text-center">
          <p className="text-sm text-gray-500">No posted entries found for the selected date.</p>
        </div>
      ) : (
        <>
          {/* Balance status banner */}
          <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm font-medium ${isBalanced ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
            {isBalanced
              ? <><CheckCircle size={16} /> Trial Balance is Balanced</>
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
        </>
      )}
    </div>
  );
}
