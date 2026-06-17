"use client";

import { useState, useEffect, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ChevronLeft, CheckCircle, AlertTriangle, Download } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { formatPaise } from "@/lib/services/formatting";
import { api } from "@/lib/api";
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

type Basis = "accrual" | "cash";

// Backend response envelope. ALL aggregation happens server-side (CLAUDE.md):
// the page only passes the basis/date and renders what the API returns.
type TBResponse = { success: boolean; data: { lines: TrialBalanceLine[] } | null; error: string | null };

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
      <div className="h-6 bg-gray-100 rounded w-48" />
      <div className="h-10 bg-[#F1F5F9] rounded w-48" />
      <div className="h-64 bg-[#F1F5F9] rounded-xl" />
    </div>
  );
}

export default function TrialBalancePage() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const [asOfDate, setAsOfDate] = useState("2025-05-31");
  // basis persists in URL — refresh-safe
  const [basis, setBasis] = useState<Basis>((searchParams.get("basis") as Basis) ?? "accrual");
  const [lines, setLines] = useState<TrialBalanceLine[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const updateBasis = useCallback((b: Basis) => {
    setBasis(b);
    const params = new URLSearchParams(searchParams.toString());
    params.set("basis", b);
    router.replace(`?${params.toString()}`, { scroll: false });
  }, [router, searchParams]);

  useEffect(() => {
    setLoading(true);
    setError(null);

    const load = async (): Promise<TrialBalanceLine[]> => {
      // Both bases are computed server-side from the same posted ledger
      // (IT Act §145). The frontend only passes parameters.
      const params: Record<string, string> = { basis };
      if (asOfDate) params.as_of_date = asOfDate;
      const res = (await api.accounting.trialBalance(params)) as TBResponse;
      if (!res.success) throw new Error(res.error ?? "Failed to load trial balance");
      return res.data?.lines ?? [];
    };

    load()
      .then(setLines)
      .catch((e) => setError(e.message ?? "Failed to load trial balance"))
      .finally(() => setLoading(false));
  }, [asOfDate, basis]);

  const totalDebit: number = lines.reduce((s, l) => s + l.total_debit_paise, 0);
  const totalCredit: number = lines.reduce((s, l) => s + l.total_credit_paise, 0);
  const difference: number = totalDebit - totalCredit;
  const isBalanced = difference === 0 && lines.length > 0;

  function exportToExcel() {
    const rows = lines.map((l) => ({
      Code: l.account_code,
      "Account Name": l.account_name,
      Type: l.account_type,
      Basis: basis === "cash" ? "Cash" : "Accrual",
      "Debit (₹)": (l.total_debit_paise / 100).toFixed(2),
      "Credit (₹)": (l.total_credit_paise / 100).toFixed(2),
    }));
    rows.push({
      Code: "",
      "Account Name": "TOTAL",
      Type: "Asset" as AccountType,
      Basis: "",
      "Debit (₹)": (totalDebit / 100).toFixed(2),
      "Credit (₹)": (totalCredit / 100).toFixed(2),
    });
    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Trial Balance");
    XLSX.writeFile(wb, `trial_balance_${basis}_${asOfDate}.xlsx`);
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
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft size={18} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Trial Balance</h1>
          <p className="text-sm text-[#64748B] mt-0.5">As of {asOfDate}</p>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <label className="text-xs text-[#64748B]">As of Date</label>
          <input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)}
            className="block mt-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>

        {/* Accrual | Cash toggle — IT Act Section 145 */}
        <div>
          <label className="text-xs text-[#64748B]">Reporting Basis</label>
          <div className="flex mt-1 rounded-md border border-[#E2E8F0] overflow-hidden text-sm">
            <button
              onClick={() => updateBasis("accrual")}
              className={`px-4 py-1.5 font-medium transition-colors ${basis === "accrual" ? "bg-[#1E293B] text-white" : "bg-white text-[#64748B] hover:bg-[#F8FAFC]"}`}
            >
              Accrual
            </button>
            <button
              onClick={() => updateBasis("cash")}
              className={`px-4 py-1.5 font-medium border-l border-[#E2E8F0] transition-colors ${basis === "cash" ? "bg-[#1E293B] text-white" : "bg-white text-[#64748B] hover:bg-[#F8FAFC]"}`}
            >
              Cash
            </button>
          </div>
        </div>

        <Button variant="outline" size="sm" onClick={exportToExcel} disabled={lines.length === 0}>
          <Download size={14} className="mr-1" /> Export Excel
        </Button>
      </div>

      {/* Cash basis disclaimer */}
      {basis === "cash" && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-xs text-amber-800">
          Cash basis is for management reporting only (IT Act §145). GST returns remain invoice-based per CGST Act and are not affected by this view.
        </div>
      )}

      {lines.length === 0 ? (
        <div className="bg-[#F8FAFC] rounded-xl border border-[#F1F5F9] p-12 text-center">
          <p className="text-sm text-[#64748B]">No posted entries found for the selected date.</p>
        </div>
      ) : (
        <>
          <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm font-medium ${isBalanced ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
            {isBalanced
              ? <><CheckCircle size={16} /> Trial Balance is Balanced</>
              : <><AlertTriangle size={16} /> Imbalanced — Difference: {formatPaise(Math.abs(difference))}</>
            }
          </div>

          <Card>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                    <th className="px-5 py-3 text-left font-semibold">Code</th>
                    <th className="px-3 py-3 text-left font-semibold">Account Name</th>
                    <th className="px-3 py-3 text-left font-semibold">Type</th>
                    <th className="px-5 py-3 text-right font-semibold">Debit</th>
                    <th className="px-5 py-3 text-right font-semibold">Credit</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F8FAFC]">
                  {lines.map((line) => (
                    <tr key={line.account_id} className="hover:bg-[#F8FAFC]">
                      <td className="px-5 py-3 text-xs font-mono text-[#94A3B8]">{line.account_code}</td>
                      <td className="px-3 py-3 text-sm text-[#0F172A]">{line.account_name}</td>
                      <td className={`px-3 py-3 text-xs font-medium ${TYPE_COLORS[line.account_type]}`}>{line.account_type}</td>
                      <td className="px-5 py-3 text-sm tabular-nums text-right text-[#334155]">
                        {line.total_debit_paise > 0 ? formatPaise(line.total_debit_paise) : "—"}
                      </td>
                      <td className="px-5 py-3 text-sm tabular-nums text-right text-[#334155]">
                        {line.total_credit_paise > 0 ? formatPaise(line.total_credit_paise) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 border-gray-300 bg-[#F8FAFC] font-bold text-sm">
                    <td colSpan={3} className="px-5 py-3 text-[#334155]">Total</td>
                    <td className="px-5 py-3 text-right tabular-nums text-[#0F172A]">{formatPaise(totalDebit)}</td>
                    <td className="px-5 py-3 text-right tabular-nums text-[#0F172A]">{formatPaise(totalCredit)}</td>
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
