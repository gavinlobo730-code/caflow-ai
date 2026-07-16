"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { RefreshCw, Camera, ChevronDown, ChevronRight } from "lucide-react";
import { yearEndApi, type FinancialStatementVersion, type FinancialStatementSnapshotData } from "@/lib/api/yearEnd";

/** Format paise → ₹ Indian number format (Companies Act §128: accounts in INR) */
function fmt(paise: number): string {
  if (paise === 0) return "—";
  const abs = Math.abs(paise);
  return (
    (paise < 0 ? "(" : "") +
    "₹" +
    new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(abs / 100) +
    (paise < 0 ? ")" : "")
  );
}

type FinTab = "balance_sheet" | "profit_loss";

// Schedule III BS group type
interface BSGroup {
  label: string;
  items: { name: string; amount_paise: number }[];
  total_paise: number;
}

interface PLLine {
  label: string;
  amount_paise: number;
  is_subtotal?: boolean;
  is_total?: boolean;
  is_negative?: boolean;
  is_header?: boolean;
}

// ── Schedule III line-code -> group/label mapping ──────────────────────────
// generate_financial_statements() (services/year_end_financial_service.py)
// returns flat {line_code: amount_paise} dicts in Companies Act 2013,
// Schedule III order (BS_EQUITY_LIABILITY_LINES / BS_ASSET_LINES /
// PL_INCOME_LINES / PL_EXPENSE_LINES) — grouped and labelled here into the
// Schedule III, Part I headings for display.
const EQUITY_LIABILITY_GROUPS: { label: string; lines: [string, string][] }[] = [
  { label: "Shareholders' Funds", lines: [
    ["share_capital", "Share Capital"],
    ["reserves_and_surplus", "Reserves and Surplus"],
  ] },
  { label: "Non-Current Liabilities", lines: [
    ["long_term_borrowings", "Long-Term Borrowings"],
    ["deferred_tax_liabilities", "Deferred Tax Liabilities (Net)"],
    ["other_long_term_liabilities", "Other Long-Term Liabilities"],
    ["long_term_provisions", "Long-Term Provisions"],
  ] },
  { label: "Current Liabilities", lines: [
    ["short_term_borrowings", "Short-Term Borrowings"],
    ["trade_payables", "Trade Payables"],
    ["other_current_liabilities", "Other Current Liabilities"],
    ["short_term_provisions", "Short-Term Provisions"],
  ] },
];

const ASSET_GROUPS: { label: string; lines: [string, string][] }[] = [
  { label: "Non-Current Assets", lines: [
    ["tangible_assets", "Tangible Assets"],
    ["intangible_assets", "Intangible Assets"],
    ["capital_wip", "Capital Work-in-Progress"],
    ["long_term_investments", "Non-Current Investments"],
    ["deferred_tax_assets", "Deferred Tax Assets (Net)"],
    ["long_term_loans_and_advances", "Long-Term Loans and Advances"],
    ["other_non_current_assets", "Other Non-Current Assets"],
  ] },
  { label: "Current Assets", lines: [
    ["current_investments", "Current Investments"],
    ["inventories", "Inventories"],
    ["trade_receivables", "Trade Receivables"],
    ["cash_and_bank", "Cash and Bank Balances"],
    ["short_term_loans_and_advances", "Short-Term Loans and Advances"],
    ["other_current_assets", "Other Current Assets"],
  ] },
];

const PL_INCOME_LABELS: [string, string][] = [
  ["revenue_from_operations", "Revenue from Operations"],
  ["other_income", "Other Income"],
];

const PL_EXPENSE_LABELS: [string, string][] = [
  ["cost_of_materials_consumed", "Cost of Materials Consumed"],
  ["purchases_of_stock_in_trade", "Purchases of Stock-in-Trade"],
  ["changes_in_inventories", "Changes in Inventories of Finished Goods, WIP and Stock-in-Trade"],
  ["employee_benefit_expense", "Employee Benefit Expense"],
  ["finance_costs", "Finance Costs"],
  ["depreciation_and_amortisation", "Depreciation and Amortisation Expense"],
  ["other_expenses", "Other Expenses"],
];

function mapBSGroups(
  groups: { label: string; lines: [string, string][] }[],
  data: Record<string, number> | undefined,
): BSGroup[] {
  if (!data) return [];
  return groups.map(({ label, lines }) => {
    const items = lines.map(([code, name]) => ({ name, amount_paise: data[code] ?? 0 }));
    return { label, items, total_paise: items.reduce((s, i) => s + i.amount_paise, 0) };
  });
}

function mapProfitLossLines(pl: FinancialStatementSnapshotData["profit_loss"] | undefined): PLLine[] {
  if (!pl) return [];
  const totalIncome = pl.total_income_paise ?? Object.values(pl.income).reduce((s, v) => s + v, 0);
  const totalExpense = pl.total_expense_paise ?? Object.values(pl.expenses).reduce((s, v) => s + v, 0);
  return [
    { label: "I. Income", amount_paise: 0, is_header: true },
    ...PL_INCOME_LABELS.map(([code, name]) => ({ label: name, amount_paise: pl.income[code] ?? 0 })),
    { label: "Total Income", amount_paise: totalIncome, is_subtotal: true },
    { label: "II. Expenses", amount_paise: 0, is_header: true },
    ...PL_EXPENSE_LABELS.map(([code, name]) => ({ label: name, amount_paise: pl.expenses[code] ?? 0 })),
    { label: "Total Expenses", amount_paise: totalExpense, is_subtotal: true },
    { label: "Profit Before Tax", amount_paise: pl.profit_before_tax_paise, is_subtotal: true },
    { label: "Tax Expense", amount_paise: pl.tax_expense_paise },
    { label: "Profit After Tax (for the period)", amount_paise: pl.profit_after_tax_paise, is_total: true },
  ];
}

export default function FinancialStatementsPage() {
  const params = useParams<{ id: string; engagementId: string }>();
  const { engagementId } = params;

  const [tab, setTab] = useState<FinTab>("balance_sheet");
  const [liveData, setLiveData] = useState<FinancialStatementSnapshotData | null>(null);
  const [versions, setVersions] = useState<FinancialStatementVersion[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string>("live");
  // versions() intentionally omits statement_data — a selected historical
  // version's Balance Sheet/P&L is fetched on demand and cached here,
  // keyed by version id so switching back to an already-fetched version
  // doesn't refetch.
  const [versionData, setVersionData] = useState<Record<string, FinancialStatementSnapshotData>>({});
  const [loading, setLoading] = useState(true);
  const [loadingVersion, setLoadingVersion] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [snapshotting, setSnapshotting] = useState(false);
  const [snapshotMsg, setSnapshotMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [liveRes, verRes] = await Promise.all([
        yearEndApi.financialStatements.getLive(engagementId),
        yearEndApi.financialStatements.versions(engagementId),
      ]);
      if (!liveRes.success) throw new Error(liveRes.error ?? "Failed to load statements");
      setLiveData(liveRes.data);
      setVersions(verRes.data ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [engagementId]);

  useEffect(() => { load(); }, [load]);

  // Fetch the selected historical version's statement_data the first time
  // it's picked (versions() never carries it — see the comment above).
  useEffect(() => {
    if (selectedVersionId === "live" || versionData[selectedVersionId]) return;
    let cancelled = false;
    (async () => {
      setLoadingVersion(true);
      try {
        const res = await yearEndApi.financialStatements.getVersion(engagementId, selectedVersionId);
        if (!res.success) throw new Error(res.error ?? "Failed to load version");
        if (!cancelled) setVersionData((prev) => ({ ...prev, [selectedVersionId]: res.data.statement_data }));
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load version");
      } finally {
        if (!cancelled) setLoadingVersion(false);
      }
    })();
    return () => { cancelled = true; };
  }, [engagementId, selectedVersionId, versionData]);

  async function handleSnapshot() {
    setSnapshotting(true);
    setSnapshotMsg(null);
    try {
      const res = await yearEndApi.financialStatements.createSnapshot(engagementId);
      if (!res.success) throw new Error(res.error ?? "Failed to create snapshot");
      const { statement_data, ...versionRow } = res.data;
      setVersions((prev) => [versionRow, ...prev]);
      setVersionData((prev) => ({ ...prev, [versionRow.id]: statement_data }));
      setSelectedVersionId(versionRow.id);
      setSnapshotMsg(`Version ${versionRow.version_number} snapshot created.`);
    } catch (err) {
      setSnapshotMsg(err instanceof Error ? err.message : "Snapshot failed");
    } finally {
      setSnapshotting(false);
    }
  }

  // Determine which data to display
  const activeData = selectedVersionId === "live" ? liveData : versionData[selectedVersionId] ?? null;

  const bs = mapBSGroups(EQUITY_LIABILITY_GROUPS, activeData?.balance_sheet.equity_and_liabilities);
  const assets = mapBSGroups(ASSET_GROUPS, activeData?.balance_sheet.assets);
  const totalEL = activeData?.balance_sheet.total_equity_and_liabilities_paise ?? 0;
  const totalAssets = activeData?.balance_sheet.total_assets_paise ?? 0;

  const pl = mapProfitLossLines(activeData?.profit_loss);

  const isBalanced = activeData?.balance_sheet.is_balanced ?? false;

  if (loading) {
    return (
      <div className="p-6 space-y-4 max-w-4xl">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-32 rounded-xl bg-[#F8FAFC] animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-4 text-sm text-red-700">
          {error}
          <button onClick={load} className="ml-3 underline text-xs">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4 max-w-4xl">
      {/* Top bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={load}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569]"
        >
          <RefreshCw size={12} /> Refresh from Ledger
        </button>
        <button
          onClick={handleSnapshot}
          disabled={snapshotting}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {snapshotting ? <RefreshCw size={12} className="animate-spin" /> : <Camera size={12} />}
          Create Snapshot
        </button>

        {/* Version selector */}
        {versions.length > 0 && (
          <select
            value={selectedVersionId}
            onChange={(e) => setSelectedVersionId(e.target.value)}
            className="text-xs border border-[#E2E8F0] rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="live">Live (Current)</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                Version {v.version_number} — {new Date(v.created_at).toLocaleDateString("en-IN")}
              </option>
            ))}
          </select>
        )}

        {/* Balance indicator */}
        <span className={`text-xs font-semibold px-2 py-1 rounded-lg ${isBalanced ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
          {isBalanced ? "✓ Balanced" : "✗ Not Balanced"}
        </span>

        {loadingVersion && (
          <span className="flex items-center gap-1.5 text-xs text-[#94A3B8]">
            <RefreshCw size={11} className="animate-spin" /> Loading version…
          </span>
        )}
      </div>

      {snapshotMsg && (
        <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-2 text-xs text-blue-700">
          {snapshotMsg}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-0.5 bg-[#F8FAFC] rounded-lg p-1 w-fit">
        {(["balance_sheet", "profit_loss"] as FinTab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              tab === t ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"
            }`}
          >
            {t === "balance_sheet" ? "Balance Sheet" : "Profit & Loss"}
          </button>
        ))}
      </div>

      {tab === "balance_sheet" && (
        <BalanceSheetView equityLiabilities={bs} assets={assets} totalEL={totalEL} totalAssets={totalAssets} />
      )}
      {tab === "profit_loss" && <ProfitLossView lines={pl} />}

      <p className="text-[10px] text-[#94A3B8]">
        All values derived from the General Ledger. Companies Act 2013, Schedule III.
      </p>
    </div>
  );
}

// ── Balance Sheet (Schedule III, Part I) ──────────────────────────────────

function BalanceSheetView({
  equityLiabilities,
  assets,
  totalEL,
  totalAssets,
}: {
  equityLiabilities: BSGroup[];
  assets: BSGroup[];
  totalEL: number;
  totalAssets: number;
}) {
  if (!equityLiabilities.length && !assets.length) {
    return (
      <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-12">
        <p className="text-sm text-[#64748B]">No data available. Refresh from ledger.</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Equity & Liabilities */}
      <StatementCard title="I. Equity & Liabilities" groups={equityLiabilities} grandTotal={totalEL} />
      {/* Assets */}
      <StatementCard title="II. Assets" groups={assets} grandTotal={totalAssets} />
    </div>
  );
}

function StatementCard({
  title,
  groups,
  grandTotal,
}: {
  title: string;
  groups: BSGroup[];
  grandTotal: number;
}) {
  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
      <div className="px-4 py-3 bg-[#F8FAFC] border-b border-[#F1F5F9]">
        <p className="text-[10px] font-bold text-[#475569] uppercase tracking-wide">{title}</p>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[#F1F5F9] text-[#94A3B8] text-[10px]">
            <th className="px-4 py-2 text-left font-semibold">Particulars</th>
            <th className="px-4 py-2 text-right font-semibold">Amount (₹)</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group, gi) => (
            <GroupRows key={gi} group={group} />
          ))}
          <tr className="border-t-2 border-[#E2E8F0] font-bold bg-[#F8FAFC]">
            <td className="px-4 py-2.5 text-[#0F172A] text-sm">Total</td>
            <td className="px-4 py-2.5 text-right font-mono text-[#0F172A] text-sm">{fmt(grandTotal)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function GroupRows({ group }: { group: BSGroup }) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <tr
        className="cursor-pointer hover:bg-[#F8FAFC] border-t border-[#F8FAFC]"
        onClick={() => setOpen((o) => !o)}
      >
        <td className="px-4 py-2 font-semibold text-[#334155] flex items-center gap-1">
          {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
          {group.label}
        </td>
        <td className="px-4 py-2 text-right font-mono font-semibold text-[#334155]">
          {fmt(group.total_paise)}
        </td>
      </tr>
      {open && group.items.map((item, i) => (
        <tr key={i} className="text-[#94A3B8]">
          <td className="px-4 py-1.5 pl-8">{item.name}</td>
          <td className="px-4 py-1.5 text-right font-mono">{fmt(item.amount_paise)}</td>
        </tr>
      ))}
    </>
  );
}

// ── Profit & Loss (Schedule III, Part II) ─────────────────────────────────

function ProfitLossView({ lines }: { lines: PLLine[] }) {
  if (!lines.length) {
    return (
      <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-12">
        <p className="text-sm text-[#64748B]">No data available. Refresh from ledger.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
      <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#F1F5F9]">
        <p className="text-[10px] font-bold text-[#475569] uppercase tracking-wide">
          Statement of Profit &amp; Loss
        </p>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[#F1F5F9] text-[#94A3B8] text-[10px]">
            <th className="px-5 py-2 text-left font-semibold">Particulars</th>
            <th className="px-4 py-2 text-right font-semibold">Amount (₹)</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line, i) => {
            if (line.is_total) {
              return (
                <tr key={i} className={`border-t-2 border-[#E2E8F0] font-bold ${(line.amount_paise ?? 0) >= 0 ? "bg-green-50" : "bg-red-50"}`}>
                  <td className="px-5 py-2.5 text-[#0F172A] text-sm">{line.label}</td>
                  <td className={`px-4 py-2.5 text-right font-mono text-sm ${(line.amount_paise ?? 0) >= 0 ? "text-green-700" : "text-red-700"}`}>
                    {fmt(line.amount_paise ?? 0)}
                  </td>
                </tr>
              );
            }
            if (line.is_subtotal) {
              return (
                <tr key={i} className="border-t border-[#E2E8F0] font-semibold">
                  <td className="px-5 py-2 text-[#1E293B]">{line.label}</td>
                  <td className="px-4 py-2 text-right font-mono text-[#0F172A]">{fmt(line.amount_paise ?? 0)}</td>
                </tr>
              );
            }
            if (line.is_header) {
              // Section header
              return (
                <tr key={i} className="bg-[#F8FAFC]">
                  <td colSpan={2} className="px-5 py-2 text-[10px] font-semibold uppercase tracking-wide text-[#334155]">
                    {line.label}
                  </td>
                </tr>
              );
            }
            return (
              <tr key={i} className="hover:bg-[#F8FAFC]">
                <td className="px-5 py-2 text-[#475569] pl-8">{line.label}</td>
                <td className="px-4 py-2 text-right font-mono text-[#334155]">{fmt(line.amount_paise ?? 0)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
