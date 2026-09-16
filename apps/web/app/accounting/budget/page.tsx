"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Pencil, Check, X, Download } from "lucide-react";
import * as XLSX from "xlsx";
import { Card, CardContent } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import { formatPaise } from "@/lib/services/formatting";
import { financialYearChoicesAround } from "@/lib/dates/periods";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { getClients } from "@/lib/data/clients";
import { api, type BudgetRow, type BudgetVsActuals } from "@/lib/api";
import type { Client } from "@/lib/types";
import { paiseFromRupeeInput, rupeeInputFromPaise } from "@/lib/money/rupeeInput";

// ─── What changed here, and why (ACC-06) ────────────────────────────────────
//
// This screen used to keep every budget a CA typed in
// `localStorage["practicesync_budget_<fy>"]` and compute the actuals itself.
// Three things were wrong and the finding named one.
//
//   1. The budgets reached no database. Another device, another user, or a
//      cleared site-data, and the year was gone.
//
//   2. THE ACTUALS WERE SILENTLY TRUNCATED. `fetchActualsForQuarter` read
//      `journal_lines` joined to `journal_entries`, firm-wide, once per
//      quarter, with no paging. PostgREST caps a response at ~1000 rows and
//      reports NOTHING when it does, so on any client with real volume every
//      actual was short by an unknown amount and every variance was wrong —
//      confidently, with no error. CLAUDE.md's reporting rule is exactly this:
//      what crosses the wire must be the size of the ANSWER, not the ledger.
//
//   3. It was FIRM-WIDE. The chart came back on `firm_id` alone, so one grid
//      mixed every client's Revenue and Expense accounts and set them against
//      firm-wide actuals.
//
// All three are the same fix: GET /api/accounting/budgets, per client, with
// the actuals read once from `account_period_balances`. This file computes
// nothing except display formatting and the colour of a variance.

type FY = string;

export default function BudgetPage() {
  const [fy, setFy] = useState<FY>(() => financialYearChoicesAround(null)[0]);
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState<string>("");
  const [data, setData] = useState<BudgetVsActuals | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Inline editing state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState<string>("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getClients()
      .then(cs => {
        if (cancelled) return;
        setClients(cs);
        // A budget is a statement about one entity's year, so the screen needs
        // a client before it can say anything. Pre-selecting the first is a
        // convenience, not an assumption: the picker stays in the header.
        setClientId(prev => prev || (cs[0]?.id ?? ""));
      })
      .catch(e => !cancelled && setError(e instanceof Error ? e.message : "Failed to load clients"));
    return () => { cancelled = true; };
  }, []);

  const load = useCallback(async (selectedFy: FY, selectedClient: string) => {
    if (!selectedClient) { setData(null); return; }
    setLoading(true);
    setError(null);
    try {
      const res = await api.accounting.budgets(selectedClient, selectedFy);
      if (!res.success) throw new Error(res.error ?? "Failed to load");
      setData(res.data);
    } catch (e) {
      setData(null);
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(fy, clientId); }, [fy, clientId, load]);

  // ── Inline budget edit ─────────────────────────────────────────────────

  function startEdit(row: BudgetRow) {
    setEditingId(row.account_id);
    setEditValue(row.budget_paise === null ? "" : rupeeInputFromPaise(row.budget_paise));
  }

  function cancelEdit() {
    setEditingId(null);
    setEditValue("");
  }

  async function confirmEdit(accountId: string) {
    // Clearing the box REMOVES the budget rather than writing zero: "not
    // budgeted" and "budgeted at nil" are different statements and only the
    // second produces a variance. The server enforces the same distinction.
    const blank = editValue.trim() === "";
    // Integer paise through the one parser. parseFloat("1,25,000") is 1, so a
    // budget typed the way Indian amounts are grouped was saved as ₹1 and
    // every variance against it was wrong.
    const paise = blank ? null : paiseFromRupeeInput(editValue);
    if (!blank && paise === null) return;   // not an amount — keep the box open
    setSaving(true);
    try {
      const res = await api.accounting.saveBudget({
        client_id: clientId, fy, account_id: accountId, budget_paise: paise,
      });
      if (!res.success) throw new Error(res.error ?? "Failed to save");
      setData(prev => prev && {
        ...prev,
        rows: prev.rows.map(r => r.account_id === accountId
          ? { ...r, budget_paise: paise,
              variance_paise: paise === null ? null : r.actual_paise - paise }
          : r),
      });
      setEditingId(null);
      setEditValue("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  // ── Summary ────────────────────────────────────────────────────────────

  const rows = data?.rows ?? [];
  const quarterLabels = data?.quarters?.map(q => q.label) ?? [];
  const revenueRows = rows.filter(r => r.account_type === "Revenue" || r.account_type === "Income");
  const expenseRows = rows.filter(r => r.account_type === "Expense");

  const sumBudget = (rws: BudgetRow[]) => rws.reduce((s, r) => s + (r.budget_paise ?? 0), 0);
  const sumActual = (rws: BudgetRow[]) => rws.reduce((s, r) => s + r.actual_paise, 0);

  const totalBudgetRevenue = sumBudget(revenueRows);
  const totalActualRevenue = sumActual(revenueRows);
  const totalBudgetExpense = sumBudget(expenseRows);
  const totalActualExpense = sumActual(expenseRows);
  const budgetedProfit = totalBudgetRevenue - totalBudgetExpense;
  const actualProfit = totalActualRevenue - totalActualExpense;

  /**
   * Revenue: actual above budget is good. Expense: actual above budget is not.
   * A row with no budget has no variance and no colour — see variancePct.
   */
  function varianceColor(type: string | null, variance: number | null): string {
    if (variance === null || variance === 0) return "text-[#64748B]";
    if (type === "Revenue" || type === "Income") return variance > 0 ? "text-green-700" : "text-red-600";
    return variance > 0 ? "text-red-600" : "text-green-700";
  }

  function variancePct(budget: number | null, actual: number): string {
    // A percentage of nothing is not 100% over — it is no answer, and saying
    // otherwise puts every unbudgeted account at the top of a sorted column.
    if (budget === null) return "—";
    if (budget === 0) return actual === 0 ? "0%" : "N/A";
    return ((Math.abs(actual - budget) / Math.abs(budget)) * 100).toFixed(1) + "%";
  }

  function exportXlsx() {
    const exportRows = rows.map(r => {
      const out: Record<string, string | null> = {
        Code: r.account_code,
        Account: r.account_name,
        Type: r.account_type,
        "Budget (₹)": r.budget_paise === null ? "" : (r.budget_paise / 100).toFixed(2),
      };
      for (const q of quarterLabels) {
        out[`${q} Actual (₹)`] = ((r.actuals[q] ?? 0) / 100).toFixed(2);
      }
      out["Year Actual (₹)"] = (r.actual_paise / 100).toFixed(2);
      out["Variance (₹)"] = r.variance_paise === null ? "" : (r.variance_paise / 100).toFixed(2);
      return out;
    });
    const ws = XLSX.utils.json_to_sheet(exportRows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Budget");
    XLSX.writeFile(wb, `budget_vs_actuals_${fy}.xlsx`);
  }

  // ─── Render ──────────────────────────────────────────────────────────────

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1 min-w-[220px]">
          <h1 className="text-xl font-semibold text-[#0F172A]">Budget vs Actuals</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            Budgets are saved for the firm; actuals are the client&apos;s posted entries
          </p>
        </div>
        <div className="w-56">
          <ClientLookup
            clients={clients}
            value={clientId}
            onChange={setClientId}
            size="sm"
            ariaLabel="Client"
            placeholder="Select a client"
          />
        </div>
        <button
          onClick={exportXlsx}
          disabled={rows.length === 0}
          className="flex items-center gap-1 px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md hover:bg-[#F8FAFC] disabled:opacity-40"
        >
          <Download size={14} /> Export
        </button>
        {/* FY Selector — derived from the clock, never a list of literals. */}
        <select
          value={fy}
          onChange={e => setFy(e.target.value as FY)}
          className="text-sm border border-[#E2E8F0] px-3 py-1.5 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {financialYearChoicesAround(null).map(y => (
            <option key={y} value={y}>FY {y.replace("-", "–")}</option>
          ))}
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

      {!clientId && !loading && (
        <div className="text-center py-10 text-sm text-[#94A3B8]">
          Choose a client. A budget is a statement about one entity&apos;s year, and the
          actuals it is measured against are that client&apos;s posted entries.
        </div>
      )}

      {/* Loading */}
      {loading ? (
        <div className="space-y-4">
          <TableSkeleton cols={9} rows={4} />
          <TableSkeleton cols={9} rows={4} />
        </div>
      ) : clientId ? (
        <>
          <BudgetTable
            title="Revenue Accounts"
            accentClass="bg-green-100 text-green-700"
            rows={revenueRows}
            quarterLabels={quarterLabels}
            editingId={editingId}
            editValue={editValue}
            saving={saving}
            onEditValue={setEditValue}
            onStartEdit={startEdit}
            onConfirmEdit={confirmEdit}
            onCancelEdit={cancelEdit}
            varianceColor={varianceColor}
            variancePct={variancePct}
          />

          <BudgetTable
            title="Expense Accounts"
            accentClass="bg-orange-100 text-orange-700"
            rows={expenseRows}
            quarterLabels={quarterLabels}
            editingId={editingId}
            editValue={editValue}
            saving={saving}
            onEditValue={setEditValue}
            onStartEdit={startEdit}
            onConfirmEdit={confirmEdit}
            onCancelEdit={cancelEdit}
            varianceColor={varianceColor}
            variancePct={variancePct}
          />

          {rows.length === 0 && !error && (
            <div className="text-center py-10 text-sm text-[#94A3B8]">
              No Revenue or Expense accounts found for this client. Import accounts via{" "}
              <Link href="/accounting/coa-import" className="text-blue-600 hover:underline">Import COA</Link>.
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}

// ─── BudgetTable sub-component ─────────────────────────────────────────────

interface BudgetTableProps {
  title: string;
  accentClass: string;
  rows: BudgetRow[];
  quarterLabels: string[];
  editingId: string | null;
  editValue: string;
  saving: boolean;
  onEditValue: (v: string) => void;
  onStartEdit: (row: BudgetRow) => void;
  onConfirmEdit: (id: string) => void;
  onCancelEdit: () => void;
  varianceColor: (type: string | null, variance: number | null) => string;
  variancePct: (budget: number | null, actual: number) => string;
}

function BudgetTable({
  title,
  accentClass,
  rows,
  quarterLabels,
  editingId,
  editValue,
  saving,
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
        <span className="ml-2 text-xs text-[#94A3B8]">— Click the budget cell to edit; clear it to remove the budget</span>
      </div>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm min-w-[800px]">
          <thead>
            <tr className="text-xs text-[#94A3B8] border-b border-[#F1F5F9]">
              <th className="px-5 py-2.5 text-left font-medium w-48">Account</th>
              <th className="px-3 py-2.5 text-right font-medium">Annual Budget</th>
              {quarterLabels.map(q => (
                <th key={q} className="px-3 py-2.5 text-right font-medium">{q} Actual</th>
              ))}
              <th className="px-3 py-2.5 text-right font-medium">Year Actual</th>
              <th className="px-3 py-2.5 text-right font-medium">Variance</th>
              <th className="px-5 py-2.5 text-right font-medium">Var %</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F8FAFC]">
            {rows.map(row => {
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
                          type="text"
                          inputMode="decimal"
                          value={editValue}
                          onChange={e => onEditValue(e.target.value)}
                          onKeyDown={e => {
                            if (e.key === "Enter") onConfirmEdit(row.account_id);
                            if (e.key === "Escape") onCancelEdit();
                          }}
                          className="w-28 px-2 py-1 text-xs border border-blue-400 rounded focus:outline-none text-right"
                          placeholder="₹ amount"
                        />
                        <button
                          onClick={() => onConfirmEdit(row.account_id)}
                          disabled={saving}
                          className="text-green-600 hover:text-green-800 disabled:opacity-40"
                        >
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
                        {row.budget_paise === null ? (
                          <span className="text-[#CBD5E1] text-xs">Set budget</span>
                        ) : (
                          formatPaise(row.budget_paise)
                        )}
                        <Pencil size={10} className="opacity-0 group-hover/edit:opacity-100 text-blue-600 shrink-0" />
                      </button>
                    )}
                  </td>
                  {quarterLabels.map(q => (
                    <td key={q} className="px-3 py-2.5 text-right tabular-nums text-[#475569]">
                      {formatPaise(row.actuals[q] ?? 0)}
                    </td>
                  ))}
                  <td className="px-3 py-2.5 text-right tabular-nums font-medium text-[#1E293B]">{formatPaise(row.actual_paise)}</td>
                  <td className={`px-3 py-2.5 text-right tabular-nums font-medium ${varianceColor(row.account_type, row.variance_paise)}`}>
                    {row.variance_paise === null
                      ? <span className="text-[#CBD5E1]">—</span>
                      : <>{row.variance_paise >= 0 ? "+" : ""}{formatPaise(row.variance_paise)}</>}
                  </td>
                  <td className={`px-5 py-2.5 text-right text-xs ${varianceColor(row.account_type, row.variance_paise)}`}>
                    {variancePct(row.budget_paise, row.actual_paise)}
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
