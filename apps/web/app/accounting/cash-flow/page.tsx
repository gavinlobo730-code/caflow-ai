"use client";

/**
 * Cash Flow Statement — Indirect Method
 * Companies Act 2013, Schedule III: Format for cash flow statement
 * AS-3 (Accounting Standard): Cash Flow Statements
 * Indirect method: Start with net profit, adjust for non-cash items and working capital changes
 */

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, TrendingUp, TrendingDown, Minus, Download } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { formatPaise } from "@/lib/services/formatting";

// ─── Types ───────────────────────────────────────────────────────────────────

interface JournalLine {
  account_id: string;
  debit_paise: number;
  credit_paise: number;
  account_name: string;
  account_type: string;
  account_code: string;
}

interface CashFlowSection {
  title: string;
  items: { label: string; amount_paise: number }[];
  total_paise: number;
}

// Indian Financial Year selector — April 1 to March 31
const FY_LIST = [
  { label: "FY 2025-26", start: "2025-04-01", end: "2026-03-31" },
  { label: "FY 2024-25", start: "2024-04-01", end: "2025-03-31" },
  { label: "FY 2023-24", start: "2023-04-01", end: "2024-03-31" },
];

// Account type classification for cash flow — AS-3
function classifyCashFlowActivity(accountCode: string, accountType: string, accountName: string): "operating" | "investing" | "financing" | "cash" {
  const code = accountCode?.toLowerCase() ?? "";
  const name = accountName?.toLowerCase() ?? "";
  const type = accountType?.toLowerCase() ?? "";

  // Cash and bank accounts
  if (name.includes("cash") || name.includes("bank") || code.startsWith("10")) return "cash";

  // Investing: Fixed assets, investments
  if (type === "asset" && (name.includes("fixed") || name.includes("equipment") || name.includes("vehicle") || name.includes("building") || name.includes("plant") || name.includes("machinery") || name.includes("investment") || name.includes("furniture"))) return "investing";

  // Financing: Capital, loans, dividends
  if (type === "equity" || name.includes("loan") || name.includes("capital") || name.includes("borrowing") || name.includes("dividend") || name.includes("debenture")) return "financing";

  // Everything else is operating (Revenue, Expense, Working Capital Assets/Liabilities)
  return "operating";
}

// ─── Cash Flow Computation ───────────────────────────────────────────────────

function computeCashFlow(lines: JournalLine[]): {
  operating: CashFlowSection;
  investing: CashFlowSection;
  financing: CashFlowSection;
  openingCash: number;
  closingCash: number;
} {
  // Group by account and net the debits/credits
  const accountMap = new Map<string, { name: string; type: string; code: string; net_paise: number }>();
  for (const l of lines) {
    const existing = accountMap.get(l.account_id) ?? { name: l.account_name, type: l.account_type, code: l.account_code, net_paise: 0 };
    // Net = debit - credit (positive = debit balance)
    existing.net_paise += (l.debit_paise - l.credit_paise);
    accountMap.set(l.account_id, existing);
  }

  const operatingItems: { label: string; amount_paise: number }[] = [];
  const investingItems: { label: string; amount_paise: number }[] = [];
  const financingItems: { label: string; amount_paise: number }[] = [];
  let cashChange = 0;

  for (const acct of Array.from(accountMap.values())) {
    const activity = classifyCashFlowActivity(acct.code, acct.type, acct.name);
    if (activity === "cash") {
      cashChange += acct.net_paise;
    } else if (activity === "operating") {
      // For revenue/expense accounts, net shows P&L contribution
      // For asset/liability working capital, net change affects operating cash
      const amt = acct.type === "Revenue" ? acct.net_paise : acct.type === "Expense" ? -acct.net_paise : -acct.net_paise;
      if (amt !== 0) operatingItems.push({ label: acct.name, amount_paise: amt });
    } else if (activity === "investing") {
      const amt = -acct.net_paise; // Asset increase = cash outflow
      if (amt !== 0) investingItems.push({ label: acct.name, amount_paise: amt });
    } else if (activity === "financing") {
      const amt = acct.type === "Equity" ? acct.net_paise : -acct.net_paise;
      if (amt !== 0) financingItems.push({ label: acct.name, amount_paise: amt });
    }
  }

  const operatingTotal = operatingItems.reduce((s, i) => s + i.amount_paise, 0);
  const investingTotal = investingItems.reduce((s, i) => s + i.amount_paise, 0);
  const financingTotal = financingItems.reduce((s, i) => s + i.amount_paise, 0);

  return {
    operating: {
      title: "A. Cash from Operating Activities",
      items: operatingItems,
      total_paise: operatingTotal,
    },
    investing: {
      title: "B. Cash from Investing Activities",
      items: investingItems,
      total_paise: investingTotal,
    },
    financing: {
      title: "C. Cash from Financing Activities",
      items: financingItems,
      total_paise: financingTotal,
    },
    openingCash: 0, // Would need prior year data
    closingCash: cashChange,
  };
}

// ─── Section Component ────────────────────────────────────────────────────────

function CashFlowSectionBlock({ section }: { section: CashFlowSection }) {
  const isPositive = section.total_paise >= 0;
  return (
    <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
      <div className={`px-5 py-3 border-b border-gray-50 flex items-center justify-between ${isPositive ? "bg-green-50/50" : "bg-red-50/50"}`}>
        <h3 className="text-sm font-semibold text-gray-900">{section.title}</h3>
        <div className="flex items-center gap-1.5">
          {isPositive ? <TrendingUp className="w-4 h-4 text-green-600" /> : <TrendingDown className="w-4 h-4 text-red-600" />}
          <span className={`text-sm font-bold ${isPositive ? "text-green-700" : "text-red-700"}`}>
            {formatPaise(Math.abs(section.total_paise))}
          </span>
        </div>
      </div>
      {section.items.length === 0 ? (
        <div className="px-5 py-4 text-xs text-gray-400">No transactions in this category for selected period</div>
      ) : (
        <table className="w-full text-sm">
          <tbody className="divide-y divide-gray-50">
            {section.items.map((item, i) => (
              <tr key={i} className="hover:bg-gray-50/30">
                <td className="px-5 py-2.5 text-xs text-gray-700">{item.label}</td>
                <td className={`px-5 py-2.5 text-xs font-medium text-right ${item.amount_paise >= 0 ? "text-green-700" : "text-red-700"}`}>
                  {item.amount_paise >= 0 ? "+" : ""}{formatPaise(item.amount_paise)}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-gray-200 bg-gray-50">
              <td className="px-5 py-2.5 text-xs font-semibold text-gray-700">Net Cash</td>
              <td className={`px-5 py-2.5 text-sm font-bold text-right ${isPositive ? "text-green-700" : "text-red-700"}`}>
                {formatPaise(section.total_paise)}
              </td>
            </tr>
          </tfoot>
        </table>
      )}
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function CashFlowPage() {
  const [selectedFY, setSelectedFY] = useState(0);
  const [lines, setLines] = useState<JournalLine[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fy = FY_LIST[selectedFY];

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const firmId = await getFirmId();
        const sb = getSupabaseClient();

        // Fetch journal lines with account info for the selected FY
        // AS-3: Cash flow from all journal entries in the period
        const { data, error: dbErr } = await sb
          .from("journal_lines")
          .select(`
            account_id,
            debit_paise,
            credit_paise,
            chart_of_accounts!inner (
              account_name,
              account_type,
              account_code
            ),
            journal_entries!inner (
              entry_date,
              firm_id
            )
          `)
          .eq("journal_entries.firm_id", firmId)
          .gte("journal_entries.entry_date", fy.start)
          .lte("journal_entries.entry_date", fy.end);

        if (dbErr) throw new Error(dbErr.message);

        const mapped: JournalLine[] = (data ?? []).map((r: Record<string, unknown>) => {
          const acct = r.chart_of_accounts as Record<string, string>;
          return {
            account_id: r.account_id as string,
            debit_paise: r.debit_paise as number,
            credit_paise: r.credit_paise as number,
            account_name: acct?.account_name ?? "",
            account_type: acct?.account_type ?? "",
            account_code: acct?.account_code ?? "",
          };
        });

        setLines(mapped);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load data");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [selectedFY, fy.start, fy.end]);

  const cf = computeCashFlow(lines);
  const netChange = cf.operating.total_paise + cf.investing.total_paise + cf.financing.total_paise;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-gray-900">Cash Flow Statement</h1>
          <p className="text-sm text-gray-500 mt-0.5">Indirect method — AS-3, Companies Act 2013 Schedule III</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={selectedFY}
            onChange={e => setSelectedFY(Number(e.target.value))}
          >
            {FY_LIST.map((f, i) => <option key={f.label} value={i}>{f.label}</option>)}
          </select>
          <button
            onClick={() => {
              const cf = computeCashFlow(lines);
              const rows = [
                ["Section", "Item", "Amount (₹)"],
                ...cf.operating.items.map(i => [cf.operating.title, i.label, String(Math.round(i.amount_paise / 100))]),
                [cf.operating.title, "Net Cash from Operations", String(Math.round(cf.operating.total_paise / 100))],
                ...cf.investing.items.map(i => [cf.investing.title, i.label, String(Math.round(i.amount_paise / 100))]),
                [cf.investing.title, "Net Cash from Investing", String(Math.round(cf.investing.total_paise / 100))],
                ...cf.financing.items.map(i => [cf.financing.title, i.label, String(Math.round(i.amount_paise / 100))]),
                [cf.financing.title, "Net Cash from Financing", String(Math.round(cf.financing.total_paise / 100))],
                ["Summary", "Net Change in Cash", String(Math.round(cf.closingCash / 100))],
              ];
              const csv = rows.map(r => r.map(c => `"${c}"`).join(",")).join("\n");
              const a = document.createElement("a");
              a.href = "data:text/csv;charset=utf-8," + encodeURIComponent(csv);
              a.download = `cash-flow-${fy.label.replace(/\s/g, "-")}.csv`;
              a.click();
            }}
            className="flex items-center gap-1.5 border border-gray-200 text-gray-600 text-sm px-3 py-1.5 rounded-lg hover:bg-gray-50"
          >
            <Download className="w-3.5 h-3.5" /> Export
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-100 rounded-lg px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {loading ? (
        <div className="space-y-4">
          {[1, 2, 3].map(i => <div key={i} className="h-32 bg-gray-100 rounded-xl animate-pulse" />)}
        </div>
      ) : (
        <>
          {/* Summary bar */}
          <div className="bg-white rounded-xl border border-gray-100 p-4">
            <div className="grid grid-cols-4 gap-4">
              {[
                { label: "Operating Activities", paise: cf.operating.total_paise, color: "text-blue-700" },
                { label: "Investing Activities", paise: cf.investing.total_paise, color: "text-purple-700" },
                { label: "Financing Activities", paise: cf.financing.total_paise, color: "text-orange-700" },
                { label: "Net Cash Change", paise: netChange, color: netChange >= 0 ? "text-green-700" : "text-red-700" },
              ].map(s => (
                <div key={s.label} className="text-center">
                  <p className="text-xs text-gray-400 mb-1">{s.label}</p>
                  <p className={`text-sm font-bold ${s.color}`}>{formatPaise(s.paise)}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Opening / Closing Cash */}
          <div className="bg-white rounded-xl border border-gray-100 p-4 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div>
                <p className="text-xs text-gray-400">Opening Cash Balance</p>
                <p className="text-sm font-semibold text-gray-900">{formatPaise(cf.openingCash)}</p>
              </div>
              <Minus className="w-4 h-4 text-gray-300" />
              <div>
                <p className="text-xs text-gray-400">Net Change</p>
                <p className={`text-sm font-semibold ${netChange >= 0 ? "text-green-700" : "text-red-700"}`}>{netChange >= 0 ? "+" : ""}{formatPaise(netChange)}</p>
              </div>
              <Minus className="w-4 h-4 text-gray-300" />
              <div>
                <p className="text-xs text-gray-400">Closing Cash Balance</p>
                <p className="text-sm font-semibold text-gray-900">{formatPaise(cf.closingCash)}</p>
              </div>
            </div>
            <p className="text-[10px] text-gray-400">FY: Apr {fy.start.slice(0, 4)} — Mar {fy.end.slice(0, 4)}</p>
          </div>

          {/* Three sections */}
          <CashFlowSectionBlock section={cf.operating} />
          <CashFlowSectionBlock section={cf.investing} />
          <CashFlowSectionBlock section={cf.financing} />

          <p className="text-[10px] text-gray-400 text-center">
            Prepared using indirect method per AS-3 (Accounting Standard on Cash Flow Statements) and Companies Act 2013 Schedule III.
          </p>
        </>
      )}
    </div>
  );
}
