"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Pencil, Check, X, Download } from "lucide-react";
import * as XLSX from "xlsx";
import { Card, CardContent } from "@/components/ui/card";
import { formatPaise } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";
import type { Account } from "@/lib/types";

// ─── Types ─────────────────────────────────────────────────────────────────

type FY = "2025-26" | "2026-27";

interface QuarterActuals {
  q1: number; // paise
  q2: number;
  q3: number;
  q4: number;
}

interface BudgetRow {
  account_id: string;
  account_code: string;
  account_name: string;
  account_type: "Revenue" | "Expense";
  budget_paise: number;       // annual budget, integer paise — no floating point
  actuals: QuarterActuals;
}

// ─── localStorage helpers ──────────────────────────────────────────────────

function lsKey(fy: FY): string {
  return `practicesync_budget_${fy}`;
}

function loadBudgets(fy: FY): Record<string, number> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(localStorage.getItem(lsKey(fy)) ?? "{}") as Record<string, number>;
  } catch {
    return {};
  }
}

function saveBudget(fy: FY, accountId: string, paise: number): void {
  const existing = loadBudgets(fy);
  existing[accountId] = paise;
  localStorage.setItem(lsKey(fy), JSON.stringify(existing));
}

// ─── FY quarter date ranges (Indian FY: Apr 1 – Mar 31) ───────────────────

interface Quarter {
  label: string;
  start: string;
  end: string;
}

function fyQuarters(fy: FY): Quarter[] {
  const startYear = parseInt(fy.split("-")[0]);
  return [
    { label: "Q1", start: `${startYear}-04-01`, end: `${startYear}-06-30` },
    { label: "Q2", start: `${startYear}-07-01`, end: `${startYear}-09-30` },
    { label: "Q3", start: `${startYear}-10-01`, end: `${startYear}-12-31` },
    { label: "Q4", start: `${startYear + 1}-01-01`, end: `${startYear + 1}-03-31` },
  ];
}

// ─── Supabase helpers ──────────────────────────────────────────────────────

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found — please complete onboarding");
  return data.firm_id as string;
}

interface LineRow {
  account_id: string;
  debit_paise: number;
  credit_paise: number;
  journal_entries: { entry_date: string; status: string } | null;
}

async function fetchActualsForQuarter(
  firmId: string,
  start: string,
  end: string
): Promise<Record<string, number>> {
  const sb = getSupabaseClient();
  // Query journal_entry_lines joined with journal_entries for posted entries
  const { data } = await sb
    .from("journal_entry_lines")
    .select("account_id, debit_paise, credit_paise, journal_entries!inner(entry_date, status)")
    .eq("journal_entries.firm_id", firmId)
    .eq("journal_entries.status", "posted")
    .gte("journal_entries.entry_date", start)
    .lte("journal_entries.entry_date", end);

  const map: Record<string, number> = {};
  for (const row of (data ?? []) as unknown as LineRow[]) {
    if (!map[row.account_id]) map[row.account_id] = 0;
    // Net = debit - credit (positive = net debit)
    map[row.account_id] += row.debit_paise - row.credit_paise;
  }
  return map;
}

// ─── Component ─────────────────────────────────────────────────────────────

export default function BudgetPage() {
  const [fy, setFy] = useState<FY>("2025-26");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [rows, setRows] = useState<BudgetRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Inline editing state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState<string>("");

  const load = useCallback(async (selectedFy: FY) => {
    setLoading(true);
    setError(null);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();

      // Load Revenue + Expense accounts only
      const { data: accs, error: accErr } = await sb
        .from("accounts")
        .select("*")
        .eq("firm_id", firmId)
        .in("account_type", ["Revenue", "Expense"])
        .eq("is_active", true)
        .order("account_type")
        .order("account_name");
      if (accErr) throw new Error(accErr.message);

      setAccounts((accs ?? []) as Account[]);

      // Load actuals for all 4 quarters
      const quarters = fyQuarters(selectedFy);
      const [q1Map, q2Map, q3Map, q4Map] = await Promise.all(
        quarters.map(q => fetchActualsForQuarter(firmId, q.start, q.end))
      );

      const budgets = loadBudgets(selectedFy);

      const built: BudgetRow[] = ((accs ?? []) as Account[]).map(acc => ({
        account_id: acc.id,
        account_code: acc.account_code,
        account_name: acc.account_name,
        account_type: acc.account_type as "Revenue" | "Expense",
        budget_paise: budgets[acc.id] ?? 0,
        actuals: {
          q1: Math.abs(q1Map[acc.id] ?? 0),
          q2: Math.abs(q2Map[acc.id] ?? 0),
          q3: Math.abs(q3Map[acc.id] ?? 0),
          q4: Math.abs(q4Map[acc.id] ?? 0),
        },
      }));

      setRows(built);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(fy);
  }, [fy, load]);

  // ── Inline budget edit ─────────────────────────────────────────────────

  function startEdit(row: BudgetRow) {
    setEditingId(row.account_id);
    setEditValue(String(row.budget_paise / 100)); // show in rupees
  }

  function cancelEdit() {
    setEditingId(null);
    setEditValue("");
  }

  function confirmEdit(accountId: string) {
    const rupees = parseFloat(editValue);
    if (isNaN(rupees) || rupees < 0) { cancelEdit(); return; }
    // All money stored as integer paise — no floating point
    const paise = Math.round(rupees * 100);
    saveBudget(fy, accountId, paise);
    setRows(prev => prev.map(r => r.account_id === accountId ? { ...r, budget_paise: paise } : r));
    setEditingId(null);
    setEditValue("");
  }

  // ── Summary calculations ───────────────────────────────────────────────

  const revenueRows = rows.filter(r => r.account_type === "Revenue");
  const expenseRows = rows.filter(r => r.account_type === "Expense");

  function sumBudget(rws: BudgetRow[]): number {
    return rws.reduce((s, r) => s + r.budget_paise, 0);
  }
  function sumYTD(rws: BudgetRow[]): number {
    return rws.reduce((s, r) => s + r.actuals.q1 + r.actuals.q2 + r.actuals.q3 + r.actuals.q4, 0);
  }

  const totalBudgetRevenue = sumBudget(revenueRows);
  const totalActualRevenue = sumYTD(revenueRows);
  const totalBudgetExpense = sumBudget(expenseRows);
  const totalActualExpense = sumYTD(expenseRows);
  const budgetedProfit = totalBudgetRevenue - totalBudgetExpense;
  const actualProfit = totalActualRevenue - totalActualExpense;

  // ── Variance helpers ───────────────────────────────────────────────────

  /**
   * Returns Tailwind color class for variance cell.
   * For Revenue: positive variance (actual > budget) = green; negative = red.
   * For Expense: positive variance (actual > budget) = red (over budget); negative = green (under budget).
   */
  function varianceColor(type: "Revenue" | "Expense", variance: number): string {
    if (variance === 0) return "text-[#64748B]";
    if (type === "Revenue") return variance > 0 ? "text-green-700" : "text-red-600";
    return variance > 0 ? "text-red-600" : "text-green-700";
  }

  function variancePct(budget: number, ytd: number): string {
    if (budget === 0) return ytd === 0 ? "0%" : "N/A";
    return ((Math.abs(ytd - budget) / budget) * 100).toFixed(1) + "%";
  }

  // ─── Render ──────────────────────────────────────────────────────────────

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A]">Budget vs Actuals</h1>
          <p className="text-sm text-[#64748B] mt-0.5">Compare budgeted amounts with posted journal entries</p>
        </div>
        <button
          onClick={() => {
            const exportRows = rows.map(r => {
              const ytd = r.actuals.q1 + r.actuals.q2 + r.actuals.q3 + r.actuals.q4;
              const variance = ytd - r.budget_paise;
              return {
                Code: r.account_code,
                Account: r.account_name,
                Type: r.account_type,
                "Budget (₹)": (r.budget_paise / 100).toFixed(2),
                "Q1 Actual (₹)": (r.actuals.q1 / 100).toFixed(2),
                "Q2 Actual (₹)": (r.actuals.q2 / 100).toFixed(2),
                "Q3 Actual (₹)": (r.actuals.q3 / 100).toFixed(2),
                "Q4 Actual (₹)": (r.actuals.q4 / 100).toFixed(2),
                "YTD Actual (₹)": (ytd / 100).toFixed(2),
                "Variance (₹)": (variance / 100).toFixed(2),
              };
            });
            const ws = XLSX.utils.json_to_sheet(exportRows);
            const wb = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(wb, ws, "Budget");
            XLSX.writeFile(wb, `budget_vs_actuals_${fy}.xlsx`);
          }}
          disabled={rows.length === 0}
          className="flex items-center gap-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md hover:bg-[#F8FAFC] disabled:opacity-40"
        >
          <Download size={14} /> Export
        </button>
        {/* FY Selector */}
        <select
          value={fy}
          onChange={e => setFy(e.target.value as FY)}
          className="text-sm border border-[#E2E8F0] px-3 py-1.5 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="2025-26">FY 2025–26</option>
          <option value="2026-27">FY 2026–27</option>
        </select>
      </div>

      {/* Summary Bar */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {[
          { label: "Budgeted Revenue", value: totalBudgetRevenue, color: "text-blue-700" },
          { label: "Actual Revenue", value: totalActualRevenue, color: "text-green-700" },
          { label: "Budgeted Expenses", value: totalBudgetExpense, color: "text-blue-700" },
          { label: "Actual Expenses", value: totalActualExpense, color: "text-orange-700" },
          { label: "Budgeted Profit", value: budgetedProfit, color: budgetedProfit >= 0 ? "text-green-700" : "text-red-600" },
          { label: "Actual Profit", value: actualProfit, color: actualProfit >= 0 ? "text-green-700" : "text-red-600" },
        ].map(s => (
          <Card key={s.label}>
            <CardContent className="pt-4 pb-3">
              <p className={`text-lg font-bold tabular-nums ${s.color}`}>{formatPaise(s.value)}</p>
              <p className="text-xs text-[#64748B] mt-0.5">{s.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>
      )}

      {/* Loading */}
      {loading ? (
        <div className="space-y-2 animate-pulse">
          {[1, 2, 3].map(i => <div key={i} className="h-10 bg-[#F1F5F9] rounded" />)}
        </div>
      ) : (
        <>
          {/* Revenue Table */}
          <BudgetTable
            title="Revenue Accounts"
            accentClass="bg-green-100 text-green-700"
            rows={revenueRows}
            editingId={editingId}
            editValue={editValue}
            onEditValue={setEditValue}
            onStartEdit={startEdit}
            onConfirmEdit={confirmEdit}
            onCancelEdit={cancelEdit}
            varianceColor={varianceColor}
            variancePct={variancePct}
          />

          {/* Expense Table */}
          <BudgetTable
            title="Expense Accounts"
            accentClass="bg-orange-100 text-orange-700"
            rows={expenseRows}
            editingId={editingId}
            editValue={editValue}
            onEditValue={setEditValue}
            onStartEdit={startEdit}
            onConfirmEdit={confirmEdit}
            onCancelEdit={cancelEdit}
            varianceColor={varianceColor}
            variancePct={variancePct}
          />

          {accounts.length === 0 && (
            <div className="text-center py-10 text-sm text-[#94A3B8]">
              No Revenue or Expense accounts found. Import accounts via{" "}
              <Link href="/accounting/coa-import" className="text-blue-600 hover:underline">Import COA</Link>.
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─── BudgetTable sub-component ─────────────────────────────────────────────

interface BudgetTableProps {
  title: string;
  accentClass: string;
  rows: BudgetRow[];
  editingId: string | null;
  editValue: string;
  onEditValue: (v: string) => void;
  onStartEdit: (row: BudgetRow) => void;
  onConfirmEdit: (id: string) => void;
  onCancelEdit: () => void;
  varianceColor: (type: "Revenue" | "Expense", variance: number) => string;
  variancePct: (budget: number, ytd: number) => string;
}

function BudgetTable({
  title,
  accentClass,
  rows,
  editingId,
  editValue,
  onEditValue,
  onStartEdit,
  onConfirmEdit,
  onCancelEdit,
  varianceColor,
  variancePct,
}: BudgetTableProps) {
  if (rows.length === 0) return null;

  return (
    <Card>
      <div className="px-5 py-3 border-b border-gray-50 flex items-center gap-2">
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${accentClass}`}>{title}</span>
        <span className="text-xs text-[#94A3B8]">{rows.length} accounts</span>
        <span className="ml-2 text-xs text-[#94A3B8]">— Click the budget cell to edit</span>
      </div>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm min-w-[800px]">
          <thead>
            <tr className="text-xs text-[#94A3B8] border-b border-[#F1F5F9]">
              <th className="px-5 py-2.5 text-left font-medium w-48">Account</th>
              <th className="px-3 py-2.5 text-right font-medium">Annual Budget</th>
              <th className="px-3 py-2.5 text-right font-medium">Q1 Actual</th>
              <th className="px-3 py-2.5 text-right font-medium">Q2 Actual</th>
              <th className="px-3 py-2.5 text-right font-medium">Q3 Actual</th>
              <th className="px-3 py-2.5 text-right font-medium">Q4 Actual</th>
              <th className="px-3 py-2.5 text-right font-medium">YTD Actual</th>
              <th className="px-3 py-2.5 text-right font-medium">Variance</th>
              <th className="px-5 py-2.5 text-right font-medium">Var %</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F8FAFC]">
            {rows.map(row => {
              const ytd = row.actuals.q1 + row.actuals.q2 + row.actuals.q3 + row.actuals.q4;
              const variance = ytd - row.budget_paise;
              const isEditing = editingId === row.account_id;

              return (
                <tr key={row.account_id} className="hover:bg-[#F8FAFC] group">
                  <td className="px-5 py-2.5">
                    <div>
                      <p className="text-sm font-medium text-[#0F172A] truncate max-w-[180px]">{row.account_name}</p>
                      <p className="text-xs text-[#94A3B8] font-mono">{row.account_code}</p>
                    </div>
                  </td>
                  {/* Annual Budget — inline editable */}
                  <td className="px-3 py-2.5 text-right">
                    {isEditing ? (
                      <div className="flex items-center justify-end gap-1">
                        <input
                          autoFocus
                          type="number"
                          min={0}
                          step={0.01}
                          value={editValue}
                          onChange={e => onEditValue(e.target.value)}
                          onKeyDown={e => {
                            if (e.key === "Enter") onConfirmEdit(row.account_id);
                            if (e.key === "Escape") onCancelEdit();
                          }}
                          className="w-28 px-2 py-1 text-xs border border-blue-400 rounded focus:outline-none text-right"
                          placeholder="₹ amount"
                        />
                        <button onClick={() => onConfirmEdit(row.account_id)} className="text-green-600 hover:text-green-800">
                          <Check size={13} />
                        </button>
                        <button onClick={onCancelEdit} className="text-[#94A3B8] hover:text-[#334155]">
                          <X size={13} />
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => onStartEdit(row)}
                        className="group/edit flex items-center gap-1 justify-end w-full text-[#0F172A] font-medium tabular-nums hover:text-blue-700"
                        title="Click to edit budget"
                      >
                        {row.budget_paise === 0 ? (
                          <span className="text-[#CBD5E1] text-xs">Set budget</span>
                        ) : (
                          formatPaise(row.budget_paise)
                        )}
                        <Pencil size={10} className="opacity-0 group-hover/edit:opacity-100 text-blue-600 shrink-0" />
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-[#475569]">{formatPaise(row.actuals.q1)}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-[#475569]">{formatPaise(row.actuals.q2)}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-[#475569]">{formatPaise(row.actuals.q3)}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-[#475569]">{formatPaise(row.actuals.q4)}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums font-medium text-[#1E293B]">{formatPaise(ytd)}</td>
                  <td className={`px-3 py-2.5 text-right tabular-nums font-medium ${varianceColor(row.account_type, variance)}`}>
                    {variance >= 0 ? "+" : ""}{formatPaise(variance)}
                  </td>
                  <td className={`px-5 py-2.5 text-right text-xs ${varianceColor(row.account_type, variance)}`}>
                    {variancePct(row.budget_paise, ytd)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
