"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronLeft, CheckCircle, AlertTriangle } from "lucide-react";
import { Card } from "@/components/ui/card";
import { formatPaise } from "@/lib/services/formatting";
import type { TrialBalanceLine, AccountType } from "@/lib/types";

// Mock trial balance — all values in paise (integer), never float
const MOCK_TB_LINES: TrialBalanceLine[] = [
  { account_id: "acc-001", account_code: "1001", account_name: "Cash in Hand", account_type: "Asset", total_debit_paise: 0, total_credit_paise: 0, net_paise: 0 },
  { account_id: "acc-002", account_code: "1002", account_name: "Bank — HDFC Current Account", account_type: "Asset", total_debit_paise: 53540000, total_credit_paise: 9240000, net_paise: 44300000 },
  { account_id: "acc-003", account_code: "1003", account_name: "Trade Receivables", account_type: "Asset", total_debit_paise: 5900000, total_credit_paise: 2360000, net_paise: 3540000 },
  { account_id: "acc-009", account_code: "2002", account_name: "GST Output Tax Payable", account_type: "Liability", total_debit_paise: 540000, total_credit_paise: 1620000, net_paise: -1080000 },
  { account_id: "acc-010", account_code: "2003", account_name: "TDS Payable", account_type: "Liability", total_debit_paise: 0, total_credit_paise: 350000, net_paise: -350000 },
  { account_id: "acc-013", account_code: "3001", account_name: "Capital Account", account_type: "Equity", total_debit_paise: 0, total_credit_paise: 50000000, net_paise: -50000000 },
  { account_id: "acc-015", account_code: "4001", account_name: "Professional Fees — GST Clients", account_type: "Income", total_debit_paise: 0, total_credit_paise: 1000000, net_paise: -1000000 },
  { account_id: "acc-016", account_code: "4002", account_name: "Professional Fees — ITR Clients", account_type: "Income", total_debit_paise: 0, total_credit_paise: 2000000, net_paise: -2000000 },
  { account_id: "acc-017", account_code: "4003", account_name: "Audit Fees", account_type: "Income", total_debit_paise: 0, total_credit_paise: 3000000, net_paise: -3000000 },
  { account_id: "acc-018", account_code: "5001", account_name: "Salary Expense", account_type: "Expense", total_debit_paise: 5000000, total_credit_paise: 0, net_paise: 5000000 },
  { account_id: "acc-019", account_code: "5002", account_name: "Office Rent", account_type: "Expense", total_debit_paise: 3500000, total_credit_paise: 0, net_paise: 3500000 },
  { account_id: "acc-020", account_code: "5003", account_name: "Software Subscriptions", account_type: "Expense", total_debit_paise: 500000, total_credit_paise: 0, net_paise: 500000 },
  { account_id: "acc-021", account_code: "5004", account_name: "Bank Charges", account_type: "Expense", total_debit_paise: 50000, total_credit_paise: 0, net_paise: 50000 },
];

const TYPE_COLORS: Record<AccountType, string> = {
  Asset: "text-blue-700",
  Liability: "text-red-700",
  Equity: "text-purple-700",
  Income: "text-green-700",
  Expense: "text-orange-700",
};

export default function TrialBalancePage() {
  const [asOfDate, setAsOfDate] = useState("2025-05-31");

  const lines = MOCK_TB_LINES.filter((l) => l.total_debit_paise > 0 || l.total_credit_paise > 0);

  // All arithmetic in integer paise
  const totalDebit: number = lines.reduce((s, l) => s + l.total_debit_paise, 0);
  const totalCredit: number = lines.reduce((s, l) => s + l.total_credit_paise, 0);
  const isBalanced = totalDebit === totalCredit;
  const difference: number = totalDebit - totalCredit;

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
