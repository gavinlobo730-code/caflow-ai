"use client";

import { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { Card } from "@/components/ui/card";
import { formatPaise, formatDate } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";
import type { Account } from "@/lib/types";

interface LedgerLineRow {
  id: string;
  date: string;
  reference_no: string | null;
  narration: string;
  debit_paise: number;
  credit_paise: number;
  running_balance_paise: number;
}

function LoadingSpinner() {
  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4 animate-pulse">
      <div className="h-6 bg-gray-200 rounded w-48" />
      <div className="h-10 bg-gray-100 rounded" />
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

export default function LedgerPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState("");
  const [rawLines, setRawLines] = useState<LedgerLineRow[]>([]);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [loadingLedger, setLoadingLedger] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  useEffect(() => {
    const sb = getSupabaseClient();
    getFirmId()
      .then(async (fid) => {
        const { data, error: err } = await sb
          .from("accounts")
          .select("*")
          .eq("firm_id", fid)
          .order("account_name");
        if (err) throw new Error(err.message);
        const accs = (data ?? []) as Account[];
        setAccounts(accs);
        if (accs.length > 0) setAccountId(accs[0].id);
      })
      .catch((e) => setError(e.message ?? "Failed to load accounts"))
      .finally(() => setLoadingAccounts(false));
  }, []);

  useEffect(() => {
    if (!accountId) return;
    setLoadingLedger(true);
    const sb = getSupabaseClient();
    sb.from("journal_entry_lines")
      .select("id, debit_paise, credit_paise, narration, journal_entries(entry_date, reference_no)")
      .eq("account_id", accountId)
      .order("created_at", { ascending: true })
      .then(({ data, error: err }) => {
        if (err) { setError(err.message); setLoadingLedger(false); return; }
        // Build ledger rows with running balance (integer paise — no float)
        let running = 0;
        const rows: LedgerLineRow[] = (data ?? []).map((row) => {
          const jeRaw = row.journal_entries;
          const entry = Array.isArray(jeRaw) ? jeRaw[0] : jeRaw;
          const je = entry as { entry_date?: string; reference_no?: string } | null;
          const debit = row.debit_paise ?? 0;
          const credit = row.credit_paise ?? 0;
          running = running + debit - credit;
          return {
            id: row.id,
            date: je?.entry_date ?? "",
            reference_no: je?.reference_no ?? null,
            narration: row.narration ?? "",
            debit_paise: debit,
            credit_paise: credit,
            running_balance_paise: running,
          };
        });
        setRawLines(rows);
        setLoadingLedger(false);
      });
  }, [accountId]);

  const linesWithBalance = useMemo(() => {
    const filtered = rawLines.filter((l) => {
      if (startDate && l.date < startDate) return false;
      if (endDate && l.date > endDate) return false;
      return true;
    });
    // Recompute running balance in integer paise for filtered window
    let running = 0;
    return filtered.map((l) => {
      running = running + l.debit_paise - l.credit_paise;
      return { ...l, running_balance_paise: running };
    });
  }, [rawLines, startDate, endDate]);

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
