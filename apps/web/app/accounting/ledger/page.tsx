"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { Card } from "@/components/ui/card";
import { formatPaise, formatDate } from "@/lib/services/formatting";
import type { LedgerLine } from "@/lib/types";

const ACCOUNTS = [
  { id: "acc-002", name: "Bank — HDFC Current Account" },
  { id: "acc-001", name: "Cash in Hand" },
  { id: "acc-003", name: "Trade Receivables" },
  { id: "acc-009", name: "GST Output Tax Payable" },
  { id: "acc-010", name: "TDS Payable" },
  { id: "acc-015", name: "Professional Fees — GST Clients" },
  { id: "acc-016", name: "Professional Fees — ITR Clients" },
  { id: "acc-017", name: "Audit Fees" },
  { id: "acc-018", name: "Salary Expense" },
  { id: "acc-019", name: "Office Rent" },
  { id: "acc-020", name: "Software Subscriptions" },
  { id: "acc-021", name: "Bank Charges" },
];

// Mock ledger lines for Bank account (acc-002) — all in paise (integer)
const MOCK_LEDGER_DATA: Record<string, LedgerLine[]> = {
  "acc-002": [
    { date: "2025-04-01", reference_no: "OB/2025-26/001", narration: "Opening balance — capital introduced by partner", debit_paise: 50000000, credit_paise: 0, running_balance_paise: 50000000, entry_id: "je-001" },
    { date: "2025-04-05", reference_no: "INV/2025-26/001", narration: "Professional fees — GST filing for Sharma Enterprises", debit_paise: 1180000, credit_paise: 0, running_balance_paise: 51180000, entry_id: "je-002" },
    { date: "2025-04-05", reference_no: "EXP/2025-26/001", narration: "Office rent — MG Road, April 2025", debit_paise: 0, credit_paise: 3150000, running_balance_paise: 48030000, entry_id: "je-003" },
    { date: "2025-04-30", reference_no: "SAL/2025-26/001", narration: "Salary payment — April 2025", debit_paise: 0, credit_paise: 5000000, running_balance_paise: 43030000, entry_id: "je-004" },
    { date: "2025-05-01", reference_no: "EXP/2025-26/002", narration: "Software subscription — Winman, Tally", debit_paise: 0, credit_paise: 500000, running_balance_paise: 42530000, entry_id: "je-008" },
    { date: "2025-05-15", reference_no: "REC/2025-26/001", narration: "Receipt from Joshi Textiles — ITR fees", debit_paise: 2360000, credit_paise: 0, running_balance_paise: 44890000, entry_id: "je-006" },
    { date: "2025-05-20", reference_no: "GST/2025-26/001", narration: "GST payment — April 2025 GSTR-3B", debit_paise: 0, credit_paise: 540000, running_balance_paise: 44350000, entry_id: "je-007" },
    { date: "2025-05-31", reference_no: "BNK/2025-26/001", narration: "Bank charges — HDFC May 2025", debit_paise: 0, credit_paise: 50000, running_balance_paise: 44300000, entry_id: "je-010" },
  ],
  "acc-009": [
    { date: "2025-04-05", reference_no: "INV/2025-26/001", narration: "GST @18% on professional fees", debit_paise: 0, credit_paise: 180000, running_balance_paise: -180000, entry_id: "je-002" },
    { date: "2025-05-10", reference_no: "INV/2025-26/002", narration: "GST @18% on ITR fees", debit_paise: 0, credit_paise: 360000, running_balance_paise: -540000, entry_id: "je-005" },
    { date: "2025-05-20", reference_no: "GST/2025-26/001", narration: "GST payment — April 2025 GSTR-3B", debit_paise: 540000, credit_paise: 0, running_balance_paise: 0, entry_id: "je-007" },
    { date: "2025-05-25", reference_no: "INV/2025-26/003", narration: "GST @18% audit fees — draft", debit_paise: 0, credit_paise: 540000, running_balance_paise: -540000, entry_id: "je-009" },
  ],
};

export default function LedgerPage() {
  const [accountId, setAccountId] = useState("acc-002");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const filtered = useMemo(() => {
    const allLines: LedgerLine[] = MOCK_LEDGER_DATA[accountId] ?? [];
    return allLines.filter((l) => {
      if (startDate && l.date < startDate) return false;
      if (endDate && l.date > endDate) return false;
      return true;
    });
  }, [accountId, startDate, endDate]);

  // Recompute running balance in integer paise for filtered lines
  const linesWithBalance = useMemo(() => {
    let running = 0;
    return filtered.map((l) => {
      running += l.debit_paise - l.credit_paise;
      return { ...l, running_balance_paise: running };
    });
  }, [filtered]);

  const selectedAccount = ACCOUNTS.find((a) => a.id === accountId);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft size={18} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-gray-900">General Ledger</h1>
          <p className="text-sm text-gray-500 mt-0.5">{selectedAccount?.name}</p>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <label className="text-xs text-gray-500">Account</label>
          <select value={accountId} onChange={(e) => setAccountId(e.target.value)}
            className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[240px]">
            {ACCOUNTS.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
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
        <button className="text-xs border border-gray-200 text-gray-600 px-3 py-1.5 rounded-md hover:bg-gray-50 mb-0.5">
          Export
        </button>
      </div>

      {/* Ledger table */}
      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-xs text-gray-400">
                <th className="px-5 py-3 text-left font-semibold">Date</th>
                <th className="px-3 py-3 text-left font-semibold">Reference</th>
                <th className="px-3 py-3 text-left font-semibold">Narration</th>
                <th className="px-3 py-3 text-right font-semibold">Debit</th>
                <th className="px-3 py-3 text-right font-semibold">Credit</th>
                <th className="px-5 py-3 text-right font-semibold">Balance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {linesWithBalance.length === 0 && (
                <tr><td colSpan={6} className="text-center text-gray-400 py-8 text-sm">No transactions found</td></tr>
              )}
              {linesWithBalance.map((line, i) => (
                <tr key={i} className="hover:bg-gray-50">
                  <td className="px-5 py-3 text-xs text-gray-600 whitespace-nowrap">{formatDate(line.date)}</td>
                  <td className="px-3 py-3 text-xs font-mono text-gray-500">{line.reference_no ?? "—"}</td>
                  <td className="px-3 py-3 text-sm text-gray-900 max-w-xs truncate">{line.narration}</td>
                  <td className="px-3 py-3 text-sm tabular-nums text-right text-green-700">
                    {line.debit_paise > 0 ? formatPaise(line.debit_paise) : "—"}
                  </td>
                  <td className="px-3 py-3 text-sm tabular-nums text-right text-red-600">
                    {line.credit_paise > 0 ? formatPaise(line.credit_paise) : "—"}
                  </td>
                  <td className={`px-5 py-3 text-sm tabular-nums font-semibold text-right ${line.running_balance_paise >= 0 ? "text-gray-900" : "text-red-600"}`}>
                    {formatPaise(Math.abs(line.running_balance_paise))}{line.running_balance_paise < 0 ? " Cr" : " Dr"}
                  </td>
                </tr>
              ))}
            </tbody>
            {linesWithBalance.length > 0 && (
              <tfoot>
                <tr className="border-t-2 border-gray-200 bg-gray-50 font-semibold text-sm">
                  <td colSpan={3} className="px-5 py-3 text-gray-500">Closing Balance</td>
                  <td className="px-3 py-3 text-right tabular-nums text-green-700">
                    {formatPaise(linesWithBalance.reduce((s, l) => s + l.debit_paise, 0))}
                  </td>
                  <td className="px-3 py-3 text-right tabular-nums text-red-600">
                    {formatPaise(linesWithBalance.reduce((s, l) => s + l.credit_paise, 0))}
                  </td>
                  <td className="px-5 py-3 text-right tabular-nums text-gray-900">
                    {linesWithBalance.length > 0 && formatPaise(Math.abs(linesWithBalance[linesWithBalance.length - 1].running_balance_paise))}
                  </td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </Card>
    </div>
  );
}
