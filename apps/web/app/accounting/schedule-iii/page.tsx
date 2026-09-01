"use client";

/**
 * Schedule III Financial Statements
 * Formats Balance Sheet and P&L as per Companies Act 2013, Schedule III
 * Reference: Section 129 of the Companies Act 2013 read with Schedule III
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Printer, AlertTriangle, Download } from "lucide-react";
import * as XLSX from "xlsx";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatementSkeleton } from "@/components/ui/skeleton";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { formatPaise } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";
import { api } from "@/lib/api";

// Financial year helpers — FY runs April 1 to March 31 (Indian fiscal year)
const CURRENT_FY_YEAR = new Date().getMonth() >= 3 ? new Date().getFullYear() : new Date().getFullYear() - 1;
const FY_OPTIONS = [CURRENT_FY_YEAR, CURRENT_FY_YEAR - 1, CURRENT_FY_YEAR - 2].map((y) => ({
  label: `FY ${y}-${String(y + 1).slice(2)}`,
  start: `${y}-04-01`,
  end: `${y + 1}-03-31`,
}));

interface Client {
  id: string;
  name: string;
}

interface LineItem {
  label: string;
  paise: number;
  indent?: boolean;
  /** The corresponding amount for the immediately preceding reporting period.
   *  Schedule III General Instructions para 5 makes this mandatory for ALL
   *  items including notes; it is null only where there is no preceding period,
   *  which is para 5's own exception for a company's first statements. */
  prior_paise?: number | null;
}

interface ScheduleSection {
  heading: string;
  lines: LineItem[];
  total_paise: number;
  totalLabel?: string;
  prior_total_paise?: number | null;
}

/** Whether this document has a comparative column at all, and why not. */
interface Comparatives {
  present: boolean;
  period: { fy_start: string | null; fy_end: string | null } | null;
  reason: string | null;
}

// ─── Data fetching ────────────────────────────────────────────────────────────

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found — please complete onboarding");
  return data.firm_id as string;
}

interface ScheduleData {
  balanceSheet: {
    equityAndLiabilities: ScheduleSection[];
    assets: ScheduleSection[];
    totalEquityLiab: number;
    totalAssets: number;
    isBalanced: boolean;
    totalEquityLiabPrior: number | null;
    totalAssetsPrior: number | null;
  };
  profitAndLoss: {
    revenue: ScheduleSection[];
    expenses: ScheduleSection[];
    totalRevenue: number;
    totalExpenses: number;
    profitBeforeTax: number;
    taxExpense: number;
    profitAfterTax: number;
    totalRevenuePrior: number | null;
    totalExpensesPrior: number | null;
    profitBeforeTaxPrior: number | null;
    taxExpensePrior: number | null;
    profitAfterTaxPrior: number | null;
  };
  comparatives: Comparatives;
}

// Backend Schedule III response (domain.reporting.schedule_iii). Amounts are
// authoritative, accrual, and already grouped into the statutory captions
// server-side (Companies Act 2013, Schedule III). The UI only renders.
interface ApiSection {
  heading: string; lines: LineItem[]; total_paise: number; total_label?: string;
  prior_total_paise?: number | null;
}
interface ScheduleApiData {
  balance_sheet: {
    equity_and_liabilities: ApiSection[];
    assets: ApiSection[];
    total_equity_liabilities_paise: number;
    total_assets_paise: number;
    is_balanced: boolean;
    total_equity_liabilities_prior_paise?: number | null;
    total_assets_prior_paise?: number | null;
  };
  profit_and_loss: {
    revenue: ApiSection[];
    expenses: ApiSection[];
    total_revenue_paise: number;
    total_expenses_paise: number;
    profit_before_tax_paise: number;
    tax_expense_paise: number;
    profit_after_tax_paise: number;
    total_revenue_prior_paise?: number | null;
    total_expenses_prior_paise?: number | null;
    profit_before_tax_prior_paise?: number | null;
    tax_expense_prior_paise?: number | null;
    profit_after_tax_prior_paise?: number | null;
  };
  comparatives: Comparatives;
}

const toSection = (s: ApiSection): ScheduleSection => ({
  heading: s.heading,
  lines: s.lines,
  total_paise: s.total_paise,
  totalLabel: s.total_label,
  prior_total_paise: s.prior_total_paise ?? null,
});

async function fetchScheduleData(
  clientId: string | null,
  fyStart: string,
  fyEnd: string
): Promise<ScheduleData> {
  // Schedule III is computed ENTIRELY server-side (CLAUDE.md: zero business
  // logic in the frontend) — statutory statements are accrual (Companies Act
  // §128). clientId=null returns the firm-wide ("All Clients") consolidation.
  const scope: Record<string, string> = { fy_start: fyStart, fy_end: fyEnd };
  if (clientId) scope.client_id = clientId;
  const res = (await api.accounting.scheduleIii(scope)) as {
    success: boolean; data: ScheduleApiData | null; error: string | null;
  };
  if (!res.success || !res.data) throw new Error(res.error ?? "Failed to load Schedule III");
  const d = res.data;
  return {
    balanceSheet: {
      equityAndLiabilities: d.balance_sheet.equity_and_liabilities.map(toSection),
      assets: d.balance_sheet.assets.map(toSection),
      totalEquityLiab: d.balance_sheet.total_equity_liabilities_paise,
      totalAssets: d.balance_sheet.total_assets_paise,
      isBalanced: d.balance_sheet.is_balanced,
      totalEquityLiabPrior: d.balance_sheet.total_equity_liabilities_prior_paise ?? null,
      totalAssetsPrior: d.balance_sheet.total_assets_prior_paise ?? null,
    },
    profitAndLoss: {
      revenue: d.profit_and_loss.revenue.map(toSection),
      expenses: d.profit_and_loss.expenses.map(toSection),
      totalRevenue: d.profit_and_loss.total_revenue_paise,
      totalExpenses: d.profit_and_loss.total_expenses_paise,
      profitBeforeTax: d.profit_and_loss.profit_before_tax_paise,
      taxExpense: d.profit_and_loss.tax_expense_paise,
      profitAfterTax: d.profit_and_loss.profit_after_tax_paise,
      totalRevenuePrior: d.profit_and_loss.total_revenue_prior_paise ?? null,
      totalExpensesPrior: d.profit_and_loss.total_expenses_prior_paise ?? null,
      profitBeforeTaxPrior: d.profit_and_loss.profit_before_tax_prior_paise ?? null,
      taxExpensePrior: d.profit_and_loss.tax_expense_prior_paise ?? null,
      profitAfterTaxPrior: d.profit_and_loss.profit_after_tax_prior_paise ?? null,
    },
    comparatives: d.comparatives,
  };
}

// ─── UI components ────────────────────────────────────────────────────────────

/** Schedule III presents amounts in brackets when negative, and an em dash for
 *  nil. A missing COMPARATIVE is different from a nil one and renders blank —
 *  see the comparatives banner for why. */
function amount(paise: number | null | undefined): string {
  if (paise === null || paise === undefined) return "";
  if (paise === 0) return "—";
  return paise < 0 ? `(${formatPaise(Math.abs(paise))})` : formatPaise(paise);
}

/**
 * One statutory section, with the preceding period's corresponding amounts
 * beside it.
 *
 * Schedule III General Instructions para 5: "the corresponding amounts
 * (comparatives) for the immediately preceding reporting period for ALL items
 * shown in the Financial Statements including notes shall also be given." A
 * one-column balance sheet is not a Schedule III balance sheet, so the second
 * column is not optional styling — it is the disclosure.
 *
 * `showPrior` comes from the document, not from whether a number happens to be
 * present: with no preceding period there is no column at all, rather than a
 * column of blanks a reader would take for nil.
 */
function SectionTable({ section, showPrior }: { section: ScheduleSection; showPrior: boolean }) {
  return (
    <div className="mb-4">
      <div className="bg-[#F8FAFC] px-4 py-2 border-b border-[#E2E8F0]">
        <p className="text-xs font-semibold text-[#334155] uppercase tracking-wide">{section.heading}</p>
      </div>
      {section.lines.map((line) => (
        <div key={line.label} className="flex items-baseline px-4 py-2 border-b border-[#F1F5F9] last:border-b-0">
          <span className={`text-sm text-[#334155] flex-1 ${line.indent ? "pl-4" : ""}`}>{line.label}</span>
          <span className="text-sm tabular-nums text-[#0F172A] font-medium w-36 text-right">
            {amount(line.paise)}
          </span>
          {showPrior && (
            <span className="text-sm tabular-nums text-[#64748B] w-36 text-right">
              {amount(line.prior_paise)}
            </span>
          )}
        </div>
      ))}
      <div className="flex items-baseline px-4 py-2.5 bg-blue-50 font-semibold">
        <span className="text-sm text-blue-900 flex-1">{section.totalLabel ?? `Total`}</span>
        <span className="text-sm tabular-nums text-blue-700 w-36 text-right">
          {formatPaise(section.total_paise)}
        </span>
        {showPrior && (
          <span className="text-sm tabular-nums text-blue-500 w-36 text-right">
            {amount(section.prior_total_paise)}
          </span>
        )}
      </div>
    </div>
  );
}

/** The column heads. Without them the second column is an unlabelled number. */
function ColumnHeads({ current, prior }: { current: string; prior: string | null }) {
  return (
    <div className="flex items-baseline px-4 py-1.5 border-b border-[#E2E8F0] bg-white">
      <span className="flex-1" />
      <span className="text-[10px] uppercase tracking-wide text-[#64748B] w-36 text-right">{current}</span>
      {prior && (
        <span className="text-[10px] uppercase tracking-wide text-[#94A3B8] w-36 text-right">{prior}</span>
      )}
    </div>
  );
}

/** A grand total row, in the same two-column grid as everything above it. */
function GrandTotal({ label, paise, prior, showPrior }: {
  label: string; paise: number; prior: number | null; showPrior: boolean;
}) {
  return (
    <div className="flex items-baseline px-4 py-3 bg-blue-700 text-white font-bold">
      <span className="text-sm flex-1">{label}</span>
      <span className="text-sm tabular-nums w-36 text-right">{formatPaise(paise)}</span>
      {showPrior && (
        <span className="text-sm tabular-nums text-blue-200 w-36 text-right">{amount(prior)}</span>
      )}
    </div>
  );
}

function LoadingSpinner() {
  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      <div className="h-6 bg-white/[0.08] rounded w-64 animate-pulse" />
      <div className="h-10 bg-[#F1F5F9] rounded w-64 animate-pulse" />
      <div className="grid grid-cols-2 gap-6">
        <StatementSkeleton sections={2} rowsPerSection={3} />
        <StatementSkeleton sections={2} rowsPerSection={3} />
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function ScheduleIIIPage() {
  const [fyIndex, setFyIndex] = useState(0);
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState<string>("all");
  const [data, setData] = useState<ScheduleData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fy = FY_OPTIONS[fyIndex];

  // Load clients once
  useEffect(() => {
    const sb = getSupabaseClient();
    getFirmId()
      .then(async (fid) => {
        const { data: cls } = await sb
          .from("clients")
          .select("id, client_name")
          .eq("firm_id", fid)
          .order("client_name");
        setClients(((cls ?? []) as { id: string; client_name: string }[])
          .map((c) => ({ id: c.id, name: c.client_name })));
      })
      .catch(() => {});
  }, []);

  const loadData = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchScheduleData(clientId === "all" ? null : clientId, fy.start, fy.end)
      .then(setData)
      .catch((e: Error) => setError(e.message ?? "Failed to load data"))
      .finally(() => setLoading(false));
  }, [clientId, fy.start, fy.end]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const pl = data?.profitAndLoss;
  const bs = data?.balanceSheet;
  const isBalanced = bs?.isBalanced ?? false;
  // Whether there IS a preceding period, decided by the document rather than by
  // whether a number happens to be present. Schedule III General Instructions
  // para 5 requires comparatives for all items and excepts only a company's
  // first financial statements after incorporation; where the exception
  // applies, the column is absent rather than blank, because a blank column
  // reads as nil.
  const showPrior = data?.comparatives?.present ?? false;
  const priorLabel = showPrior && data?.comparatives.period?.fy_end
    ? `As at 31 Mar ${data.comparatives.period.fy_end.slice(0, 4)}`
    : null;

  if (loading) return <LoadingSpinner />;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6 print:p-2 print:space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3 print:hidden">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft size={18} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Schedule III — Financial Statements</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            As per Companies Act 2013, Schedule III — {fy.label}
          </p>
        </div>
      </div>

      {/* Print heading */}
      <div className="hidden print:block text-center mb-4">
        <h1 className="text-2xl font-bold">Schedule III Financial Statements</h1>
        <p className="text-sm text-[#475569] mt-1">As per Companies Act 2013, Schedule III | {fy.label}</p>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap gap-4 items-end print:hidden">
        <div>
          <label className="block text-xs text-[#64748B] mb-1">Financial Year</label>
          <select
            value={fyIndex}
            onChange={(e) => setFyIndex(Number(e.target.value))}
            className="px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {FY_OPTIONS.map((f, i) => (
              <option key={f.label} value={i}>{f.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-[#64748B] mb-1">Client</label>
          <div className="min-w-[200px]">
            <ClientLookup
              clients={clients}
              value={clientId === "all" ? "" : clientId}
              onChange={(id) => setClientId(id || "all")}
              clearable
              placeholder="All Clients"
              ariaLabel="Client"
            />
          </div>
        </div>
        <button
          onClick={() => window.print()}
          className="flex items-center gap-2 px-4 py-1.5 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
        >
          <Printer size={15} /> Print
        </button>
        <button
          onClick={() => {
            if (!data) return;
            // The export carries the comparative column too. A workbook a CA
            // hands to an auditor with one column is the same defect as a
            // one-column statement on screen — Schedule III General
            // Instructions para 5 applies to what is exported, not to what is
            // displayed.
            const priorHead = data.comparatives.present && data.comparatives.period?.fy_end
              ? `Prior (FY ending ${data.comparatives.period.fy_end.slice(0, 4)})`
              : null;
            const rupees = (paise: number | null | undefined) =>
              paise === null || paise === undefined ? "" : (paise / 100).toFixed(2);
            const row = (section: string, item: string, paise?: number | null,
                         prior?: number | null): Record<string, string> => {
              const r: Record<string, string> = {
                Section: section, Item: item,
                Amount: paise === undefined ? "" : rupees(paise),
              };
              if (priorHead) r[priorHead] = prior === undefined ? "" : rupees(prior);
              return r;
            };
            const rows: Record<string, string>[] = [];
            rows.push(row("BALANCE SHEET", ""));
            for (const sec of data.balanceSheet.equityAndLiabilities) {
              rows.push(row(sec.heading, ""));
              for (const l of sec.lines) rows.push(row("", l.label, l.paise, l.prior_paise));
              rows.push(row("", sec.totalLabel ?? "Total", sec.total_paise, sec.prior_total_paise));
            }
            rows.push(row("ASSETS", ""));
            for (const sec of data.balanceSheet.assets) {
              rows.push(row(sec.heading, ""));
              for (const l of sec.lines) rows.push(row("", l.label, l.paise, l.prior_paise));
              rows.push(row("", sec.totalLabel ?? "Total", sec.total_paise, sec.prior_total_paise));
            }
            rows.push(row("PROFIT & LOSS", ""));
            for (const sec of [...data.profitAndLoss.revenue, ...data.profitAndLoss.expenses]) {
              rows.push(row(sec.heading, ""));
              for (const l of sec.lines) rows.push(row("", l.label, l.paise, l.prior_paise));
              rows.push(row("", sec.totalLabel ?? "Total", sec.total_paise, sec.prior_total_paise));
            }
            rows.push(row("Summary", "Profit Before Tax",
                          data.profitAndLoss.profitBeforeTax, data.profitAndLoss.profitBeforeTaxPrior));
            rows.push(row("Summary", "Tax Expense",
                          data.profitAndLoss.taxExpense, data.profitAndLoss.taxExpensePrior));
            rows.push(row("Summary", "Profit After Tax",
                          data.profitAndLoss.profitAfterTax, data.profitAndLoss.profitAfterTaxPrior));
            const ws = XLSX.utils.json_to_sheet(rows);
            const wb = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(wb, ws, "Schedule III");
            XLSX.writeFile(wb, `schedule_iii_${fy.label}.xlsx`);
          }}
          disabled={!data}
          className="flex items-center gap-2 px-4 py-1.5 text-sm border border-[#E2E8F0] text-[#334155] rounded-md hover:bg-[#F8FAFC] transition-colors disabled:opacity-40"
        >
          <Download size={15} /> Export Excel
        </button>
      </div>

      {error && (
        <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm flex gap-2 items-center">
          <AlertTriangle size={16} /> {error}
        </div>
      )}

      {data && (
        <>
          {/* ── BALANCE SHEET ── */}
          <Card className="print:shadow-none print:border-gray-300">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">
                Balance Sheet as at 31 March {Number(fy.start.split("-")[0]) + 1}
              </CardTitle>
              <p className="text-xs text-[#64748B]">(Companies Act 2013, Schedule III, Part I)</p>
            </CardHeader>
            <CardContent className="pb-4 p-0">
              <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-gray-200">
                {/* Equity & Liabilities */}
                <div>
                  <div className="px-4 py-3 border-b border-[#E2E8F0] bg-[#F1F5F9]">
                    <p className="text-xs font-bold text-[#1E293B] uppercase tracking-wider">EQUITY AND LIABILITIES</p>
                  </div>
                  <ColumnHeads current={`As at 31 Mar ${Number(fy.start.split("-")[0]) + 1}`}
                               prior={priorLabel} />
                  {bs?.equityAndLiabilities.map((sec) => (
                    <SectionTable key={sec.heading} section={sec} showPrior={showPrior} />
                  ))}
                  <GrandTotal label="TOTAL EQUITY AND LIABILITIES"
                              paise={bs?.totalEquityLiab ?? 0}
                              prior={bs?.totalEquityLiabPrior ?? null}
                              showPrior={showPrior} />
                </div>

                {/* Assets */}
                <div>
                  <div className="px-4 py-3 border-b border-[#E2E8F0] bg-[#F1F5F9]">
                    <p className="text-xs font-bold text-[#1E293B] uppercase tracking-wider">ASSETS</p>
                  </div>
                  <ColumnHeads current={`As at 31 Mar ${Number(fy.start.split("-")[0]) + 1}`}
                               prior={priorLabel} />
                  {bs?.assets.map((sec) => (
                    <SectionTable key={sec.heading} section={sec} showPrior={showPrior} />
                  ))}
                  <GrandTotal label="TOTAL ASSETS"
                              paise={bs?.totalAssets ?? 0}
                              prior={bs?.totalAssetsPrior ?? null}
                              showPrior={showPrior} />
                </div>
              </div>

              {/* Para 5's own exception, stated rather than left as an empty
                  column a reader would take for nil. */}
              {!showPrior && data?.comparatives?.reason && (
                <div className="mx-4 mt-3 px-4 py-2.5 rounded-lg text-[11px] bg-[#F8FAFC] border border-[#E2E8F0] text-[#64748B] flex items-start gap-2">
                  <AlertTriangle size={13} className="text-[#94A3B8] flex-shrink-0 mt-0.5" />
                  <span>
                    <span className="font-medium text-[#334155]">No comparative column.</span>{" "}
                    {data.comparatives.reason}
                  </span>
                </div>
              )}

              {/* Balance check indicator */}
              {(bs?.totalAssets ?? 0) > 0 && (
                <div className={`mx-4 mt-3 mb-4 px-4 py-2.5 rounded-lg text-xs flex items-center gap-2 font-medium print:hidden ${isBalanced ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-700"}`}>
                  {isBalanced
                    ? "Balance Sheet balances — Total Assets = Total Equity & Liabilities"
                    : <><AlertTriangle size={14} /> Balance Sheet does not balance — verify opening entries and retained earnings</>}
                </div>
              )}
            </CardContent>
          </Card>

          {/* ── PROFIT & LOSS ── */}
          <Card className="print:shadow-none print:border-gray-300">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">
                Statement of Profit & Loss for the year ended 31 March {Number(fy.start.split("-")[0]) + 1}
              </CardTitle>
              <p className="text-xs text-[#64748B]">(Companies Act 2013, Schedule III, Part II)</p>
            </CardHeader>
            <CardContent className="pb-4 p-0">
              <ColumnHeads
                current={`Year ended 31 Mar ${Number(fy.start.split("-")[0]) + 1}`}
                prior={showPrior && data?.comparatives.period?.fy_end
                  ? `Year ended 31 Mar ${data.comparatives.period.fy_end.slice(0, 4)}`
                  : null} />
              {/* Revenue */}
              {pl?.revenue.map((sec) => (
                <SectionTable key={sec.heading} section={sec} showPrior={showPrior} />
              ))}

              {/* Expenses */}
              {pl?.expenses.map((sec) => (
                <SectionTable key={sec.heading} section={sec} showPrior={showPrior} />
              ))}

              {/* Profit summary */}
              <div className="mx-4 mb-4 mt-2 border border-[#E2E8F0] rounded-lg overflow-hidden">
                <div className="flex items-baseline px-4 py-2.5 bg-[#F8FAFC] border-b border-[#E2E8F0]">
                  <span className="text-sm font-semibold text-[#1E293B] flex-1">Profit Before Tax (I - II)</span>
                  <span className={`text-sm tabular-nums font-bold w-36 text-right ${(pl?.profitBeforeTax ?? 0) >= 0 ? "text-green-700" : "text-red-700"}`}>
                    {amount(pl?.profitBeforeTax ?? 0)}
                  </span>
                  {showPrior && (
                    <span className="text-sm tabular-nums text-[#64748B] w-36 text-right">
                      {amount(pl?.profitBeforeTaxPrior)}
                    </span>
                  )}
                </div>
                <div className="flex items-baseline px-4 py-2.5 border-b border-[#E2E8F0]">
                  <span className="text-sm text-[#334155] pl-4 flex-1">Tax Expense (Current + Deferred)</span>
                  <span className="text-sm tabular-nums text-[#0F172A] w-36 text-right">{amount(pl?.taxExpense ?? 0)}</span>
                  {showPrior && (
                    <span className="text-sm tabular-nums text-[#64748B] w-36 text-right">
                      {amount(pl?.taxExpensePrior)}
                    </span>
                  )}
                </div>
                <GrandTotal label="Profit After Tax (PAT)"
                            paise={pl?.profitAfterTax ?? 0}
                            prior={pl?.profitAfterTaxPrior ?? null}
                            showPrior={showPrior} />
              </div>
            </CardContent>
          </Card>

          {/* Statutory note */}
          <p className="text-xs text-[#94A3B8] text-center print:mt-6">
            Prepared as per Schedule III to the Companies Act, 2013. All figures in Indian Rupees (INR).
            This statement is for internal review only — CA sign-off required before filing with MCA/ROC.
          </p>
        </>
      )}
    </div>
  );
}
