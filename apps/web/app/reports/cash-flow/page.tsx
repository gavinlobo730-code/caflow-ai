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
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { Callout } from "@/components/ui/callout";

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
    // Opening balance through the one parser. parseFloat(x) || 0 read
    // "1,25,000" as ₹1 and any typo as ₹0, and this figure is the base every
    // closing balance in the statement is carried forward from — so one
    // unreadable keystroke moved every month on the report, silently.
    const openingPaise = paiseFromRupeeInput(openingBalanceInput.replace(/[,\s₹]/g, ""));
    if (openingPaise === null) {
      setError("Opening cash balance isn't an amount — enter rupees, like 125000 or 125000.50.");
      return;
    }

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

      const [invRes, loanRes] = await Promise.all([
        // Inflows: unpaid invoices due in next 6 months
        supabase
          .from("fee_invoices")
          .select("amount_paise, due_date")
          .eq("client_id", selectedClientId)
          .eq("status", "unpaid")
          .gte("due_date", today)
          .lt("due_date", sixMonthsLater),
        // Outflows: loan EMIs.
        // `next_emi_date` does not exist on loans and never has, so this query
        // used to 400 and — because the handler below rethrows — took the whole
        // forecast down. An active loan pays its EMI monthly between
        // disbursement and maturity, which is what the real columns describe.
        supabase
          .from("loans")
          .select("emi_paise, disbursement_date, maturity_date")
          .eq("client_id", selectedClientId)
          .eq("status", "active"),
      ]);
      // A non-null PostgREST error is a real failure, not "no rows" — silently
      // proceeding with partial data (e.g. loan EMIs missing) would render a
      // falsely rosy forecast with no indication anything went wrong.
      if (invRes.error) throw invRes.error;
      if (loanRes.error) throw loanRes.error;
      const invoices = invRes.data;
      const loans = loanRes.data;

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

      // An EMI falls in a forecast month when the loan is live for that month:
      // disbursed on or before it, and not yet matured. Walking the WINDOWS and
      // testing each is also what makes maturity actually bind — the previous
      // version spread the EMI over six months unconditionally, so a loan
      // maturing next month still showed five more payments.
      for (const loan of (loans ?? [])) {
        if (!loan.disbursement_date) continue;
        const start = new Date(loan.disbursement_date);
        const end = loan.maturity_date ? new Date(loan.maturity_date) : null;
        for (const w of windows) {
          // Compare on year*12+month so a mid-month disbursement still counts
          // for its own month rather than being pushed to the next one.
          const wIdx = w.year * 12 + w.month;
          if (wIdx < start.getFullYear() * 12 + start.getMonth()) continue;
          if (end && wIdx > end.getFullYear() * 12 + end.getMonth()) continue;
          const key = `${w.year}-${w.month}`;
          outflowByMonth[key] = (outflowByMonth[key] ?? 0) + (loan.emi_paise ?? 0);
        }
      }

      // TAX OUTFLOWS ARE NOT INCLUDED — see the notice rendered below.
      //
      // This used to read compliance_calendar.tax_amount_paise. That column
      // does not exist and no equivalent does: compliance_calendar carries the
      // SCHEDULE (compliance_type, due_date) and no amount at all. The amounts
      // live on `filings` (tax_payable_paise), which in turn has no due date,
      // and there is no foreign key joining the two.
      //
      // Pricing the leg would mean deriving GST/TDS due dates in the browser —
      // business logic that belongs in the backend (services/compliance_engine.py
      // is the authority on due dates). Rather than guess, or silently add zero
      // and present it as a complete forecast, the leg is omitted and the
      // omission is stated on screen. A CA must not read a fabricated tax
      // number in a cash-flow projection.

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
        <Link href="/reports" className="text-ps-hint hover:text-ps-label">
          <ArrowLeft size={16} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-ps-ink">Cash Flow Forecast</h1>
          <p className="text-sm text-ps-hint mt-0.5">6-month projection based on unpaid invoices and loan EMIs</p>
        </div>
      </div>

      {/* Controls */}
      <div className="bg-white rounded-xl border border-ps-muted p-5 flex flex-wrap items-end gap-4">
        <div className="flex-1 min-w-[200px]">
          <label className="block text-xs font-medium text-ps-label mb-1">Client *</label>
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
          <label className="block text-xs font-medium text-ps-label mb-1">Opening Cash Balance (₹)</label>
          <input
            type="text"
            inputMode="decimal"
            value={openingBalanceInput}
            onChange={e => setOpeningBalanceInput(e.target.value)}
            placeholder="0"
            className="w-full px-3 py-2 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
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

      {error && <Callout tone="problem">{error}</Callout>}

      {/* What this forecast does NOT contain. Shown with the results rather
          than buried in a tooltip: a CA reading a closing balance needs to know
          tax payments are missing from it before acting on the number. */}
      {rows.length > 0 && (
        <div className="bg-state-attention-surface border border-amber-100 rounded-lg px-4 py-3 text-xs text-amber-800">
          <span className="font-semibold">Excludes tax outflows.</span>{" "}
          GST and TDS payments are not included in these figures. The compliance
          calendar records when a filing is due but not how much is payable, so
          the amounts cannot be projected here yet. Treat the closing balances
          as before-tax.
        </div>
      )}

      {/* Table */}
      {rows.length > 0 && (
        <>
          <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ps-muted text-xs text-ps-hint bg-ps-bg">
                  <th className="px-5 py-3 text-left font-semibold">Month</th>
                  <th className="px-4 py-3 text-right font-semibold">Opening</th>
                  <th className="px-4 py-3 text-right font-semibold">Inflows</th>
                  <th className="px-4 py-3 text-right font-semibold">Outflows</th>
                  <th className="px-4 py-3 text-right font-semibold">Closing</th>
                  <th className="px-5 py-3 text-left font-semibold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-bg">
                {rows.map(row => (
                  <tr
                    key={row.label}
                    className={row.isSurplus ? "bg-green-50/40 hover:bg-green-50" : "bg-state-problem-surface/40 hover:bg-state-problem-surface"}
                  >
                    <td className="px-5 py-3 font-medium text-ps-ink text-xs">{row.label}</td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-ps-label">{fmt(row.opening)}</td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-green-700 font-semibold">
                      {row.inflows > 0 ? `+${fmt(row.inflows)}` : fmt(row.inflows)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-red-600 font-semibold">
                      {row.outflows > 0 ? `-${fmt(row.outflows)}` : fmt(row.outflows)}
                    </td>
                    <td className={`px-4 py-3 text-right font-mono text-sm font-bold ${row.isSurplus ? "text-green-800" : "text-state-problem"}`}>
                      {fmt(row.closing)}
                    </td>
                    <td className="px-5 py-3">
                      <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${
                        row.isSurplus
                          ? "bg-green-100 text-green-700"
                          : "bg-red-100 text-state-problem"
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
          <div className="bg-white rounded-xl border border-ps-muted p-5">
            <h2 className="text-xs font-semibold text-ps-body mb-4">Cash Flow Chart</h2>
            <div className="space-y-4">
              {rows.map(row => (
                <div key={row.label} className="space-y-1">
                  <div className="flex items-center justify-between text-xs text-ps-label">
                    <span className="w-14 shrink-0 font-medium">{row.label}</span>
                    <span className={`text-xs font-semibold ml-auto ${row.isSurplus ? "text-green-700" : "text-red-600"}`}>
                      {fmt(row.closing)}
                    </span>
                  </div>
                  <div className="flex gap-1 items-center">
                    {/* Inflows bar */}
                    <div className="flex-1 h-3 bg-ps-bg rounded overflow-hidden">
                      <div
                        className="h-full bg-green-400 rounded transition-all duration-500"
                        style={{ width: `${Math.round((row.inflows / maxPaise) * 100)}%` }}
                      />
                    </div>
                    {/* Outflows bar */}
                    <div className="flex-1 h-3 bg-ps-bg rounded overflow-hidden">
                      <div
                        className="h-full bg-red-400 rounded transition-all duration-500"
                        style={{ width: `${Math.round((row.outflows / maxPaise) * 100)}%` }}
                      />
                    </div>
                  </div>
                </div>
              ))}
              <div className="flex gap-4 text-xs text-ps-hint pt-1">
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
