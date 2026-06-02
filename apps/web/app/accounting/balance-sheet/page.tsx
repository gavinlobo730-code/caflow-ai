"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, CheckCircle, AlertTriangle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatPaise } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";

const TODAY = new Date().toISOString().split("T")[0];

interface BSLine {
  account_name: string;
  balance_paise: number;
}

interface BSSection {
  label: string;
  lines: BSLine[];
  total_paise: number;
}

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

function BSSectionCard({ section, color }: { section: BSSection; color: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className={`text-sm ${color}`}>{section.label}</CardTitle>
      </CardHeader>
      <CardContent className="pb-4">
        <div className="divide-y divide-gray-50">
          {section.lines.map((l) => (
            <div key={l.account_name} className="flex items-center justify-between py-2">
              <span className="text-sm text-gray-700">{l.account_name}</span>
              <span className={`text-sm tabular-nums font-medium ${l.balance_paise < 0 ? "text-red-600" : "text-gray-900"}`}>
                {l.balance_paise < 0 ? `(${formatPaise(Math.abs(l.balance_paise))})` : formatPaise(l.balance_paise)}
              </span>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-between py-2.5 font-semibold border-t border-gray-200 mt-1">
          <span className="text-sm text-gray-900">Total {section.label}</span>
          <span className="text-sm tabular-nums text-gray-900">{formatPaise(section.total_paise)}</span>
        </div>
      </CardContent>
    </Card>
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

export default function BalanceSheetPage() {
  const [asOfDate, setAsOfDate] = useState(TODAY);
  const [assets, setAssets] = useState<BSSection[]>([]);
  const [liabilities, setLiabilities] = useState<BSSection[]>([]);
  const [equity, setEquity] = useState<BSSection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const sb = getSupabaseClient();
    getFirmId()
      .then(async (fid) => {
        // Fetch balance sheet accounts (Asset, Liability, Equity)
        const { data: accs, error: accErr } = await sb
          .from("accounts")
          .select("id, account_name, account_type")
          .eq("firm_id", fid)
          .in("account_type", ["Asset", "Liability", "Equity"]);
        if (accErr) throw new Error(accErr.message);

        // Fetch journal entry lines for posted entries up to asOfDate
        const { data: entryLines, error: lineErr } = await sb
          .from("journal_entry_lines")
          .select("account_id, debit_paise, credit_paise, journal_entries!inner(firm_id, entry_date, status)")
          .eq("journal_entries.firm_id", fid)
          .eq("journal_entries.status", "posted")
          .lte("journal_entries.entry_date", asOfDate);
        if (lineErr) throw new Error(lineErr.message);

        // Aggregate net balance per account in integer paise — no floating point
        const map = new Map<string, number>();
        for (const line of (entryLines ?? [])) {
          const prev = map.get(line.account_id) ?? 0;
          // Assets: debit increases balance; Liabilities/Equity: credit increases balance
          map.set(line.account_id, prev + (line.debit_paise ?? 0) - (line.credit_paise ?? 0));
        }

        const assetLines: BSLine[] = [];
        const liabilityLines: BSLine[] = [];
        const equityLines: BSLine[] = [];

        for (const acc of (accs ?? [])) {
          let bal = map.get(acc.id) ?? 0;
          // For Liability/Equity, negate so positive = credit balance
          if (acc.account_type === "Liability" || acc.account_type === "Equity") {
            bal = -bal;
          }
          if (bal === 0) continue;
          const line: BSLine = { account_name: acc.account_name, balance_paise: bal };
          if (acc.account_type === "Asset") assetLines.push(line);
          else if (acc.account_type === "Liability") liabilityLines.push(line);
          else equityLines.push(line);
        }

        const assetTotal: number = assetLines.reduce((s, l) => s + l.balance_paise, 0);
        const liabTotal: number = liabilityLines.reduce((s, l) => s + l.balance_paise, 0);
        const eqTotal: number = equityLines.reduce((s, l) => s + l.balance_paise, 0);

        setAssets(assetLines.length > 0 ? [{ label: "Assets", lines: assetLines, total_paise: assetTotal }] : []);
        setLiabilities(liabilityLines.length > 0 ? [{ label: "Liabilities", lines: liabilityLines, total_paise: liabTotal }] : []);
        setEquity(equityLines.length > 0 ? [{ label: "Equity", lines: equityLines, total_paise: eqTotal }] : []);
      })
      .catch((e) => setError(e.message ?? "Failed to load balance sheet"))
      .finally(() => setLoading(false));
  }, [asOfDate]);

  // All arithmetic in integer paise
  const totalAssetsPaise: number = assets.reduce((s, sec) => s + sec.total_paise, 0);
  const totalLiabEquityPaise: number =
    liabilities.reduce((s, sec) => s + sec.total_paise, 0) +
    equity.reduce((s, sec) => s + sec.total_paise, 0);
  const isBalanced = totalAssetsPaise === totalLiabEquityPaise && (totalAssetsPaise > 0 || totalLiabEquityPaise > 0);
  const hasData = assets.length > 0 || liabilities.length > 0 || equity.length > 0;

  if (loading) return <LoadingSpinner />;

  if (error) {
    return (
      <div className="p-6 max-w-4xl mx-auto">
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>
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

      {!hasData ? (
        <div className="bg-gray-50 rounded-xl border border-gray-100 p-12 text-center">
          <p className="text-sm text-gray-500">No posted transactions found for this date.</p>
        </div>
      ) : (
        <>
          {/* Balance check */}
          <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm font-medium ${isBalanced ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-700"}`}>
            {isBalanced
              ? <><CheckCircle size={16} /> Balance Sheet balances — Assets = Liabilities + Equity</>
              : <><AlertTriangle size={16} /> Balance Sheet may not balance — add Retained Earnings or Opening entries</>
            }
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Left: Assets */}
            <div className="space-y-4">
              {assets.map((section) => (
                <BSSectionCard key={section.label} section={section} color="text-blue-700" />
              ))}
              {totalAssetsPaise > 0 && (
                <div className="bg-blue-50 rounded-lg px-5 py-3 flex items-center justify-between">
                  <span className="text-sm font-bold text-blue-900">Total Assets</span>
                  <span className="text-sm font-bold tabular-nums text-blue-700">{formatPaise(totalAssetsPaise)}</span>
                </div>
              )}
            </div>

            {/* Right: Liabilities + Equity */}
            <div className="space-y-4">
              {liabilities.map((section) => (
                <BSSectionCard key={section.label} section={section} color="text-red-700" />
              ))}
              {equity.map((section) => (
                <BSSectionCard key={section.label} section={section} color="text-purple-700" />
              ))}
              {totalLiabEquityPaise > 0 && (
                <div className="bg-purple-50 rounded-lg px-5 py-3 flex items-center justify-between">
                  <span className="text-sm font-bold text-purple-900">Total Liabilities + Equity</span>
                  <span className="text-sm font-bold tabular-nums text-purple-700">{formatPaise(totalLiabEquityPaise)}</span>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
