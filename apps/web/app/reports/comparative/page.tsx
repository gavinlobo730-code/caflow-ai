"use client";

/**
 * Comparative Financial Reports — Year-over-year and quarter-over-quarter
 * Fetches from journal_lines joined with chart_of_accounts and journal_entries
 * All amounts in integer paise — no floating point arithmetic
 */

import { useState, useCallback } from "react";
import { ArrowLeft, TrendingUp, TrendingDown, Download } from "lucide-react";
import Link from "next/link";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";
import { useEffect } from "react";

type Tab = "pl" | "bs" | "quarterly";

interface AccountLine {
  account_name: string;
  account_type: string;
  current: number;
  previous: number;
  changePct: number | null;
}

interface PLData {
  revenue: AccountLine[];
  expenses: AccountLine[];
  totalRevenueCurrent: number;
  totalRevenuePrevious: number;
  totalExpensesCurrent: number;
  totalExpensesPrevious: number;
  netProfitCurrent: number;
  netProfitPrevious: number;
}

interface BSData {
  assets: AccountLine[];
  liabilities: AccountLine[];
  equity: AccountLine[];
  totalAssetsCurrent: number;
  totalAssetsPrevious: number;
  totalLiabilitiesCurrent: number;
  totalLiabilitiesPrevious: number;
}

interface QuarterData {
  quarter: string;
  revenue: number;
  expenses: number;
}

function fmtPaise(p: number): string {
  if (p === 0) return "₹0";
  const abs = Math.abs(p);
  const rupees = Math.floor(abs / 100);
  const paise = abs % 100;
  const s = rupees.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (p < 0 ? "-₹" : "₹") + s + "." + String(paise).padStart(2, "0");
}

function changePct(current: number, previous: number): number | null {
  if (previous === 0) return null;
  return Math.round(((current - previous) * 10000) / Math.abs(previous)) / 100;
}

function ChangeChip({ pct, inverse }: { pct: number | null; inverse?: boolean }) {
  if (pct === null) return <span className="text-xs text-gray-400">—</span>;
  // For expenses: increase is bad (inverse), for revenue: increase is good
  const isGood = inverse ? pct < 0 : pct > 0;
  return (
    <span className={`text-xs font-medium flex items-center gap-0.5 ${isGood ? "text-green-600" : pct === 0 ? "text-gray-400" : "text-red-600"}`}>
      {isGood ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
      {pct > 0 ? "+" : ""}{pct}%
    </span>
  );
}

function CompareTable({ rows, label, inverse }: { rows: AccountLine[]; label: string; inverse?: boolean }) {
  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-2 bg-gray-50">{label}</h3>
      {rows.map((r, i) => (
        <div key={i} className="flex items-center px-4 py-2.5 border-b border-gray-100 hover:bg-gray-50">
          <span className="flex-1 text-sm text-gray-800">{r.account_name}</span>
          <span className="w-32 text-right font-mono text-sm text-gray-700">{fmtPaise(r.current)}</span>
          <span className="w-32 text-right font-mono text-sm text-gray-500">{fmtPaise(r.previous)}</span>
          <span className="w-20 text-right"><ChangeChip pct={r.changePct} inverse={inverse} /></span>
        </div>
      ))}
    </div>
  );
}

const FY_OPTIONS = [
  { label: "FY 2025-26", start: "2025-04-01", end: "2026-03-31" },
  { label: "FY 2024-25", start: "2024-04-01", end: "2025-03-31" },
  { label: "FY 2023-24", start: "2023-04-01", end: "2024-03-31" },
];

export default function ComparativeReportsPage() {
  const [tab, setTab] = useState<Tab>("pl");
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [currentFyIdx, setCurrentFyIdx] = useState(0);
  const [plData, setPLData] = useState<PLData | null>(null);
  const [bsData, setBSData] = useState<BSData | null>(null);
  const [quarterlyData, setQuarterlyData] = useState<QuarterData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getClients().then(c => { setClients(c); if (c.length > 0) setClientId(c[0].id); }).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setError(null);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const currentFy = FY_OPTIONS[currentFyIdx];
      const prevFyIdx = Math.min(currentFyIdx + 1, FY_OPTIONS.length - 1);
      const prevFy = FY_OPTIONS[prevFyIdx];

      // Fetch journal lines with account info for both periods
      const [currRes, prevRes] = await Promise.all([
        sb.from("journal_lines")
          .select("debit_paise, credit_paise, chart_of_accounts(account_name, account_type), journal_entries!inner(entry_date, client_id, firm_id)")
          .eq("journal_entries.firm_id", firmId)
          .eq("journal_entries.client_id", clientId)
          .gte("journal_entries.entry_date", currentFy.start)
          .lte("journal_entries.entry_date", currentFy.end),
        sb.from("journal_lines")
          .select("debit_paise, credit_paise, chart_of_accounts(account_name, account_type), journal_entries!inner(entry_date, client_id, firm_id)")
          .eq("journal_entries.firm_id", firmId)
          .eq("journal_entries.client_id", clientId)
          .gte("journal_entries.entry_date", prevFy.start)
          .lte("journal_entries.entry_date", prevFy.end),
      ]);

      type JournalLineRow = {
        debit_paise: number;
        credit_paise: number;
        chart_of_accounts: { account_name: string; account_type: string } | null;
      };

      function aggregate(rows: JournalLineRow[]): Map<string, { name: string; type: string; net: number }> {
        const m = new Map<string, { name: string; type: string; net: number }>();
        for (const r of rows) {
          const acc = r.chart_of_accounts;
          if (!acc) continue;
          const key = acc.account_name;
          const existing = m.get(key) ?? { name: acc.account_name, type: acc.account_type, net: 0 };
          // Net = credit - debit for income/equity, debit - credit for assets/expenses
          existing.net += (r.credit_paise ?? 0) - (r.debit_paise ?? 0);
          m.set(key, existing);
        }
        return m;
      }

      const currMap = aggregate((currRes.data ?? []) as JournalLineRow[]);
      const prevMap = aggregate((prevRes.data ?? []) as JournalLineRow[]);

      const allAccounts = new Set([...currMap.keys(), ...prevMap.keys()]);

      const revenue: AccountLine[] = [];
      const expenses: AccountLine[] = [];
      const assets: AccountLine[] = [];
      const liabilities: AccountLine[] = [];
      const equity: AccountLine[] = [];

      for (const name of allAccounts) {
        const curr = currMap.get(name);
        const prev = prevMap.get(name);
        const type = curr?.type ?? prev?.type ?? "";
        const currVal = curr?.net ?? 0;
        const prevVal = prev?.net ?? 0;
        const line: AccountLine = {
          account_name: name,
          account_type: type,
          current: Math.abs(currVal),
          previous: Math.abs(prevVal),
          changePct: changePct(Math.abs(currVal), Math.abs(prevVal)),
        };
        if (type === "Income" || type === "Revenue") revenue.push(line);
        else if (type === "Expense") expenses.push(line);
        else if (type === "Asset") assets.push(line);
        else if (type === "Liability") liabilities.push(line);
        else if (type === "Equity") equity.push(line);
      }

      const totalRevCurr = revenue.reduce((s, r) => s + r.current, 0);
      const totalRevPrev = revenue.reduce((s, r) => s + r.previous, 0);
      const totalExpCurr = expenses.reduce((s, r) => s + r.current, 0);
      const totalExpPrev = expenses.reduce((s, r) => s + r.previous, 0);

      setPLData({
        revenue, expenses,
        totalRevenueCurrent: totalRevCurr,
        totalRevenuePrevious: totalRevPrev,
        totalExpensesCurrent: totalExpCurr,
        totalExpensesPrevious: totalExpPrev,
        netProfitCurrent: totalRevCurr - totalExpCurr,
        netProfitPrevious: totalRevPrev - totalExpPrev,
      });

      setBSData({
        assets, liabilities, equity,
        totalAssetsCurrent: assets.reduce((s, r) => s + r.current, 0),
        totalAssetsPrevious: assets.reduce((s, r) => s + r.previous, 0),
        totalLiabilitiesCurrent: liabilities.reduce((s, r) => s + r.current, 0),
        totalLiabilitiesPrevious: liabilities.reduce((s, r) => s + r.previous, 0),
      });

      // Quarterly data for current FY
      const fyYear = parseInt(currentFy.start.split("-")[0]);
      const quarters: QuarterData[] = [
        { quarter: `Q1 (Apr-Jun ${fyYear})`, revenue: 0, expenses: 0 },
        { quarter: `Q2 (Jul-Sep ${fyYear})`, revenue: 0, expenses: 0 },
        { quarter: `Q3 (Oct-Dec ${fyYear})`, revenue: 0, expenses: 0 },
        { quarter: `Q4 (Jan-Mar ${fyYear + 1})`, revenue: 0, expenses: 0 },
      ];

      for (const r of (currRes.data ?? []) as (JournalLineRow & { journal_entries: { entry_date: string } | null })[]) {
        const entryDate = r.journal_entries?.entry_date;
        if (!entryDate) continue;
        const m = parseInt(entryDate.split("-")[1]);
        // FY months: Apr=4,May=5,...Mar=3
        // Q1: Apr-Jun (4-6), Q2: Jul-Sep (7-9), Q3: Oct-Dec (10-12), Q4: Jan-Mar (1-3)
        const qIdx = m >= 4 && m <= 6 ? 0 : m >= 7 && m <= 9 ? 1 : m >= 10 ? 2 : 3;
        const acc = r.chart_of_accounts;
        if (!acc) continue;
        const net = (r.credit_paise ?? 0) - (r.debit_paise ?? 0);
        if (acc.account_type === "Income" || acc.account_type === "Revenue") {
          quarters[qIdx].revenue += Math.abs(net);
        } else if (acc.account_type === "Expense") {
          quarters[qIdx].expenses += Math.abs(net);
        }
      }
      setQuarterlyData(quarters);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [clientId, currentFyIdx]);

  useEffect(() => { if (clientId) load(); }, [clientId, load]);

  const currentFy = FY_OPTIONS[currentFyIdx];
  const prevFy = FY_OPTIONS[Math.min(currentFyIdx + 1, FY_OPTIONS.length - 1)];

  const TABS = [
    { id: "pl" as Tab, label: "P&L Comparison" },
    { id: "bs" as Tab, label: "Balance Sheet" },
    { id: "quarterly" as Tab, label: "Quarterly Trend" },
  ];

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/reports" className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-500">
            <ArrowLeft size={15} />
          </Link>
          <div>
            <h1 className="text-lg md:text-xl font-semibold text-gray-900">Comparative Reports</h1>
            <p className="text-sm text-gray-500 mt-0.5">Year-over-year financial comparison</p>
          </div>
        </div>
        <button
          onClick={() => { window.dispatchEvent(new CustomEvent("toast", { detail: "Export to Excel coming soon" })); }}
          className="flex items-center gap-2 px-4 py-2 border border-gray-200 text-gray-700 text-sm rounded-lg hover:bg-gray-50">
          <Download size={15} /> Export to Excel
        </button>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap gap-3">
        <select value={clientId} onChange={e => setClientId(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
          {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
        </select>
        <select value={currentFyIdx} onChange={e => setCurrentFyIdx(parseInt(e.target.value))}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
          {FY_OPTIONS.slice(0, -1).map((fy, i) => (
            <option key={i} value={i}>{fy.label} vs {FY_OPTIONS[i + 1].label}</option>
          ))}
        </select>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
              tab === t.id ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {loading && <div className="text-center py-12 text-gray-400">Loading report data…</div>}

      {/* P&L Comparison */}
      {!loading && tab === "pl" && plData && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {/* Column headers */}
          <div className="flex items-center px-4 py-3 bg-gray-50 border-b border-gray-200 text-xs font-semibold text-gray-600">
            <span className="flex-1">Account</span>
            <span className="w-32 text-right">{currentFy.label}</span>
            <span className="w-32 text-right">{prevFy.label}</span>
            <span className="w-20 text-right">Change</span>
          </div>

          <CompareTable rows={plData.revenue} label="Revenue" />
          {/* Revenue total */}
          <div className="flex items-center px-4 py-3 bg-green-50 border-b border-gray-200">
            <span className="flex-1 text-sm font-semibold text-green-800">Total Revenue</span>
            <span className="w-32 text-right font-mono text-sm font-semibold text-green-800">{fmtPaise(plData.totalRevenueCurrent)}</span>
            <span className="w-32 text-right font-mono text-sm text-green-600">{fmtPaise(plData.totalRevenuePrevious)}</span>
            <span className="w-20 text-right"><ChangeChip pct={changePct(plData.totalRevenueCurrent, plData.totalRevenuePrevious)} /></span>
          </div>

          <CompareTable rows={plData.expenses} label="Expenses" inverse />
          {/* Expenses total */}
          <div className="flex items-center px-4 py-3 bg-red-50 border-b border-gray-200">
            <span className="flex-1 text-sm font-semibold text-red-800">Total Expenses</span>
            <span className="w-32 text-right font-mono text-sm font-semibold text-red-800">{fmtPaise(plData.totalExpensesCurrent)}</span>
            <span className="w-32 text-right font-mono text-sm text-red-600">{fmtPaise(plData.totalExpensesPrevious)}</span>
            <span className="w-20 text-right"><ChangeChip pct={changePct(plData.totalExpensesCurrent, plData.totalExpensesPrevious)} inverse /></span>
          </div>

          {/* Net Profit */}
          <div className="flex items-center px-4 py-4 bg-blue-50">
            <span className="flex-1 text-sm font-bold text-blue-900">Net Profit / (Loss)</span>
            <span className={`w-32 text-right font-mono text-base font-bold ${plData.netProfitCurrent >= 0 ? "text-blue-900" : "text-red-700"}`}>
              {fmtPaise(plData.netProfitCurrent)}
            </span>
            <span className={`w-32 text-right font-mono text-sm ${plData.netProfitPrevious >= 0 ? "text-blue-600" : "text-red-500"}`}>
              {fmtPaise(plData.netProfitPrevious)}
            </span>
            <span className="w-20 text-right"><ChangeChip pct={changePct(plData.netProfitCurrent, plData.netProfitPrevious)} /></span>
          </div>
        </div>
      )}

      {/* Balance Sheet Comparison */}
      {!loading && tab === "bs" && bsData && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="flex items-center px-4 py-3 bg-gray-50 border-b border-gray-200 text-xs font-semibold text-gray-600">
            <span className="flex-1">Account</span>
            <span className="w-32 text-right">{currentFy.label}</span>
            <span className="w-32 text-right">{prevFy.label}</span>
            <span className="w-20 text-right">Change</span>
          </div>
          <CompareTable rows={bsData.assets} label="Assets" />
          <div className="flex items-center px-4 py-3 bg-gray-50 border-b border-gray-200">
            <span className="flex-1 text-sm font-semibold">Total Assets</span>
            <span className="w-32 text-right font-mono text-sm font-semibold">{fmtPaise(bsData.totalAssetsCurrent)}</span>
            <span className="w-32 text-right font-mono text-sm text-gray-500">{fmtPaise(bsData.totalAssetsPrevious)}</span>
            <span className="w-20 text-right"><ChangeChip pct={changePct(bsData.totalAssetsCurrent, bsData.totalAssetsPrevious)} /></span>
          </div>
          <CompareTable rows={bsData.liabilities} label="Liabilities" inverse />
          <div className="flex items-center px-4 py-3 bg-gray-50 border-b border-gray-200">
            <span className="flex-1 text-sm font-semibold">Total Liabilities</span>
            <span className="w-32 text-right font-mono text-sm font-semibold">{fmtPaise(bsData.totalLiabilitiesCurrent)}</span>
            <span className="w-32 text-right font-mono text-sm text-gray-500">{fmtPaise(bsData.totalLiabilitiesPrevious)}</span>
            <span className="w-20 text-right"><ChangeChip pct={changePct(bsData.totalLiabilitiesCurrent, bsData.totalLiabilitiesPrevious)} inverse /></span>
          </div>
          <CompareTable rows={bsData.equity} label="Equity" />
        </div>
      )}

      {/* Quarterly Trend */}
      {!loading && tab === "quarterly" && (
        <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-4">
          <h3 className="text-sm font-semibold text-gray-900">Quarterly Revenue vs Expenses — {currentFy.label}</h3>
          {quarterlyData.length > 0 && (() => {
            const maxVal = Math.max(...quarterlyData.map(q => Math.max(q.revenue, q.expenses)), 1);
            return (
              <div className="space-y-4">
                {quarterlyData.map(q => (
                  <div key={q.quarter} className="space-y-1">
                    <div className="flex items-center justify-between text-xs text-gray-600">
                      <span className="font-medium">{q.quarter}</span>
                      <span>
                        <span className="text-green-600 mr-3">Rev: {fmtPaise(q.revenue)}</span>
                        <span className="text-red-500">Exp: {fmtPaise(q.expenses)}</span>
                      </span>
                    </div>
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-400 w-16">Revenue</span>
                        <div className="flex-1 h-5 bg-gray-100 rounded overflow-hidden">
                          <div className="h-full bg-green-500 rounded"
                            style={{ width: `${Math.round((q.revenue / maxVal) * 100)}%` }} />
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-400 w-16">Expenses</span>
                        <div className="flex-1 h-5 bg-gray-100 rounded overflow-hidden">
                          <div className="h-full bg-red-400 rounded"
                            style={{ width: `${Math.round((q.expenses / maxVal) * 100)}%` }} />
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            );
          })()}
          {quarterlyData.every(q => q.revenue === 0 && q.expenses === 0) && (
            <p className="text-sm text-gray-400 text-center py-8">No journal data for this period</p>
          )}
        </div>
      )}

      {!loading && !plData && !bsData && (
        <div className="text-center py-12 text-gray-400">Select a client and load data to view reports</div>
      )}
    </div>
  );
}
