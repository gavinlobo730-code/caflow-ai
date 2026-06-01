"use client";

import { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { Card } from "@/components/ui/card";
import { formatPaise, formatDate } from "@/lib/services/formatting";
import type { Account, LedgerLine, ApiResponse } from "@/lib/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function LoadingSpinner() {
  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4 animate-pulse">
      <div className="h-6 bg-gray-200 rounded w-48" />
      <div className="h-10 bg-gray-100 rounded" />
      <div className="h-64 bg-gray-100 rounded-xl" />
    </div>
  );
}

export default function LedgerPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState("");
  const [ledgerLines, setLedgerLines] = useState<LedgerLine[]>([]);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [loadingLedger, setLoadingLedger] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  useEffect(() => {
    fetch(`${BASE_URL}/api/accounting/accounts`)
      .then((r) => r.json())
      .then((res: ApiResponse<Account[]>) => {
        if (res.success) {
          setAccounts(res.data);
          if (res.data.length > 0) setAccountId(res.data[0].id);
        } else {
          setError(res.error ?? "Failed to load accounts");
        }
      })
      .catch(() => setError("Failed to load accounts"))
      .finally(() => setLoadingAccounts(false));
  }, []);

  useEffect(() => {
    if (!accountId) return;
    setLoadingLedger(true);
    fetch(`${BASE_URL}/api/accounting/ledger?account_id=${accountId}`)
      .then((r) => r.json())
      .then((res: ApiResponse<LedgerLine[]>) => {
        if (res.success) setLedgerLines(res.data);
        else setError(res.error ?? "Failed to load ledger");
      })
      .catch(() => setError("Failed to load ledger"))
      .finally(() => setLoadingLedger(false));
  }, [accountId]);

  const filtered = useMemo(() => {
    return ledgerLines.filter((l) => {
      if (startDate && l.date < startDate) return false;
      if (endDate && l.date > endDate) return false;
      return true;
    });
  }, [ledgerLines, startDate, endDate]);

  // Recompute running balance in integer paise for filtered lines
  const linesWithBalance = useMemo(() => {
    let running = 0;
    return filtered.map((l) => {
      running += l.debit_paise - l.credit_paise;
      return { ...l, running_balance_paise: running };
    });
  }, [filtered]);

  const selectedAccount = accounts.find((a) => a.id === accountId);

  if (loadingAccounts) return <LoadingSpinner />;

  if (error) {
    return (
      <div className="p-6 max-w-6xl mx-auto">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft size={18} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-gray-900">General Ledger</h1>
          <p className="text-sm text-gray-500 mt-0.5">{selectedAccount?.account_name}</p>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <label className="text-xs text-gray-500">Account</label>
          <select value={accountId} onChange={(e) => setAccountId(e.target.value)}
            className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[240px]">
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
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
        {loadingLedger ? (
          <div className="p-8 text-center text-gray-400 text-sm animate-pulse">Loading ledger…</div>
        ) : (
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
                      {formatPaise(Math.abs(linesWithBalance[linesWithBalance.length - 1].running_balance_paise))}
                    </td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
