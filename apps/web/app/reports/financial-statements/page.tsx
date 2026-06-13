"use client";

/**
 * Financial Statements — Year-on-Year Comparison (P&L & Balance Sheet)
 *
 * Indian Financial Year: April 1 to March 31
 * FY label format: "2024-25" means April 1 2024 to March 31 2025
 *
 * All monetary values stored and computed in integer paise (never floating point).
 * Relevant law: CGST Act §2(69), Companies Act 2013 Schedule III
 */

import { useState, useCallback, useEffect } from "react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { formatPaise } from "@/lib/services/formatting";
import { Download, Loader2, AlertCircle, BarChart3, Share2, X, CheckCircle } from "lucide-react";
import * as XLSX from "xlsx";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Client {
  id: string;
  client_name: string;
}

interface AccountBalance {
  accountId: string;
  accountCode: string;
  accountName: string;
  accountType: "asset" | "liability" | "equity" | "revenue" | "expense";
  /** net balance in paise (credit - debit for revenue/liability/equity; debit - credit for asset/expense) */
  balancePaise: number;
}

interface PLData {
  incomeAccounts: AccountBalance[];
  expenseAccounts: AccountBalance[];
  totalIncome: number;
  totalExpenses: number;
  profitBeforeTax: number;
  taxExpense: number;
  profitAfterTax: number;
}

interface BSData {
  assetAccounts: AccountBalance[];
  liabilityAccounts: AccountBalance[];
  equityAccounts: AccountBalance[];
  totalAssets: number;
  totalLiabilities: number;
  totalEquity: number;
  totalLiabilitiesAndEquity: number;
}

// ─── FY helpers ───────────────────────────────────────────────────────────────

/**
 * Indian Financial Year: April 1 to March 31
 * "2024-25" → { from: "2024-04-01", to: "2025-03-31" }
 */
function fyToDateRange(fy: string): { from: string; to: string } {
  const startYear = parseInt(fy.split("-")[0], 10);
  return {
    from: `${startYear}-04-01`,
    to: `${startYear + 1}-03-31`,
  };
}

function currentFYLabel(): string {
  const now = new Date();
  const startYear = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  return `${startYear}-${String(startYear + 1).slice(2)}`;
}

function generateFYOptions(): string[] {
  const current = currentFYLabel();
  const [startYear] = current.split("-").map(Number);
  const options: string[] = [];
  for (let y = startYear; y >= startYear - 4; y--) {
    options.push(`${y}-${String(y + 1).slice(2)}`);
  }
  return options;
}

// ─── Data fetching ────────────────────────────────────────────────────────────

async function fetchClients(): Promise<Client[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { data, error } = await sb
    .from("clients")
    .select("id, client_name")
    .eq("firm_id", firmId)
    .order("client_name");
  if (error) throw new Error(error.message);
  return (data ?? []) as Client[];
}

/**
 * Fetch account balances for a given client and FY date range.
 * Uses integer paise arithmetic throughout — never floating point.
 */
async function fetchAccountBalances(
  clientId: string,
  from: string,
  to: string
): Promise<AccountBalance[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();

  // Fetch chart of accounts for this firm
  const { data: accounts, error: acctErr } = await sb
    .from("chart_of_accounts")
    .select("id, firm_id, code, name, account_type")
    .eq("firm_id", firmId);

  if (acctErr) throw new Error(acctErr.message);
  if (!accounts || accounts.length === 0) return [];

  // Fetch journal entries in the FY range for the given client
  const { data: entries, error: entryErr } = await sb
    .from("journal_entries")
    .select("id")
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .gte("entry_date", from)
    .lte("entry_date", to);

  if (entryErr) throw new Error(entryErr.message);
  if (!entries || entries.length === 0) return [];

  const entryIds = entries.map((e: { id: string }) => e.id);

  // Fetch all journal lines for those entries
  const { data: lines, error: lineErr } = await sb
    .from("journal_lines")
    .select("journal_entry_id, account_id, debit_paise, credit_paise")
    .in("journal_entry_id", entryIds);

  if (lineErr) throw new Error(lineErr.message);

  // Aggregate per account using integer paise (no floats)
  const debitMap = new Map<string, number>();
  const creditMap = new Map<string, number>();

  for (const line of lines ?? []) {
    const aid = line.account_id as string;
    debitMap.set(aid, (debitMap.get(aid) ?? 0) + (line.debit_paise as number));
    creditMap.set(aid, (creditMap.get(aid) ?? 0) + (line.credit_paise as number));
  }

  return accounts.map(
    (a: { id: string; code: string; name: string; account_type: string }) => {
      const debit = debitMap.get(a.id) ?? 0;
      const credit = creditMap.get(a.id) ?? 0;
      const type = a.account_type as AccountBalance["accountType"];

      // Normal balance convention:
      // revenue/liability/equity → credit - debit (credit balance is positive)
      // asset/expense → debit - credit (debit balance is positive)
      const balancePaise =
        type === "revenue" || type === "liability" || type === "equity"
          ? credit - debit
          : debit - credit;

      return {
        accountId: a.id,
        accountCode: a.code as string,
        accountName: a.name as string,
        accountType: type,
        balancePaise,
      };
    }
  );
}

async function buildPLData(balances: AccountBalance[]): Promise<PLData> {
  const incomeAccounts = balances
    .filter((b) => b.accountType === "revenue" && b.balancePaise !== 0)
    .sort((a, b) => a.accountCode.localeCompare(b.accountCode));

  const expenseAccounts = balances
    .filter((b) => b.accountType === "expense" && b.balancePaise !== 0)
    .sort((a, b) => a.accountCode.localeCompare(b.accountCode));

  // Integer paise arithmetic — no floating point
  const totalIncome = incomeAccounts.reduce((s, a) => s + a.balancePaise, 0);
  const totalExpenses = expenseAccounts.reduce((s, a) => s + a.balancePaise, 0);
  const profitBeforeTax = totalIncome - totalExpenses;

  // 30% tax provision — integer paise (truncated, no rounding float)
  // IT Act §115JB / normal corporate tax rate
  const taxExpense = profitBeforeTax > 0 ? Math.trunc(profitBeforeTax * 30) / 100 : 0;
  const profitAfterTax = profitBeforeTax - taxExpense;

  return {
    incomeAccounts,
    expenseAccounts,
    totalIncome,
    totalExpenses,
    profitBeforeTax,
    taxExpense,
    profitAfterTax,
  };
}

async function buildBSData(balances: AccountBalance[]): Promise<BSData> {
  const assetAccounts = balances
    .filter((b) => b.accountType === "asset" && b.balancePaise !== 0)
    .sort((a, b) => a.accountCode.localeCompare(b.accountCode));
  const liabilityAccounts = balances
    .filter((b) => b.accountType === "liability" && b.balancePaise !== 0)
    .sort((a, b) => a.accountCode.localeCompare(b.accountCode));
  const equityAccounts = balances
    .filter((b) => b.accountType === "equity" && b.balancePaise !== 0)
    .sort((a, b) => a.accountCode.localeCompare(b.accountCode));

  // Integer paise
  const totalAssets = assetAccounts.reduce((s, a) => s + a.balancePaise, 0);
  const totalLiabilities = liabilityAccounts.reduce((s, a) => s + a.balancePaise, 0);
  const totalEquity = equityAccounts.reduce((s, a) => s + a.balancePaise, 0);

  return {
    assetAccounts,
    liabilityAccounts,
    equityAccounts,
    totalAssets,
    totalLiabilities,
    totalEquity,
    totalLiabilitiesAndEquity: totalLiabilities + totalEquity,
  };
}

// ─── Variance helpers ─────────────────────────────────────────────────────────

function variance(current: number, prior: number): number {
  return current - prior;
}

function variancePct(current: number, prior: number): string {
  if (prior === 0) return current === 0 ? "—" : "N/A";
  const pct = ((current - prior) / Math.abs(prior)) * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

function varianceClass(v: number, isIncome: boolean): string {
  if (v === 0) return "text-[#64748B]";
  // For income: positive variance = good = green; negative = bad = red
  // For expense: positive variance = bad = red; negative = good = green
  if (isIncome) return v > 0 ? "text-green-600" : "text-red-600";
  return v > 0 ? "text-red-600" : "text-green-600";
}

// ─── Excel export ─────────────────────────────────────────────────────────────

function exportToExcel(
  currentFY: string,
  priorFY: string,
  currentPL: PLData,
  priorPL: PLData,
  currentBS: BSData,
  priorBS: BSData
): void {
  const wb = XLSX.utils.book_new();

  // Helper: paise to rupees string
  const r = (paise: number) => (paise / 100).toFixed(2);

  // P&L Sheet
  const plRows: (string | number)[][] = [
    ["Profit & Loss Statement — Year-on-Year Comparison"],
    [`FY ${currentFY} vs FY ${priorFY}`],
    [],
    ["Particulars", `FY ${currentFY} (₹)`, `FY ${priorFY} (₹)`, "Variance (₹)", "Variance %"],
    ["INCOME"],
    ...currentPL.incomeAccounts.map((a) => {
      const prior = priorPL.incomeAccounts.find((p) => p.accountId === a.accountId);
      const priorVal = prior?.balancePaise ?? 0;
      return [a.accountName, r(a.balancePaise), r(priorVal), r(a.balancePaise - priorVal), variancePct(a.balancePaise, priorVal)];
    }),
    ["TOTAL INCOME", r(currentPL.totalIncome), r(priorPL.totalIncome), r(currentPL.totalIncome - priorPL.totalIncome), variancePct(currentPL.totalIncome, priorPL.totalIncome)],
    [],
    ["EXPENSES"],
    ...currentPL.expenseAccounts.map((a) => {
      const prior = priorPL.expenseAccounts.find((p) => p.accountId === a.accountId);
      const priorVal = prior?.balancePaise ?? 0;
      return [a.accountName, r(a.balancePaise), r(priorVal), r(a.balancePaise - priorVal), variancePct(a.balancePaise, priorVal)];
    }),
    ["TOTAL EXPENSES", r(currentPL.totalExpenses), r(priorPL.totalExpenses), r(currentPL.totalExpenses - priorPL.totalExpenses), variancePct(currentPL.totalExpenses, priorPL.totalExpenses)],
    [],
    ["PROFIT BEFORE TAX", r(currentPL.profitBeforeTax), r(priorPL.profitBeforeTax), r(currentPL.profitBeforeTax - priorPL.profitBeforeTax), ""],
    ["Less: Tax Expense (30%)", r(currentPL.taxExpense), r(priorPL.taxExpense), "", ""],
    ["PROFIT AFTER TAX", r(currentPL.profitAfterTax), r(priorPL.profitAfterTax), r(currentPL.profitAfterTax - priorPL.profitAfterTax), ""],
  ];
  const wsP = XLSX.utils.aoa_to_sheet(plRows);
  XLSX.utils.book_append_sheet(wb, wsP, "P&L");

  // Balance Sheet
  const bsRows: (string | number)[][] = [
    ["Balance Sheet"],
    [`As at 31 March — FY ${currentFY} vs FY ${priorFY}`],
    [],
    ["Particulars", `FY ${currentFY} (₹)`, `FY ${priorFY} (₹)`],
    ["ASSETS"],
    ...currentBS.assetAccounts.map((a) => {
      const prior = priorBS.assetAccounts.find((p) => p.accountId === a.accountId);
      return [a.accountName, r(a.balancePaise), r(prior?.balancePaise ?? 0)];
    }),
    ["TOTAL ASSETS", r(currentBS.totalAssets), r(priorBS.totalAssets)],
    [],
    ["EQUITY"],
    ...currentBS.equityAccounts.map((a) => {
      const prior = priorBS.equityAccounts.find((p) => p.accountId === a.accountId);
      return [a.accountName, r(a.balancePaise), r(prior?.balancePaise ?? 0)];
    }),
    [],
    ["LIABILITIES"],
    ...currentBS.liabilityAccounts.map((a) => {
      const prior = priorBS.liabilityAccounts.find((p) => p.accountId === a.accountId);
      return [a.accountName, r(a.balancePaise), r(prior?.balancePaise ?? 0)];
    }),
    ["TOTAL LIABILITIES & EQUITY", r(currentBS.totalLiabilitiesAndEquity), r(priorBS.totalLiabilitiesAndEquity)],
  ];
  const wsB = XLSX.utils.aoa_to_sheet(bsRows);
  XLSX.utils.book_append_sheet(wb, wsB, "Balance Sheet");

  XLSX.writeFile(wb, `Financial_Statements_${currentFY}_vs_${priorFY}.xlsx`);
}

// ─── UI Components ────────────────────────────────────────────────────────────

function AmountCell({ paise }: { paise: number }) {
  return (
    <td className="px-4 py-2 text-right tabular-nums text-[#1E293B]">
      {formatPaise(paise)}
    </td>
  );
}

function VarianceCell({
  current,
  prior,
  isIncome,
}: {
  current: number;
  prior: number;
  isIncome: boolean;
}) {
  const v = variance(current, prior);
  const cls = varianceClass(v, isIncome);
  return (
    <td className={`px-4 py-2 text-right tabular-nums text-xs ${cls}`}>
      <div>{formatPaise(v)}</div>
      <div className="text-[#94A3B8]">{variancePct(current, prior)}</div>
    </td>
  );
}

interface PLTableProps {
  currentPL: PLData;
  priorPL: PLData;
  currentFY: string;
  priorFY: string;
}

function PLTable({ currentPL, priorPL, currentFY, priorFY }: PLTableProps) {
  const colHeader =
    "px-4 py-3 text-right text-xs font-semibold text-[#64748B] uppercase tracking-wide";
  const thLeft = "px-4 py-3 text-left text-xs font-semibold text-[#64748B] uppercase tracking-wide";

  // Build a union of income/expense accounts
  const incomeIdSet = new Set<string>();
  currentPL.incomeAccounts.forEach((a) => incomeIdSet.add(a.accountId));
  priorPL.incomeAccounts.forEach((a) => incomeIdSet.add(a.accountId));
  const allIncomeIds = Array.from(incomeIdSet);

  const expenseIdSet = new Set<string>();
  currentPL.expenseAccounts.forEach((a) => expenseIdSet.add(a.accountId));
  priorPL.expenseAccounts.forEach((a) => expenseIdSet.add(a.accountId));
  const allExpenseIds = Array.from(expenseIdSet);

  function accountName(id: string, cur: AccountBalance[], pri: AccountBalance[]): string {
    return (cur.find((a) => a.accountId === id) ?? pri.find((a) => a.accountId === id))!.accountName;
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-[#E2E8F0]">
      <table className="w-full text-sm">
        <thead className="bg-[#F8FAFC] border-b border-[#E2E8F0]">
          <tr>
            <th className={thLeft}>Particulars</th>
            <th className={colHeader}>FY {currentFY}</th>
            <th className={colHeader}>FY {priorFY}</th>
            <th className={colHeader}>Variance / %</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#F1F5F9]">
          {/* INCOME */}
          <tr className="bg-blue-50">
            <td colSpan={4} className="px-4 py-2 text-xs font-bold text-blue-700 uppercase tracking-wider">
              INCOME
            </td>
          </tr>
          {allIncomeIds.map((id) => {
            const cur = currentPL.incomeAccounts.find((a) => a.accountId === id)?.balancePaise ?? 0;
            const pri = priorPL.incomeAccounts.find((a) => a.accountId === id)?.balancePaise ?? 0;
            return (
              <tr key={id} className="hover:bg-[#F8FAFC]">
                <td className="px-4 py-2 pl-8 text-[#334155]">{accountName(id, currentPL.incomeAccounts, priorPL.incomeAccounts)}</td>
                <AmountCell paise={cur} />
                <AmountCell paise={pri} />
                <VarianceCell current={cur} prior={pri} isIncome={true} />
              </tr>
            );
          })}
          {allIncomeIds.length === 0 && (
            <tr>
              <td colSpan={4} className="px-4 py-3 pl-8 text-[#94A3B8] text-xs italic">No income accounts</td>
            </tr>
          )}
          <tr className="bg-blue-50 font-semibold">
            <td className="px-4 py-2.5 text-blue-800 text-sm">TOTAL INCOME</td>
            <AmountCell paise={currentPL.totalIncome} />
            <AmountCell paise={priorPL.totalIncome} />
            <VarianceCell current={currentPL.totalIncome} prior={priorPL.totalIncome} isIncome={true} />
          </tr>

          {/* EXPENSES */}
          <tr className="bg-red-50">
            <td colSpan={4} className="px-4 py-2 text-xs font-bold text-red-700 uppercase tracking-wider">
              EXPENSES
            </td>
          </tr>
          {allExpenseIds.map((id) => {
            const cur = currentPL.expenseAccounts.find((a) => a.accountId === id)?.balancePaise ?? 0;
            const pri = priorPL.expenseAccounts.find((a) => a.accountId === id)?.balancePaise ?? 0;
            return (
              <tr key={id} className="hover:bg-[#F8FAFC]">
                <td className="px-4 py-2 pl-8 text-[#334155]">{accountName(id, currentPL.expenseAccounts, priorPL.expenseAccounts)}</td>
                <AmountCell paise={cur} />
                <AmountCell paise={pri} />
                <VarianceCell current={cur} prior={pri} isIncome={false} />
              </tr>
            );
          })}
          {allExpenseIds.length === 0 && (
            <tr>
              <td colSpan={4} className="px-4 py-3 pl-8 text-[#94A3B8] text-xs italic">No expense accounts</td>
            </tr>
          )}
          <tr className="bg-red-50 font-semibold">
            <td className="px-4 py-2.5 text-red-800 text-sm">TOTAL EXPENSES</td>
            <AmountCell paise={currentPL.totalExpenses} />
            <AmountCell paise={priorPL.totalExpenses} />
            <VarianceCell current={currentPL.totalExpenses} prior={priorPL.totalExpenses} isIncome={false} />
          </tr>

          {/* PBT */}
          <tr className="border-t-2 border-gray-300 font-semibold bg-[#F8FAFC]">
            <td className="px-4 py-3 text-[#0F172A]">PROFIT BEFORE TAX</td>
            <AmountCell paise={currentPL.profitBeforeTax} />
            <AmountCell paise={priorPL.profitBeforeTax} />
            <VarianceCell current={currentPL.profitBeforeTax} prior={priorPL.profitBeforeTax} isIncome={true} />
          </tr>
          <tr className="hover:bg-[#F8FAFC]">
            <td className="px-4 py-2 pl-8 text-[#475569] text-sm">Less: Tax Expense (30% provision)</td>
            <AmountCell paise={currentPL.taxExpense} />
            <AmountCell paise={priorPL.taxExpense} />
            <td />
          </tr>
          <tr className="border-t-2 border-blue-300 font-bold bg-blue-50">
            <td className="px-4 py-3 text-blue-900 text-base">PROFIT AFTER TAX</td>
            <td className={`px-4 py-3 text-right tabular-nums text-base font-bold ${currentPL.profitAfterTax >= 0 ? "text-green-700" : "text-red-700"}`}>
              {formatPaise(currentPL.profitAfterTax)}
            </td>
            <td className={`px-4 py-3 text-right tabular-nums text-base font-bold ${priorPL.profitAfterTax >= 0 ? "text-green-700" : "text-red-700"}`}>
              {formatPaise(priorPL.profitAfterTax)}
            </td>
            <VarianceCell current={currentPL.profitAfterTax} prior={priorPL.profitAfterTax} isIncome={true} />
          </tr>
        </tbody>
      </table>
    </div>
  );
}

interface BSTableProps {
  currentBS: BSData;
  priorBS: BSData;
  currentFY: string;
  priorFY: string;
}

function BSTable({ currentBS, priorBS, currentFY, priorFY }: BSTableProps) {
  const colHeader =
    "px-4 py-3 text-right text-xs font-semibold text-[#64748B] uppercase tracking-wide";
  const thLeft = "px-4 py-3 text-left text-xs font-semibold text-[#64748B] uppercase tracking-wide";

  function SectionRows({
    label,
    curAccounts,
    priAccounts,
    colorClass,
  }: {
    label: string;
    curAccounts: AccountBalance[];
    priAccounts: AccountBalance[];
    colorClass: string;
  }) {
    const idSet = new Set<string>();
    curAccounts.forEach((a) => idSet.add(a.accountId));
    priAccounts.forEach((a) => idSet.add(a.accountId));
    const allIds = Array.from(idSet);

    function name(id: string): string {
      return (curAccounts.find((a) => a.accountId === id) ?? priAccounts.find((a) => a.accountId === id))!.accountName;
    }

    return (
      <>
        <tr className={colorClass}>
          <td colSpan={3} className="px-4 py-2 text-xs font-bold uppercase tracking-wider">
            {label}
          </td>
        </tr>
        {allIds.map((id) => {
          const cur = curAccounts.find((a) => a.accountId === id)?.balancePaise ?? 0;
          const pri = priAccounts.find((a) => a.accountId === id)?.balancePaise ?? 0;
          return (
            <tr key={id} className="hover:bg-[#F8FAFC]">
              <td className="px-4 py-2 pl-8 text-[#334155]">{name(id)}</td>
              <AmountCell paise={cur} />
              <AmountCell paise={pri} />
            </tr>
          );
        })}
        {allIds.length === 0 && (
          <tr>
            <td colSpan={3} className="px-4 py-3 pl-8 text-[#94A3B8] text-xs italic">None</td>
          </tr>
        )}
      </>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-[#E2E8F0]">
      <table className="w-full text-sm">
        <thead className="bg-[#F8FAFC] border-b border-[#E2E8F0]">
          <tr>
            <th className={thLeft}>Particulars</th>
            <th className={colHeader}>As at 31 Mar {currentFY.split("-")[0].slice(-2) === "99" ? "2099" : `20${currentFY.split("-")[1]}`}</th>
            <th className={colHeader}>As at 31 Mar {priorFY.split("-")[0].slice(-2) === "99" ? "2099" : `20${priorFY.split("-")[1]}`}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#F1F5F9]">
          <SectionRows
            label="ASSETS"
            curAccounts={currentBS.assetAccounts}
            priAccounts={priorBS.assetAccounts}
            colorClass="bg-emerald-50 text-emerald-700"
          />
          <tr className="bg-emerald-50 font-semibold">
            <td className="px-4 py-2.5 text-emerald-800">TOTAL ASSETS</td>
            <AmountCell paise={currentBS.totalAssets} />
            <AmountCell paise={priorBS.totalAssets} />
          </tr>

          <SectionRows
            label="EQUITY"
            curAccounts={currentBS.equityAccounts}
            priAccounts={priorBS.equityAccounts}
            colorClass="bg-purple-50 text-purple-700"
          />

          <SectionRows
            label="LIABILITIES"
            curAccounts={currentBS.liabilityAccounts}
            priAccounts={priorBS.liabilityAccounts}
            colorClass="bg-orange-50 text-orange-700"
          />
          <tr className="border-t-2 border-gray-300 bg-[#F8FAFC] font-semibold">
            <td className="px-4 py-3 text-[#0F172A]">TOTAL LIABILITIES &amp; EQUITY</td>
            <AmountCell paise={currentBS.totalLiabilitiesAndEquity} />
            <AmountCell paise={priorBS.totalLiabilitiesAndEquity} />
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function FinancialStatementsPage() {
  const fyOptions = generateFYOptions();
  const [activeTab, setActiveTab] = useState<"pl" | "bs" | "cashflow">("pl");

  // Controls
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [currentFY, setCurrentFY] = useState<string>(fyOptions[0]);
  const [priorFY, setPriorFY] = useState<string>(fyOptions[1]);

  // Report state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentPL, setCurrentPL] = useState<PLData | null>(null);
  const [priorPL, setPriorPL] = useState<PLData | null>(null);
  const [currentBS, setCurrentBS] = useState<BSData | null>(null);
  const [priorBS, setPriorBS] = useState<BSData | null>(null);

  // Share with client
  const [showShareModal, setShowShareModal] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [shareSuccess, setShareSuccess] = useState(false);

  // Load clients on mount
  useEffect(() => {
    fetchClients()
      .then((list) => {
        setClients(list);
        if (list.length > 0) setSelectedClientId(list[0].id);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load clients"));
  }, []);

  const generate = useCallback(async () => {
    if (!selectedClientId) {
      setError("Please select a client.");
      return;
    }
    setLoading(true);
    setError(null);
    setCurrentPL(null);
    setPriorPL(null);
    setCurrentBS(null);
    setPriorBS(null);

    try {
      const curRange = fyToDateRange(currentFY);
      const priRange = fyToDateRange(priorFY);

      const [curBalances, priBalances] = await Promise.all([
        fetchAccountBalances(selectedClientId, curRange.from, curRange.to),
        fetchAccountBalances(selectedClientId, priRange.from, priRange.to),
      ]);

      const [cPL, pPL, cBS, pBS] = await Promise.all([
        buildPLData(curBalances),
        buildPLData(priBalances),
        buildBSData(curBalances),
        buildBSData(priBalances),
      ]);

      setCurrentPL(cPL);
      setPriorPL(pPL);
      setCurrentBS(cBS);
      setPriorBS(pBS);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to generate report");
    } finally {
      setLoading(false);
    }
  }, [selectedClientId, currentFY, priorFY]);

  const hasData = currentPL && priorPL && currentBS && priorBS;

  const handleExport = useCallback(() => {
    if (!hasData) return;
    exportToExcel(currentFY, priorFY, currentPL, priorPL, currentBS, priorBS);
  }, [hasData, currentFY, priorFY, currentPL, priorPL, currentBS, priorBS]);

  const handleShareWithClient = useCallback(async () => {
    if (!hasData || !selectedClientId) return;
    setSharing(true);
    setShareSuccess(false);
    try {
      // Generate Excel and upload to Supabase Storage
      const wb = XLSX.utils.book_new();
      const reportType = activeTab === "bs" ? "balance_sheet" : "pl";
      const label = activeTab === "bs" ? `Balance Sheet FY ${currentFY}` : `P&L FY ${currentFY}`;
      exportToExcel(currentFY, priorFY, currentPL, priorPL, currentBS, priorBS);

      // Build a simple CSV blob for sharing (Excel export already ran above for download)
      const rows: (string | number)[][] = [];
      if (activeTab === "pl" && currentPL) {
        rows.push(["P&L Statement", `FY ${currentFY}`, `FY ${priorFY}`]);
        rows.push(["INCOME"]);
        for (const a of currentPL.incomeAccounts) {
          const prior = priorPL?.incomeAccounts.find((x) => x.accountId === a.accountId);
          rows.push([a.accountName, a.balancePaise / 100, (prior?.balancePaise ?? 0) / 100]);
        }
        rows.push(["Total Income", currentPL.totalIncome / 100, (priorPL?.totalIncome ?? 0) / 100]);
        rows.push(["EXPENSES"]);
        for (const a of currentPL.expenseAccounts) {
          const prior = priorPL?.expenseAccounts.find((x) => x.accountId === a.accountId);
          rows.push([a.accountName, a.balancePaise / 100, (prior?.balancePaise ?? 0) / 100]);
        }
        rows.push(["Net Profit / (Loss)", currentPL.profitAfterTax / 100, (priorPL?.profitAfterTax ?? 0) / 100]);
      } else if (activeTab === "bs" && currentBS) {
        rows.push(["Balance Sheet", `FY ${currentFY}`, `FY ${priorFY}`]);
        rows.push(["ASSETS"]);
        for (const a of currentBS.assetAccounts) {
          const prior = priorBS?.assetAccounts.find((x) => x.accountId === a.accountId);
          rows.push([a.accountName, a.balancePaise / 100, (prior?.balancePaise ?? 0) / 100]);
        }
        rows.push(["Total Assets", currentBS.totalAssets / 100, (priorBS?.totalAssets ?? 0) / 100]);
      }

      const ws = XLSX.utils.aoa_to_sheet(rows);
      XLSX.utils.book_append_sheet(wb, ws, "Report");
      const buf = XLSX.write(wb, { type: "array", bookType: "xlsx" });
      const file = new File([buf], `${label}.xlsx`, { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });

      const sb = getSupabaseClient();
      const firmId = await getFirmId();
      const uuid = crypto.randomUUID();
      const storagePath = `${firmId}/${selectedClientId}/reports/${uuid}-${file.name}`;
      const { error: upErr } = await sb.storage.from("Documents").upload(storagePath, file, { contentType: file.type });
      if (upErr) throw new Error(upErr.message);

      const { error: dbErr } = await sb.from("shared_reports").insert({
        firm_id: firmId,
        client_id: selectedClientId,
        report_type: reportType,
        report_label: label,
        financial_year: currentFY,
        storage_path: storagePath,
        file_name: file.name,
        file_size_bytes: file.size,
      });
      if (dbErr) throw new Error(dbErr.message);

      setShareSuccess(true);
      setTimeout(() => { setShowShareModal(false); setShareSuccess(false); }, 1800);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Share failed");
    } finally {
      setSharing(false);
    }
  }, [hasData, selectedClientId, activeTab, currentFY, priorFY, currentPL, priorPL, currentBS, priorBS]);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A] flex items-center gap-2">
            <BarChart3 size={20} className="text-blue-600" />
            Financial Statements
          </h1>
          <p className="text-sm text-[#64748B] mt-0.5">Year-on-year comparison — P&L and Balance Sheet</p>
        </div>
        {hasData && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowShareModal(true)}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
            >
              <Share2 size={14} />
              Share with Client
            </button>
            <button
              onClick={handleExport}
              className="flex items-center gap-2 px-4 py-2 bg-white border border-[#E2E8F0] text-[#334155] text-sm font-medium rounded-lg hover:bg-[#F8FAFC] transition-colors shadow-sm"
            >
              <Download size={14} />
              Export Excel
            </button>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-[#F1F5F9] p-1 rounded-lg w-fit">
        {(["pl", "bs", "cashflow"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
              activeTab === tab
                ? "bg-white text-[#0F172A] shadow-sm"
                : "text-[#64748B] hover:text-[#334155]"
            }`}
          >
            {tab === "pl" ? "P&L" : tab === "bs" ? "Balance Sheet" : "Cash Flow Summary"}
          </button>
        ))}
      </div>

      {/* Controls */}
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-5">
        <div className="flex flex-wrap gap-4 items-end">
          {/* Client selector */}
          <div className="flex flex-col gap-1">
            <label className="text-xs text-[#64748B] font-medium">Client</label>
            <select
              value={selectedClientId}
              onChange={(e) => setSelectedClientId(e.target.value)}
              className="text-sm border border-[#E2E8F0] rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[200px]"
            >
              {clients.length === 0 && <option value="">Loading clients…</option>}
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.client_name}
                </option>
              ))}
            </select>
          </div>

          {/* Current FY */}
          <div className="flex flex-col gap-1">
            <label className="text-xs text-[#64748B] font-medium">Current FY</label>
            <select
              value={currentFY}
              onChange={(e) => setCurrentFY(e.target.value)}
              className="text-sm border border-[#E2E8F0] rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {fyOptions.map((fy) => (
                <option key={fy} value={fy}>
                  FY {fy}
                </option>
              ))}
            </select>
          </div>

          {/* Comparison FY */}
          <div className="flex flex-col gap-1">
            <label className="text-xs text-[#64748B] font-medium">Comparison FY</label>
            <select
              value={priorFY}
              onChange={(e) => setPriorFY(e.target.value)}
              className="text-sm border border-[#E2E8F0] rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {fyOptions.map((fy) => (
                <option key={fy} value={fy}>
                  FY {fy}
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={generate}
            disabled={loading || !selectedClientId}
            className="flex items-center gap-2 px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : null}
            {loading ? "Generating…" : "Generate"}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 p-3 bg-red-50 text-red-700 rounded-lg text-sm border border-red-200">
          <AlertCircle size={14} className="shrink-0" />
          {error}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && !hasData && (
        <div className="text-center py-16 text-[#94A3B8]">
          <BarChart3 size={40} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">Select a client and FY range, then click Generate.</p>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-16 gap-3 text-[#94A3B8]">
          <Loader2 size={22} className="animate-spin" />
          <span className="text-sm">Fetching journal data…</span>
        </div>
      )}

      {/* P&L Tab */}
      {hasData && activeTab === "pl" && (
        <PLTable
          currentPL={currentPL}
          priorPL={priorPL}
          currentFY={currentFY}
          priorFY={priorFY}
        />
      )}

      {/* Balance Sheet Tab */}
      {hasData && activeTab === "bs" && (
        <BSTable
          currentBS={currentBS}
          priorBS={priorBS}
          currentFY={currentFY}
          priorFY={priorFY}
        />
      )}

      {/* Cash Flow Summary Tab */}
      {hasData && activeTab === "cashflow" && (
        <div className="bg-white rounded-xl border border-[#E2E8F0] p-8 text-center text-[#94A3B8]">
          <BarChart3 size={32} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">Cash Flow Statement requires direct cash account mapping.</p>
          <p className="text-xs mt-1 text-[#CBD5E1]">Coming in next phase — configure cash &amp; bank accounts in Chart of Accounts first.</p>
        </div>
      )}

      {/* Share with Client Modal */}
      {showShareModal && (
        <div className="fixed inset-0 bg-[#0F172A]/60 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-[#0F172A]">Share with Client</h3>
              <button onClick={() => setShowShareModal(false)} className="text-[#94A3B8] hover:text-[#475569]">
                <X size={18} />
              </button>
            </div>
            {shareSuccess ? (
              <div className="flex flex-col items-center gap-3 py-4">
                <CheckCircle size={40} className="text-green-500" />
                <p className="text-sm font-medium text-[#0F172A]">Shared successfully!</p>
                <p className="text-xs text-[#94A3B8]">The client can now view and download this report from their portal.</p>
              </div>
            ) : (
              <>
                <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-sm text-blue-800">
                  <p className="font-medium">{activeTab === "bs" ? `Balance Sheet FY ${currentFY}` : `P&L FY ${currentFY}`}</p>
                  <p className="text-xs text-blue-600 mt-0.5">
                    {clients.find((c) => c.id === selectedClientId)?.client_name ?? "Selected client"}
                  </p>
                </div>
                <p className="text-xs text-[#64748B]">
                  This will upload an Excel copy to the client&apos;s portal under the <strong>Reports</strong> tab. The client can view and download it.
                </p>
                <div className="flex gap-2 justify-end pt-1">
                  <button
                    onClick={() => setShowShareModal(false)}
                    className="px-4 py-2 text-sm text-[#475569] border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleShareWithClient}
                    disabled={sharing}
                    className="flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-60"
                  >
                    {sharing ? <Loader2 size={14} className="animate-spin" /> : <Share2 size={14} />}
                    {sharing ? "Sharing…" : "Share"}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
