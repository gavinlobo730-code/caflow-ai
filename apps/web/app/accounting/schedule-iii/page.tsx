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
import { formatPaise } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";

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

interface AccountRow {
  id: string;
  account_name: string;
  account_type: string; // Asset | Liability | Equity | Revenue | Expense
  account_subtype: string | null;
}

interface LineItem {
  label: string;
  paise: number;
  indent?: boolean;
}

interface ScheduleSection {
  heading: string;
  lines: LineItem[];
  total_paise: number;
  totalLabel?: string;
}

// ─── Schedule III mapping helpers ────────────────────────────────────────────

/**
 * Map account_subtype (or fallback to account_type) to Schedule III Balance Sheet bucket.
 * Companies Act 2013, Schedule III, Part I
 */
function bsBucket(acc: AccountRow): string | null {
  const sub = (acc.account_subtype ?? "").toLowerCase();
  const type = acc.account_type.toLowerCase();

  if (type === "equity") {
    if (sub.includes("share capital") || sub.includes("capital")) return "Share Capital";
    return "Reserves & Surplus";
  }
  if (type === "liability") {
    if (sub.includes("long term") || sub.includes("term loan") || sub.includes("debenture")) return "Long Term Borrowings";
    if (sub.includes("deferred tax")) return "Deferred Tax Liability";
    if (sub.includes("trade payable") || sub.includes("creditor")) return "Trade Payables";
    if (sub.includes("short term") || sub.includes("overdraft") || sub.includes("cc limit")) return "Short Term Borrowings";
    return "Other Current Liabilities";
  }
  if (type === "asset") {
    if (sub.includes("fixed asset") || sub.includes("tangible") || sub.includes("plant") || sub.includes("machinery") || sub.includes("furniture") || sub.includes("building") || sub.includes("vehicle")) return "Tangible Fixed Assets";
    if (sub.includes("intangible") || sub.includes("goodwill") || sub.includes("software")) return "Intangible Fixed Assets";
    if (sub.includes("long term investment") || sub.includes("investment")) return "Long Term Investments";
    if (sub.includes("inventor") || sub.includes("stock")) return "Inventories";
    if (sub.includes("trade receivable") || sub.includes("debtor")) return "Trade Receivables";
    if (sub.includes("cash") || sub.includes("bank")) return "Cash & Cash Equivalents";
    if (sub.includes("short term loan") || sub.includes("advance")) return "Short Term Loans & Advances";
    return "Other Current Assets";
  }
  return null;
}

/**
 * Map account_subtype to Schedule III P&L bucket.
 * Companies Act 2013, Schedule III, Part II
 */
function plBucket(acc: AccountRow): string | null {
  const sub = (acc.account_subtype ?? "").toLowerCase();
  const type = acc.account_type.toLowerCase();

  if (type === "revenue") {
    if (sub.includes("other income") || sub.includes("interest income") || sub.includes("dividend")) return "Other Income";
    return "Revenue from Operations";
  }
  if (type === "expense") {
    if (sub.includes("material") || sub.includes("cost of goods") || sub.includes("purchase") || sub.includes("raw material")) return "Cost of Materials";
    if (sub.includes("employee") || sub.includes("salary") || sub.includes("wages") || sub.includes("staff")) return "Employee Benefit Expense";
    if (sub.includes("finance") || sub.includes("interest expense") || sub.includes("bank charge")) return "Finance Costs";
    if (sub.includes("depreciation") || sub.includes("amortisation") || sub.includes("amortization")) return "Depreciation & Amortisation";
    if (sub.includes("tax") || sub.includes("income tax") || sub.includes("deferred tax")) return "Tax Expense";
    return "Other Expenses";
  }
  return null;
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
  };
  profitAndLoss: {
    revenue: ScheduleSection[];
    expenses: ScheduleSection[];
    totalRevenue: number;
    totalExpenses: number;
    profitBeforeTax: number;
    taxExpense: number;
    profitAfterTax: number;
  };
}

async function fetchScheduleData(
  firmId: string,
  clientId: string | null,
  fyStart: string,
  fyEnd: string
): Promise<ScheduleData> {
  const sb = getSupabaseClient();

  // Fetch accounts — chart_of_accounts for the firm
  const accQuery = sb
    .from("accounts")
    .select("id, account_name, account_type, account_subtype")
    .eq("firm_id", firmId);
  if (clientId) accQuery.eq("client_id", clientId);

  const { data: accounts, error: accErr } = await accQuery;
  if (accErr) throw new Error(accErr.message);

  // Fetch all posted journal entry lines within FY date range
  const { data: lines, error: lineErr } = await sb
    .from("journal_entry_lines")
    .select("account_id, debit_paise, credit_paise, journal_entries!inner(firm_id, entry_date, status)")
    .eq("journal_entries.firm_id", firmId)
    .eq("journal_entries.status", "posted")
    .gte("journal_entries.entry_date", fyStart)
    .lte("journal_entries.entry_date", fyEnd);
  if (lineErr) throw new Error(lineErr.message);

  // Aggregate net balance per account in integer paise — no floating point
  const balMap = new Map<string, number>();
  for (const line of (lines ?? [])) {
    const prev = balMap.get(line.account_id) ?? 0;
    // Debit increases Assets/Expenses; Credit increases Liabilities/Equity/Revenue
    balMap.set(line.account_id, prev + (line.debit_paise ?? 0) - (line.credit_paise ?? 0));
  }

  // Group accounts into Schedule III buckets
  const bsBuckets = new Map<string, number>();
  const plBuckets = new Map<string, number>();

  for (const acc of (accounts ?? [])) {
    const raw = balMap.get(acc.id) ?? 0;
    const type = acc.account_type.toLowerCase();

    if (["asset", "liability", "equity"].includes(type)) {
      const bucket = bsBucket(acc);
      if (!bucket) continue;
      // Normalise: Assets positive = debit; Liabilities/Equity positive = credit
      const signed = (type === "liability" || type === "equity") ? -raw : raw;
      bsBuckets.set(bucket, (bsBuckets.get(bucket) ?? 0) + signed);
    } else if (["revenue", "expense"].includes(type)) {
      const bucket = plBucket(acc);
      if (!bucket) continue;
      // Revenue positive = credit balance; Expense positive = debit balance
      const signed = type === "revenue" ? -raw : raw;
      plBuckets.set(bucket, (plBuckets.get(bucket) ?? 0) + signed);
    }
  }

  const get = (map: Map<string, number>, key: string) => map.get(key) ?? 0;
  const toLine = (map: Map<string, number>, key: string): LineItem => ({
    label: key,
    paise: get(map, key),
    indent: true,
  });

  // ── Balance Sheet: Equity & Liabilities ────────────────────────────────────
  const shareCapPaise = get(bsBuckets, "Share Capital");
  const reservesPaise = get(bsBuckets, "Reserves & Surplus");
  const shareholdersFunds = shareCapPaise + reservesPaise;

  const ltbPaise = get(bsBuckets, "Long Term Borrowings");
  const dtlPaise = get(bsBuckets, "Deferred Tax Liability");
  const nonCurrentLiab = ltbPaise + dtlPaise;

  const stbPaise = get(bsBuckets, "Short Term Borrowings");
  const tpPaise = get(bsBuckets, "Trade Payables");
  const oclPaise = get(bsBuckets, "Other Current Liabilities");
  const currentLiab = stbPaise + tpPaise + oclPaise;

  const totalEquityLiab = shareholdersFunds + nonCurrentLiab + currentLiab;

  const equityAndLiabilities: ScheduleSection[] = [
    {
      heading: "I. Shareholders' Funds",
      lines: [
        { label: "Share Capital", paise: shareCapPaise, indent: true },
        { label: "Reserves & Surplus", paise: reservesPaise, indent: true },
      ],
      total_paise: shareholdersFunds,
      totalLabel: "Total Shareholders' Funds",
    },
    {
      heading: "II. Non-Current Liabilities",
      lines: [
        toLine(bsBuckets, "Long Term Borrowings"),
        toLine(bsBuckets, "Deferred Tax Liability"),
      ],
      total_paise: nonCurrentLiab,
      totalLabel: "Total Non-Current Liabilities",
    },
    {
      heading: "III. Current Liabilities",
      lines: [
        toLine(bsBuckets, "Short Term Borrowings"),
        toLine(bsBuckets, "Trade Payables"),
        toLine(bsBuckets, "Other Current Liabilities"),
      ],
      total_paise: currentLiab,
      totalLabel: "Total Current Liabilities",
    },
  ];

  // ── Balance Sheet: Assets ───────────────────────────────────────────────────
  const tangiblePaise = get(bsBuckets, "Tangible Fixed Assets");
  const intangiblePaise = get(bsBuckets, "Intangible Fixed Assets");
  const ltInvPaise = get(bsBuckets, "Long Term Investments");
  const fixedAssets = tangiblePaise + intangiblePaise;
  const nonCurrentAssets = fixedAssets + ltInvPaise;

  const invPaise = get(bsBuckets, "Inventories");
  const trPaise = get(bsBuckets, "Trade Receivables");
  const cashPaise = get(bsBuckets, "Cash & Cash Equivalents");
  const stlaPaise = get(bsBuckets, "Short Term Loans & Advances");
  const ocaPaise = get(bsBuckets, "Other Current Assets");
  const currentAssets = invPaise + trPaise + cashPaise + stlaPaise + ocaPaise;
  const totalAssets = nonCurrentAssets + currentAssets;

  const assets: ScheduleSection[] = [
    {
      heading: "I. Non-Current Assets",
      lines: [
        { label: "Fixed Assets — Tangible", paise: tangiblePaise, indent: true },
        { label: "Fixed Assets — Intangible", paise: intangiblePaise, indent: true },
        { label: "Long Term Investments", paise: ltInvPaise, indent: true },
      ],
      total_paise: nonCurrentAssets,
      totalLabel: "Total Non-Current Assets",
    },
    {
      heading: "II. Current Assets",
      lines: [
        toLine(bsBuckets, "Inventories"),
        toLine(bsBuckets, "Trade Receivables"),
        toLine(bsBuckets, "Cash & Cash Equivalents"),
        toLine(bsBuckets, "Short Term Loans & Advances"),
        toLine(bsBuckets, "Other Current Assets"),
      ],
      total_paise: currentAssets,
      totalLabel: "Total Current Assets",
    },
  ];

  // ── Profit & Loss Statement ─────────────────────────────────────────────────
  const revOpsPaise = get(plBuckets, "Revenue from Operations");
  const otherIncomePaise = get(plBuckets, "Other Income");
  const totalRevenue = revOpsPaise + otherIncomePaise;

  const materialsPaise = get(plBuckets, "Cost of Materials");
  const empPaise = get(plBuckets, "Employee Benefit Expense");
  const finCostPaise = get(plBuckets, "Finance Costs");
  const deprPaise = get(plBuckets, "Depreciation & Amortisation");
  const otherExpPaise = get(plBuckets, "Other Expenses");
  const taxExpPaise = get(plBuckets, "Tax Expense");

  const operatingExpenses = materialsPaise + empPaise + finCostPaise + deprPaise + otherExpPaise;
  const profitBeforeTax = totalRevenue - operatingExpenses;
  const profitAfterTax = profitBeforeTax - taxExpPaise;

  const revenue: ScheduleSection[] = [
    {
      heading: "I. Revenue",
      lines: [
        { label: "Revenue from Operations", paise: revOpsPaise, indent: true },
        { label: "Other Income", paise: otherIncomePaise, indent: true },
      ],
      total_paise: totalRevenue,
      totalLabel: "Total Revenue (I)",
    },
  ];

  const expenses: ScheduleSection[] = [
    {
      heading: "II. Expenses",
      lines: [
        { label: "Cost of Materials Consumed", paise: materialsPaise, indent: true },
        { label: "Employee Benefit Expense", paise: empPaise, indent: true },
        { label: "Finance Costs", paise: finCostPaise, indent: true },
        { label: "Depreciation & Amortisation Expense", paise: deprPaise, indent: true },
        { label: "Other Expenses", paise: otherExpPaise, indent: true },
      ],
      total_paise: operatingExpenses,
      totalLabel: "Total Expenses (II)",
    },
  ];

  return {
    balanceSheet: { equityAndLiabilities, assets, totalEquityLiab, totalAssets },
    profitAndLoss: { revenue, expenses, totalRevenue, totalExpenses: operatingExpenses, profitBeforeTax, taxExpense: taxExpPaise, profitAfterTax },
  };
}

// ─── UI components ────────────────────────────────────────────────────────────

function SectionTable({ section }: { section: ScheduleSection }) {
  return (
    <div className="mb-4">
      <div className="bg-gray-50 px-4 py-2 border-b border-gray-200">
        <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">{section.heading}</p>
      </div>
      {section.lines.map((line) => (
        <div key={line.label} className="flex justify-between px-4 py-2 border-b border-gray-100 last:border-b-0">
          <span className={`text-sm text-gray-700 ${line.indent ? "pl-4" : ""}`}>{line.label}</span>
          <span className="text-sm tabular-nums text-gray-900 font-medium">
            {line.paise === 0 ? "—" : line.paise < 0
              ? `(${formatPaise(Math.abs(line.paise))})`
              : formatPaise(line.paise)}
          </span>
        </div>
      ))}
      <div className="flex justify-between px-4 py-2.5 bg-blue-50 font-semibold">
        <span className="text-sm text-blue-900">{section.totalLabel ?? `Total`}</span>
        <span className="text-sm tabular-nums text-blue-700">{formatPaise(section.total_paise)}</span>
      </div>
    </div>
  );
}

function LoadingSpinner() {
  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4 animate-pulse">
      <div className="h-6 bg-gray-200 rounded w-64" />
      <div className="h-10 bg-gray-100 rounded w-64" />
      <div className="grid grid-cols-2 gap-6">
        <div className="h-96 bg-gray-100 rounded-xl" />
        <div className="h-96 bg-gray-100 rounded-xl" />
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
          .select("id, name")
          .eq("firm_id", fid)
          .order("name");
        setClients((cls ?? []) as Client[]);
      })
      .catch(() => {});
  }, []);

  const loadData = useCallback(() => {
    setLoading(true);
    setError(null);
    getFirmId()
      .then((fid) =>
        fetchScheduleData(fid, clientId === "all" ? null : clientId, fy.start, fy.end)
      )
      .then(setData)
      .catch((e: Error) => setError(e.message ?? "Failed to load data"))
      .finally(() => setLoading(false));
  }, [clientId, fy.start, fy.end]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const pl = data?.profitAndLoss;
  const bs = data?.balanceSheet;
  const isBalanced = bs ? bs.totalAssets === bs.totalEquityLiab : false;

  if (loading) return <LoadingSpinner />;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6 print:p-2 print:space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3 print:hidden">
        <Link href="/accounting" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft size={18} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Schedule III — Financial Statements</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            As per Companies Act 2013, Schedule III — {fy.label}
          </p>
        </div>
      </div>

      {/* Print heading */}
      <div className="hidden print:block text-center mb-4">
        <h1 className="text-2xl font-bold">Schedule III Financial Statements</h1>
        <p className="text-sm text-gray-600 mt-1">As per Companies Act 2013, Schedule III | {fy.label}</p>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap gap-4 items-end print:hidden">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Financial Year</label>
          <select
            value={fyIndex}
            onChange={(e) => setFyIndex(Number(e.target.value))}
            className="px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {FY_OPTIONS.map((f, i) => (
              <option key={f.label} value={i}>{f.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Client</label>
          <select
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            className="px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">All Clients</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
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
            const rows: Record<string, string>[] = [];
            rows.push({ Section: "BALANCE SHEET", Item: "", Amount: "" });
            for (const sec of data.balanceSheet.equityAndLiabilities) {
              rows.push({ Section: sec.heading, Item: "", Amount: "" });
              for (const l of sec.lines) rows.push({ Section: "", Item: l.label, Amount: (l.paise / 100).toFixed(2) });
              rows.push({ Section: "", Item: sec.totalLabel ?? "Total", Amount: (sec.total_paise / 100).toFixed(2) });
            }
            rows.push({ Section: "ASSETS", Item: "", Amount: "" });
            for (const sec of data.balanceSheet.assets) {
              rows.push({ Section: sec.heading, Item: "", Amount: "" });
              for (const l of sec.lines) rows.push({ Section: "", Item: l.label, Amount: (l.paise / 100).toFixed(2) });
              rows.push({ Section: "", Item: sec.totalLabel ?? "Total", Amount: (sec.total_paise / 100).toFixed(2) });
            }
            rows.push({ Section: "PROFIT & LOSS", Item: "", Amount: "" });
            for (const sec of [...data.profitAndLoss.revenue, ...data.profitAndLoss.expenses]) {
              rows.push({ Section: sec.heading, Item: "", Amount: "" });
              for (const l of sec.lines) rows.push({ Section: "", Item: l.label, Amount: (l.paise / 100).toFixed(2) });
              rows.push({ Section: "", Item: sec.totalLabel ?? "Total", Amount: (sec.total_paise / 100).toFixed(2) });
            }
            rows.push({ Section: "Summary", Item: "Profit Before Tax", Amount: (data.profitAndLoss.profitBeforeTax / 100).toFixed(2) });
            rows.push({ Section: "Summary", Item: "Tax Expense", Amount: (data.profitAndLoss.taxExpense / 100).toFixed(2) });
            rows.push({ Section: "Summary", Item: "Profit After Tax", Amount: (data.profitAndLoss.profitAfterTax / 100).toFixed(2) });
            const ws = XLSX.utils.json_to_sheet(rows);
            const wb = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(wb, ws, "Schedule III");
            XLSX.writeFile(wb, `schedule_iii_${fy.label}.xlsx`);
          }}
          disabled={!data}
          className="flex items-center gap-2 px-4 py-1.5 text-sm border border-gray-200 text-gray-700 rounded-md hover:bg-gray-50 transition-colors disabled:opacity-40"
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
              <p className="text-xs text-gray-500">(Companies Act 2013, Schedule III, Part I)</p>
            </CardHeader>
            <CardContent className="pb-4 p-0">
              <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-gray-200">
                {/* Equity & Liabilities */}
                <div>
                  <div className="px-4 py-3 border-b border-gray-200 bg-gray-100">
                    <p className="text-xs font-bold text-gray-800 uppercase tracking-wider">EQUITY AND LIABILITIES</p>
                  </div>
                  {bs?.equityAndLiabilities.map((sec) => (
                    <SectionTable key={sec.heading} section={sec} />
                  ))}
                  <div className="flex justify-between px-4 py-3 bg-blue-700 text-white font-bold">
                    <span className="text-sm">TOTAL EQUITY AND LIABILITIES</span>
                    <span className="text-sm tabular-nums">{formatPaise(bs?.totalEquityLiab ?? 0)}</span>
                  </div>
                </div>

                {/* Assets */}
                <div>
                  <div className="px-4 py-3 border-b border-gray-200 bg-gray-100">
                    <p className="text-xs font-bold text-gray-800 uppercase tracking-wider">ASSETS</p>
                  </div>
                  {bs?.assets.map((sec) => (
                    <SectionTable key={sec.heading} section={sec} />
                  ))}
                  <div className="flex justify-between px-4 py-3 bg-blue-700 text-white font-bold">
                    <span className="text-sm">TOTAL ASSETS</span>
                    <span className="text-sm tabular-nums">{formatPaise(bs?.totalAssets ?? 0)}</span>
                  </div>
                </div>
              </div>

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
              <p className="text-xs text-gray-500">(Companies Act 2013, Schedule III, Part II)</p>
            </CardHeader>
            <CardContent className="pb-4 p-0">
              {/* Revenue */}
              {pl?.revenue.map((sec) => (
                <SectionTable key={sec.heading} section={sec} />
              ))}

              {/* Expenses */}
              {pl?.expenses.map((sec) => (
                <SectionTable key={sec.heading} section={sec} />
              ))}

              {/* Profit summary */}
              <div className="mx-4 mb-4 mt-2 border border-gray-200 rounded-lg overflow-hidden">
                <div className="flex justify-between px-4 py-2.5 bg-gray-50 border-b border-gray-200">
                  <span className="text-sm font-semibold text-gray-800">Profit Before Tax (I - II)</span>
                  <span className={`text-sm tabular-nums font-bold ${(pl?.profitBeforeTax ?? 0) >= 0 ? "text-green-700" : "text-red-700"}`}>
                    {(pl?.profitBeforeTax ?? 0) < 0
                      ? `(${formatPaise(Math.abs(pl?.profitBeforeTax ?? 0))})`
                      : formatPaise(pl?.profitBeforeTax ?? 0)}
                  </span>
                </div>
                <div className="flex justify-between px-4 py-2.5 border-b border-gray-200">
                  <span className="text-sm text-gray-700 pl-4">Tax Expense (Current + Deferred)</span>
                  <span className="text-sm tabular-nums text-gray-900">{formatPaise(pl?.taxExpense ?? 0)}</span>
                </div>
                <div className="flex justify-between px-4 py-3 bg-blue-700 text-white font-bold">
                  <span className="text-sm">Profit After Tax (PAT)</span>
                  <span className="text-sm tabular-nums">
                    {(pl?.profitAfterTax ?? 0) < 0
                      ? `(${formatPaise(Math.abs(pl?.profitAfterTax ?? 0))})`
                      : formatPaise(pl?.profitAfterTax ?? 0)}
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Statutory note */}
          <p className="text-xs text-gray-400 text-center print:mt-6">
            Prepared as per Schedule III to the Companies Act, 2013. All figures in Indian Rupees (INR).
            This statement is for internal review only — CA sign-off required before filing with MCA/ROC.
          </p>
        </>
      )}
    </div>
  );
}
