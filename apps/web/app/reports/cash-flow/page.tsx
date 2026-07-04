"use client";

/**
 * Cash Flow Forecast — PracticeSync AI
 * 6-month cash flow projection per client.
 * All monetary values in integer paise. Never use floating point for rupee calculations.
 */

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, TrendingUp, TrendingDown, Loader2 } from "lucide-react";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { getSupabaseClient } from "@/lib/supabase/client";
import { useClientPicker } from "@/lib/workspace/useClientPicker";

// ─── Types ────────────────────────────────────────────────────────────────────

interface MonthRow {
  label: string;         // "Jul 2025"
  opening: number;       // paise
  inflows: number;       // paise
  outflows: number;      // paise
  closing: number;       // paise
  isSurplus: boolean;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Display integer paise as ₹ en-IN — never floating point */
function fmt(paise: number): string {
  const rupees = Math.floor(Math.abs(paise) / 100);
  const p = Math.abs(paise) % 100;
  const formatted = new Intl.NumberFormat("en-IN").format(rupees);
  const sign = paise < 0 ? "-" : "";
  return p > 0 ? `${sign}₹${formatted}.${String(p).padStart(2, "0")}` : `${sign}₹${formatted}`;
}

const MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

function addMonths(year: number, month: number, add: number): { year: number; month: number } {
  const total = month + add;
  return { year: year + Math.floor(total / 12), month: total % 12 };
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CashFlowForecastPage() {
  const { clients, clientId: selectedClientId, setClientId: setSelectedClientId } = useClientPicker();
  const [openingBalanceInput, setOpeningBalanceInput] = useState("0");
  const [rows, setRows] = useState<MonthRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate() {
    if (!selectedClientId) {
      setError("Please select a client");
      return;
    }
    // Parse opening balance from rupees input → paise (integer arithmetic)
    const rupeesInput = parseFloat(openingBalanceInput) || 0;
    const openingPaise = Math.round(rupeesInput * 100); // integer paise

    setLoading(true);
    setError(null);
    setRows([]);

    try {
      const supabase = getSupabaseClient();
      const now = new Date();
      const baseYear = now.getFullYear();
      const baseMonth = now.getMonth(); // 0-based

      // Build 6-month windows
      const windows = Array.from({ length: 6 }, (_, i) => addMonths(baseYear, baseMonth, i));

      // Load unpaid sales/fee invoices — expected inflows
      // Amount stored in paise — integer arithmetic throughout
      const sixMonthsLater = new Date(baseYear, baseMonth + 6, 1).toISOString();
      const today = new Date().toISOString();

      const [{ data: invoices }, { data: loans }, { data: compliance }] = await Promise.all([
        // Inflows: unpaid invoices due in next 6 months
        supabase
          .from("fee_invoices")
          .select("amount_paise, due_date")
          .eq("client_id", selectedClientId)
          .eq("status", "unpaid")
          .gte("due_date", today)
          .lt("due_date", sixMonthsLater),
        // Outflows: loan EMIs
        supabase
          .from("loans")
          .select("emi_paise, next_emi_date")
          .eq("client_id", selectedClientId)
          .eq("status", "active"),
        // Outflows: GST payments from compliance calendar
        supabase
          .from("compliance_calendar")
          .select("tax_amount_paise, due_date")
          .eq("client_id", selectedClientId)
          .in("filing_type", ["GSTR-3B", "TDS"])
          .gte("due_date", today)
          .lt("due_date", sixMonthsLater),
      ]);

      // Aggregate by month
      const inflowByMonth: Record<string, number> = {};
      const outflowByMonth: Record<string, number> = {};

      for (const inv of (invoices ?? [])) {
        if (!inv.due_date) continue;
        const d = new Date(inv.due_date);
        const key = `${d.getFullYear()}-${d.getMonth()}`;
        // Integer paise arithmetic — no floats
        inflowByMonth[key] = (inflowByMonth[key] ?? 0) + (inv.amount_paise ?? 0);
      }

      for (const loan of (loans ?? [])) {
        if (!loan.next_emi_date) continue;
        const d = new Date(loan.next_emi_date);
        // Spread EMI across all 6 months from next_emi_date
        for (let i = 0; i < 6; i++) {
          const m = addMonths(d.getFullYear(), d.getMonth(), i);
          const key = `${m.year}-${m.month}`;
          const inWindow = windows.some(w => w.year === m.year && w.month === m.month);
          if (inWindow) {
            outflowByMonth[key] = (outflowByMonth[key] ?? 0) + (loan.emi_paise ?? 0);
          }
        }
      }

      for (const c of (compliance ?? [])) {
        if (!c.due_date) continue;
        const d = new Date(c.due_date);
        const key = `${d.getFullYear()}-${d.getMonth()}`;
        outflowByMonth[key] = (outflowByMonth[key] ?? 0) + (c.tax_amount_paise ?? 0);
      }

      // Build rows — integer paise arithmetic, no floats
      let runningBalance = openingPaise;
      const result: MonthRow[] = windows.map(({ year, month }) => {
        const key = `${year}-${month}`;
        const inflows = inflowByMonth[key] ?? 0;
        const outflows = outflowByMonth[key] ?? 0;
        const opening = runningBalance;
        const closing = opening + inflows - outflows; // integer paise
        runningBalance = closing;
        return {
          label: `${MONTH_NAMES[month]} ${year}`,
          opening,
          inflows,
          outflows,
          closing,
          isSurplus: closing >= 0,
        };
      });

      setRows(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate forecast");
    } finally {
      setLoading(false);
    }
  }

  // Max paise for bar chart scaling
  const maxPaise = rows.length > 0
    ? Math.max(...rows.flatMap(r => [Math.abs(r.inflows), Math.abs(r.outflows)]), 1)
    : 1;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/reports" className="text-[#94A3B8] hover:text-[#475569]">
          <ArrowLeft size={16} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Cash Flow Forecast</h1>
          <p className="text-sm text-[#94A3B8] mt-0.5">6-month projection based on unpaid invoices, loans, and GST dues</p>
        </div>
      </div>

      {/* Controls */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 flex flex-wrap items-end gap-4">
        <div className="flex-1 min-w-[200px]">
          <label className="block text-xs font-medium text-[#475569] mb-1">Client *</label>
          <div className="w-full">
            <ClientLookup
              clients={clients}
              value={selectedClientId}
              onChange={setSelectedClientId}
              ariaLabel="Client"
              placeholder="Select client…"
            />
          </div>
        </div>

        <div className="w-52">
          <label className="block text-xs font-medium text-[#475569] mb-1">Opening Cash Balance (₹)</label>
          <input
            type="number"
            value={openingBalanceInput}
            onChange={e => setOpeningBalanceInput(e.target.value)}
            placeholder="0"
            className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <button
          onClick={handleGenerate}
          disabled={loading || !selectedClientId}
          className="flex items-center gap-1.5 px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40"
        >
          {loading && <Loader2 size={14} className="animate-spin" />}
          {loading ? "Generating…" : "Generate Forecast"}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-100 rounded-lg px-4 py-3 text-xs text-red-700">{error}</div>
      )}

      {/* Table */}
      {rows.length > 0 && (
        <>
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8] bg-[#F8FAFC]">
                  <th className="px-5 py-3 text-left font-semibold">Month</th>
                  <th className="px-4 py-3 text-right font-semibold">Opening</th>
                  <th className="px-4 py-3 text-right font-semibold">Inflows</th>
                  <th className="px-4 py-3 text-right font-semibold">Outflows</th>
                  <th className="px-4 py-3 text-right font-semibold">Closing</th>
                  <th className="px-5 py-3 text-left font-semibold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {rows.map(row => (
                  <tr
                    key={row.label}
                    className={row.isSurplus ? "bg-green-50/40 hover:bg-green-50" : "bg-red-50/40 hover:bg-red-50"}
                  >
                    <td className="px-5 py-3 font-medium text-[#0F172A] text-xs">{row.label}</td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-[#475569]">{fmt(row.opening)}</td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-green-700 font-semibold">
                      {row.inflows > 0 ? `+${fmt(row.inflows)}` : fmt(row.inflows)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-red-600 font-semibold">
                      {row.outflows > 0 ? `-${fmt(row.outflows)}` : fmt(row.outflows)}
                    </td>
                    <td className={`px-4 py-3 text-right font-mono text-sm font-bold ${row.isSurplus ? "text-green-800" : "text-red-700"}`}>
                      {fmt(row.closing)}
                    </td>
                    <td className="px-5 py-3">
                      <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${
                        row.isSurplus
                          ? "bg-green-100 text-green-700"
                          : "bg-red-100 text-red-700"
                      }`}>
                        {row.isSurplus
                          ? <TrendingUp size={11} />
                          : <TrendingDown size={11} />
                        }
                        {row.isSurplus ? "Surplus" : "Deficit"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Bar chart — div widths, no external lib */}
          <div className="bg-white rounded-xl border border-[#F1F5F9] p-5">
            <h2 className="text-xs font-semibold text-[#334155] mb-4">Cash Flow Chart</h2>
            <div className="space-y-4">
              {rows.map(row => (
                <div key={row.label} className="space-y-1">
                  <div className="flex items-center justify-between text-xs text-[#64748B]">
                    <span className="w-14 shrink-0 font-medium">{row.label}</span>
                    <span className={`text-xs font-semibold ml-auto ${row.isSurplus ? "text-green-700" : "text-red-600"}`}>
                      {fmt(row.closing)}
                    </span>
                  </div>
                  <div className="flex gap-1 items-center">
                    {/* Inflows bar */}
                    <div className="flex-1 h-3 bg-[#F8FAFC] rounded overflow-hidden">
                      <div
                        className="h-full bg-green-400 rounded transition-all duration-500"
                        style={{ width: `${Math.round((row.inflows / maxPaise) * 100)}%` }}
                      />
                    </div>
                    {/* Outflows bar */}
                    <div className="flex-1 h-3 bg-[#F8FAFC] rounded overflow-hidden">
                      <div
                        className="h-full bg-red-400 rounded transition-all duration-500"
                        style={{ width: `${Math.round((row.outflows / maxPaise) * 100)}%` }}
                      />
                    </div>
                  </div>
                </div>
              ))}
              <div className="flex gap-4 text-xs text-[#94A3B8] pt-1">
                <span className="flex items-center gap-1"><span className="w-3 h-2 bg-green-400 rounded inline-block" /> Inflows</span>
                <span className="flex items-center gap-1"><span className="w-3 h-2 bg-red-400 rounded inline-block" /> Outflows</span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
