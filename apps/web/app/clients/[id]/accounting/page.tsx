"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Plus, RefreshCw, Upload, CheckCircle, X, Printer, FileText, Download, Share2 } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { formatPaise, formatMoney } from "@/lib/services/formatting";
import { DataTable, downloadCsv } from "@/components/ui/data-table";
import { toCsv } from "@/lib/table/process";
import { AccountLookup } from "@/components/lookups/AccountLookup";
import type { Column, FilterDef } from "@/lib/table/types";
import { getFirmId } from "@/lib/data/getFirmId";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { api } from "@/lib/api";
import { cachedReport, reportKey, clearReports } from "@/lib/accounting/reportCache";
import { writeTimelineEvent } from "@/lib/services/timeline";
import { todayLocalISO } from "@/lib/dateMath";
import {
  parseCSV,
  importBankStatement,
  getBankStatements,
  getBankTransactions,
  type BankStatement,
  type BankTransaction,
} from "@/lib/data/bankStatements";

// ── Tab definitions ────────────────────────────────────────────────────────

type AccountingTab =
  | "dashboard"
  | "coa"
  | "journal"
  | "trial"
  | "pl"
  | "balance-sheet"
  | "cashflow"
  | "banks"
  | "categorize"
  | "post"
  | "approvals"
  | "reconciliation"
  | "reports"
  | "fx-reports";

const TABS: { id: AccountingTab; label: string }[] = [
  { id: "dashboard",     label: "Dashboard" },
  { id: "coa",           label: "Accounts" },
  { id: "journal",       label: "Journal" },
  { id: "trial",         label: "Trial Balance" },
  { id: "pl",            label: "P & L" },
  { id: "balance-sheet", label: "Balance Sheet" },
  { id: "cashflow",      label: "Cash Flow" },
  { id: "banks",         label: "Banks" },
  { id: "categorize",    label: "Categorize" },
  { id: "post",          label: "Post" },
  { id: "approvals",     label: "Approvals" },
  { id: "reconciliation",label: "Reconciliation" },
  { id: "reports",       label: "Reports" },
  { id: "fx-reports",    label: "FX Reports" },
];

// ── Shared types ───────────────────────────────────────────────────────────

interface Account {
  id: string;
  account_code: string;
  account_name: string;
  account_type: "Asset" | "Liability" | "Equity" | "Revenue" | "Expense";
  account_subtype: string | null;
  is_active: boolean;
  client_id: string | null;
}

interface JournalLine {
  account_id: string;
  debit_paise: number;
  credit_paise: number;
  narration: string;
}

interface JournalEntry {
  id: string;
  entry_date: string;
  reference_no: string | null;
  narration: string;
  entry_type: string;
  is_posted: boolean;
  lines: { account_id: string; debit_paise: number; credit_paise: number; narration: string | null }[];
}

// Backend-computed ledger row (running balance comes from the engine, not React).
interface LedgerLine {
  entry_id: string;
  entry_date: string;
  narration: string | null;
  reference_no: string | null;
  debit_paise: number;
  credit_paise: number;
  running_balance_paise: number;
  is_debit: boolean;
}
interface LedgerView {
  account_name: string;
  opening_balance_paise: number;
  opening_is_debit: boolean;
  closing_balance_paise: number;
  closing_is_debit: boolean;
  total_debit_paise: number;
  total_credit_paise: number;
  lines: LedgerLine[];
}

interface TrialRow {
  account_id: string;
  account_code: string;
  account_name: string;
  account_type: string;
  total_debit_paise: number;
  total_credit_paise: number;
}

// Backend trial-balance payload (authoritative totals computed server-side).
interface TBApiData {
  lines: TrialRow[];
  total_debit_paise: number;
  total_credit_paise: number;
  is_balanced: boolean;
}

// Aggregated balance per account (from journal lines)
interface AccountBalance {
  account_id: string;
  account_code: string;
  account_name: string;
  account_type: string;
  account_subtype: string | null;
  net_paise: number; // positive = normal balance side
}

// ── Helpers ────────────────────────────────────────────────────────────────

// Shared money formatter (paise → ₹). Preserves the sign so a negative amount
// never renders as positive (audit M15). Ledger Dr/Cr callers pass abs values.
function fmt(paise: number): string {
  return paise === 0 ? "—" : formatPaise(paise);
}

function fyDateRange(fy: string): { start: string; end: string } {
  const [startYear] = fy.split("-");
  const y = parseInt(startYear, 10);
  return { start: `${y}-04-01`, end: `${y + 1}-03-31` };
}

// "2026-27" shifted by -1 → "2025-26". Used for the Schedule III comparative
// (prior year) column — Companies Act 2013, Schedule III requires the
// previous year's figures alongside the current year on the P&L/BS face.
function shiftFY(fy: string, delta: number): string {
  const [startYear] = fy.split("-");
  const start = parseInt(startYear, 10) + delta;
  return `${start}-${String(start + 1).slice(-2)}`;
}

// Renders a signed % change cell for the "compare to prior year" columns.
// `prev` undefined/0 with a nonzero `curr` reads as "New" rather than a
// misleading infinite/undefined percentage.
function ChangeCell({ curr, prev }: { curr: number; prev: number | undefined }) {
  if (prev === undefined) return <span className="text-[#CBD5E1]">…</span>;
  if (prev === 0) return curr === 0 ? <span className="text-[#CBD5E1]">—</span> : <span className="text-blue-600 font-medium">New</span>;
  const pct = ((curr - prev) / Math.abs(prev)) * 100;
  if (curr === prev) return <span className="text-[#94A3B8]">—</span>;
  const up = pct > 0;
  return <span className={up ? "text-green-700" : "text-red-700"}>{up ? "+" : ""}{pct.toFixed(1)}%</span>;
}

// Report lines can carry a synthetic id (e.g. "__retained__" for a computed
// Retained Earnings rollup) instead of a real chart-of-accounts id — those
// have no ledger of their own, so drill-down must skip them.
function isDrillableAccount(id?: string): boolean {
  return !!id && !id.startsWith("__");
}

// Schedule III P&L bucket — Companies Act 2013, Schedule III, Part II
function plBucket(type: string, subtype: string | null): string {
  const s = (subtype ?? "").toLowerCase();
  if (type === "Revenue") {
    if (s.includes("other income") || s.includes("non-operating")) return "Other Income";
    return "Revenue from Operations";
  }
  if (type === "Expense") {
    if (s.includes("cost") || s.includes("cogs") || s.includes("purchase") || s.includes("material"))
      return "Cost of Materials Consumed";
    if (s.includes("employee") || s.includes("salary") || s.includes("payroll") || s.includes("wages") || s.includes("staff"))
      return "Employee Benefit Expense";
    if (s.includes("depreciation") || s.includes("amortisation") || s.includes("amortization"))
      return "Depreciation & Amortisation";
    if (s.includes("finance") || s.includes("interest") || s.includes("bank charge") || s.includes("borrowing cost"))
      return "Finance Costs";
    return "Other Expenses";
  }
  return "Other";
}

// Schedule III Balance Sheet bucket — Companies Act 2013, Schedule III, Part I
function bsBucket(type: string, subtype: string | null): string {
  const s = (subtype ?? "").toLowerCase();
  if (type === "Asset") {
    if (s.includes("intangible") || s.includes("goodwill") || s.includes("patent") || s.includes("trademark"))
      return "Intangible Assets";
    if (s.includes("fixed") || s.includes("plant") || s.includes("machinery") || s.includes("building") ||
        s.includes("furniture") || s.includes("vehicle") || s.includes("tangible") || s.includes("equipment"))
      return "Tangible Assets";
    if (s.includes("investment")) return "Non-Current Investments";
    if (s.includes("receivable") || s.includes("debtor")) return "Trade Receivables";
    if (s.includes("cash") || s.includes("bank")) return "Cash & Cash Equivalents";
    if (s.includes("inventor") || s.includes("stock")) return "Inventories";
    if (s.includes("prepaid") || s.includes("advance")) return "Short-term Loans & Advances";
    return "Other Current Assets";
  }
  if (type === "Liability") {
    if (s.includes("long term") || s.includes("term loan") || s.includes("debenture") || s.includes("mortgage"))
      return "Long-term Borrowings";
    if (s.includes("payable") || s.includes("creditor")) return "Trade Payables";
    if (s.includes("short term") || s.includes("overdraft") || s.includes("cc limit") || s.includes("cash credit"))
      return "Short-term Borrowings";
    if (s.includes("tax") || s.includes("gst") || s.includes("tds") || s.includes("duty"))
      return "Tax Liabilities";
    return "Other Current Liabilities";
  }
  if (type === "Equity") {
    if (s.includes("capital") || s.includes("share")) return "Share Capital";
    return "Reserves & Surplus";
  }
  return "Other";
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function AccountingPage() {
  const { clientId, financialYear } = useClientNav();
  const [tab, setTab] = useState<AccountingTab>("dashboard");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accsLoading, setAccsLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  // Multi-Currency Phase 5 — the FX Reports tab is shown ONLY when multi-currency is
  // active for this client, so an INR-only client sees no added complexity (CLAUDE.md).
  const [mcActive, setMcActive] = useState(false);
  // QuickBooks-style drill-down: set by clicking an amount on Trial Balance,
  // P&L, or the Balance Sheet. Lives outside `tab`/basis/FY state entirely, so
  // opening or closing it never touches the report underneath.
  const [drillDown, setDrillDown] = useState<{ accountId: string } | null>(null);
  const openDrillDown = useCallback((accountId: string) => setDrillDown({ accountId }), []);

  const loadAccounts = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setAccsLoading(true);
    const supabase = getSupabaseClient();
    const { data } = await selectAll(() => supabase
      .from("chart_of_accounts")
      .select("id, account_code, account_name, account_type, account_subtype, is_active, client_id")
      .or(`client_id.eq.${clientId},client_id.is.null`)
      .eq("is_active", true)
      .order("account_code")
      .order("id"));
    setAccounts((data as Account[]) ?? []);
    setAccsLoading(false);
  }, [clientId]);

  useEffect(() => { loadAccounts(); }, [loadAccounts]);

  // Resolve the multi-currency policy for this client (env + firm + client gates).
  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    let cancelled = false;
    (async () => {
      try {
        const res = await api.currencies.policy({ client_id: clientId }) as { success: boolean; data: { active?: boolean } | null };
        if (!cancelled) setMcActive(Boolean(res?.success && res.data?.active));
      } catch { if (!cancelled) setMcActive(false); }
    })();
    return () => { cancelled = true; };
  }, [clientId]);

  const visibleTabs = TABS.filter((t) => t.id !== "fx-reports" || mcActive);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Sub-tab bar */}
      <div className="flex-shrink-0 overflow-x-auto px-6 pt-5 pb-0">
        <div className="flex gap-0.5 bg-[#F8FAFC] rounded-lg p-1 w-fit">
          {visibleTabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap ${
                tab === t.id ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div key={reloadKey} className="flex-1 overflow-y-auto px-6 pb-6 pt-4 min-h-0">
        {tab === "dashboard" && (
          <AccountingDashboard clientId={clientId} financialYear={financialYear} accounts={accounts} onNavigate={setTab} />
        )}
        {tab === "coa" && (
          <ChartOfAccounts accounts={accounts} loading={accsLoading} onRefresh={loadAccounts} />
        )}
        {tab === "journal" && (
          <JournalEntryForm
            accounts={accounts}
            clientId={clientId}
            financialYear={financialYear}
            onPosted={() => { clearReports(clientId); loadAccounts(); setReloadKey((k) => k + 1); }}
          />
        )}
        {tab === "trial" && (
          <TrialBalance clientId={clientId} financialYear={financialYear} onDrillDown={openDrillDown} />
        )}
        {tab === "pl" && (
          <ProfitAndLoss clientId={clientId} financialYear={financialYear} onDrillDown={openDrillDown} />
        )}
        {tab === "balance-sheet" && (
          <BalanceSheet clientId={clientId} financialYear={financialYear} onDrillDown={openDrillDown} />
        )}
        {tab === "cashflow" && (
          <CashFlow clientId={clientId} financialYear={financialYear} />
        )}
        {tab === "banks" && (
          <BankAccounts clientId={clientId} />
        )}
        {tab === "categorize" && (
          <BankMatchQueue clientId={clientId} />
        )}
        {tab === "post" && (
          <BankPostingQueue clientId={clientId} accounts={accounts} />
        )}
        {tab === "approvals" && (
          <ApprovalQueue clientId={clientId} />
        )}
        {tab === "reconciliation" && (
          <BankReconciliation clientId={clientId} />
        )}
        {tab === "reports" && (
          <FinancialReports clientId={clientId} financialYear={financialYear} />
        )}
        {tab === "fx-reports" && (
          <FXReports clientId={clientId} financialYear={financialYear} />
        )}
      </div>

      {drillDown && (
        <LedgerDrillDown
          accounts={accounts}
          clientId={clientId}
          financialYear={financialYear}
          initialAccountId={drillDown.accountId}
          onClose={() => setDrillDown(null)}
        />
      )}
    </div>
  );
}

// ── Accounting Dashboard ───────────────────────────────────────────────────

function AccountingDashboard({
  clientId, financialYear, accounts, onNavigate,
}: {
  clientId: string;
  financialYear: string;
  accounts: Account[];
  onNavigate: (tab: AccountingTab) => void;
}) {
  const [stats, setStats] = useState({
    revenue_paise: 0, expenses_paise: 0, cash_paise: 0,
    unmatched_bank: 0, journal_count: 0,
  });
  const [recentEntries, setRecentEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    async function load() {
      setLoading(true);
      const supabase = getSupabaseClient();
      const { start, end } = fyDateRange(financialYear);

      // Headline figures come from the SINGLE backend reporting engine — never
      // recomputed in the browser (Phase 3: frontend renders only).
      let revenue = 0, expenses = 0, cash = 0;
      try {
        const [plRes, cfRes] = await Promise.all([
          api.accounting.profitLoss({ client_id: clientId, start_date: start, end_date: end }) as Promise<{ success: boolean; data: { revenue: { total_paise: number }; operating_expenses: { total_paise: number } } }>,
          api.accounting.cashFlow({ client_id: clientId, start_date: start, end_date: end }) as Promise<{ success: boolean; data: { closing_cash_paise: number } }>,
        ]);
        if (plRes.success) {
          revenue = plRes.data.revenue?.total_paise ?? 0;
          expenses = plRes.data.operating_expenses?.total_paise ?? 0;
        }
        if (cfRes.success) cash = cfRes.data.closing_cash_paise ?? 0;
      } catch { /* transient API error — leave zeros rather than recomputing client-side */ }

      // Unmatched bank transactions
      const { count: unmatchedCount } = await supabase
        .from("bank_transactions")
        .select("id", { count: "exact", head: true })
        .eq("client_id", clientId)
        .eq("match_status", "unmatched");

      // Recent journal entries
      const { data: recent } = await supabase
        .from("journal_entries")
        .select("id, entry_date, reference_no, narration, entry_type, is_posted")
        .eq("client_id", clientId)
        .is("deleted_at", null)
        .order("created_at", { ascending: false })
        .limit(5);

      // Journal count for FY
      const { count: jCount } = await supabase
        .from("journal_entries")
        .select("id", { count: "exact", head: true })
        .eq("client_id", clientId)
        .eq("is_posted", true)
        .is("deleted_at", null)
        .gte("entry_date", start)
        .lte("entry_date", end);

      setStats({ revenue_paise: revenue, expenses_paise: expenses, cash_paise: cash, unmatched_bank: unmatchedCount ?? 0, journal_count: jCount ?? 0 });
      setRecentEntries((recent as JournalEntry[]) ?? []);
      setLoading(false);
    }
    load();
  }, [clientId, financialYear]);

  const netPL = stats.revenue_paise - stats.expenses_paise;

  if (loading) return <div className="space-y-4 max-w-4xl mx-auto">{[...Array(3)].map((_, i) => <div key={i} className="h-24 rounded-xl bg-[#F8FAFC] animate-pulse" />)}</div>;

  return (
    <div className="space-y-5 max-w-4xl mx-auto">
      {/* Stat strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <DashCard label="Revenue" value={fmt(stats.revenue_paise)} accent="green" action={() => onNavigate("pl")} />
        <DashCard label="Expenses" value={fmt(stats.expenses_paise)} accent="red" action={() => onNavigate("pl")} />
        <DashCard
          label={netPL >= 0 ? "Net Profit" : "Net Loss"}
          value={fmt(Math.abs(netPL))}
          accent={netPL >= 0 ? "emerald" : "orange"}
          action={() => onNavigate("pl")}
        />
        <DashCard label="Cash & Bank" value={fmt(stats.cash_paise)} accent="blue" action={() => onNavigate("balance-sheet")} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <DashCard label="Posted Entries (FY)" value={String(stats.journal_count)} accent="gray" action={() => onNavigate("journal")} />
        <DashCard label="Unmatched Bank Txns" value={String(stats.unmatched_bank)} accent={stats.unmatched_bank > 0 ? "amber" : "gray"} action={() => onNavigate("reconciliation")} />
        <DashCard label="Accounts" value={String(accounts.length)} accent="gray" action={() => onNavigate("coa")} />
      </div>

      {/* Recent journal entries */}
      {recentEntries.length > 0 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-50 flex items-center justify-between">
            <p className="text-xs font-semibold text-[#334155]">Recent Entries</p>
            <button onClick={() => onNavigate("journal")} className="text-xs text-blue-600 hover:underline">View all</button>
          </div>
          <table className="w-full text-xs">
            <tbody className="divide-y divide-[#F8FAFC]">
              {recentEntries.map((e) => (
                <tr key={e.id} className="hover:bg-[#F8FAFC]">
                  <td className="px-4 py-2.5 text-[#64748B] whitespace-nowrap w-24">{e.entry_date}</td>
                  <td className="px-3 py-2.5 text-[#334155] truncate max-w-xs">{e.narration}</td>
                  <td className="px-3 py-2.5 text-[#94A3B8]">{e.entry_type}</td>
                  <td className="px-4 py-2.5">
                    <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${e.is_posted ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"}`}>
                      {e.is_posted ? "Posted" : "Draft"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function DashCard({ label, value, accent, action }: { label: string; value: string; accent: string; action?: () => void }) {
  const colors: Record<string, string> = {
    green: "bg-green-50 border-green-100", red: "bg-red-50 border-red-100",
    emerald: "bg-emerald-50 border-emerald-100", orange: "bg-orange-50 border-orange-100",
    blue: "bg-blue-50 border-blue-100", amber: "bg-amber-50 border-amber-100",
    gray: "bg-white border-[#F1F5F9]",
  };
  const textColors: Record<string, string> = {
    green: "text-green-800", red: "text-red-800", emerald: "text-emerald-800",
    orange: "text-orange-800", blue: "text-blue-800", amber: "text-amber-800", gray: "text-[#1E293B]",
  };
  return (
    <button
      onClick={action}
      className={`rounded-xl border p-4 text-left transition-shadow hover:shadow-sm ${colors[accent] ?? colors.gray}`}
    >
      <p className="text-[10px] font-medium text-[#64748B] mb-1">{label}</p>
      <p className={`text-lg font-bold tabular-nums ${textColors[accent] ?? "text-[#1E293B]"}`}>{value}</p>
    </button>
  );
}

// ── Chart of Accounts ──────────────────────────────────────────────────────

function ChartOfAccounts({ accounts, loading, onRefresh }: { accounts: Account[]; loading: boolean; onRefresh: () => void }) {
  const TYPE_ORDER = ["Asset", "Liability", "Equity", "Revenue", "Expense"];

  // Type-grouping context preserved as a colored badge in the Type column (flat,
  // sortable table). Type order also drives the default account_type sort tie-break.
  const TYPE_COLORS: Record<string, string> = {
    Asset: "text-blue-600 bg-blue-50", Liability: "text-orange-600 bg-orange-50",
    Equity: "text-purple-600 bg-purple-50", Revenue: "text-green-600 bg-green-50", Expense: "text-red-600 bg-red-50",
  };

  const columns: Column<Account>[] = [
    { key: "account_code", header: "Code", accessor: (a) => a.account_code, searchable: true, sortable: true, sticky: true, hideable: false, width: "6rem",
      render: (a) => <span className="font-mono text-[#64748B]">{a.account_code}</span> },
    { key: "account_name", header: "Account", accessor: (a) => a.account_name, searchable: true, sortable: true,
      render: (a) => <span className="font-medium text-[#1E293B]">{a.account_name}</span> },
    { key: "account_type", header: "Type", accessor: (a) => a.account_type, sortable: true,
      render: (a) => <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${TYPE_COLORS[a.account_type] ?? "text-[#64748B] bg-[#F1F5F9]"}`}>{a.account_type}</span> },
    { key: "account_subtype", header: "Subtype", accessor: (a) => a.account_subtype ?? "",
      render: (a) => <span className="text-[#94A3B8]">{a.account_subtype ?? "—"}</span> },
    { key: "scope", header: "Scope", accessor: (a) => (a.client_id ? "Client" : "Firm"), align: "right",
      render: (a) => <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#F8FAFC] text-[#94A3B8]">{a.client_id ? "Client" : "Firm"}</span> },
  ];

  const filters: FilterDef<Account>[] = [
    { key: "account_type", label: "Type", type: "select", accessor: (a) => a.account_type,
      options: TYPE_ORDER.map((t) => ({ value: t, label: t })) },
    { key: "is_active", label: "Status", type: "select", accessor: (a) => (a.is_active ? "active" : "inactive"),
      options: [{ value: "active", label: "Active" }, { value: "inactive", label: "Inactive" }] },
  ];

  return (
    <div className="space-y-4 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <p className="text-xs text-[#64748B]">{accounts.length} accounts</p>
      </div>

      <DataTable
        data={accounts}
        columns={columns}
        filters={filters}
        getRowId={(a) => a.id}
        loading={loading}
        onRefresh={onRefresh}
        searchPlaceholder="Search by code or name…"
        initialSort={{ key: "account_code", dir: "asc" }}
        persistKey="accounting.coa"
        emptyTitle="No accounts found"
        emptyDescription="Accounts are seeded from the firm-level chart of accounts."
      />
    </div>
  );
}

// ── Journal Entry Form ─────────────────────────────────────────────────────

const ENTRY_TYPES = ["Journal", "Sales", "Purchase", "Payment", "Receipt", "Contra", "Opening"] as const;

function JournalEntryForm({
  accounts, clientId, financialYear, onPosted,
}: {
  accounts: Account[]; clientId: string; financialYear: string; onPosted: () => void;
}) {
  const [entryDate, setEntryDate] = useState(todayLocalISO());
  const [entryType, setEntryType] = useState<string>("Journal");
  const [narration, setNarration] = useState("");
  const [referenceNo, setReferenceNo] = useState("");
  const [lines, setLines] = useState<JournalLine[]>([
    { account_id: "", debit_paise: 0, credit_paise: 0, narration: "" },
    { account_id: "", debit_paise: 0, credit_paise: 0, narration: "" },
  ]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  // Full journal list (posted + draft, non-deleted) for this client — rendered via
  // the shared DataTable below. Fetched with selectAll so large books are never
  // silently truncated at PostgREST's row cap (mirrors the other accounting tabs).
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [entriesLoading, setEntriesLoading] = useState(true);

  const totalDebit = lines.reduce((s, l) => s + l.debit_paise, 0);
  const totalCredit = lines.reduce((s, l) => s + l.credit_paise, 0);
  const isBalanced = totalDebit > 0 && totalDebit === totalCredit;

  const loadEntries = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setEntriesLoading(true);
    const supabase = getSupabaseClient();
    const { data } = await selectAll(() => supabase
      .from("journal_entries")
      // Alias the embed to `lines` so it matches the JournalEntry type (and the
      // amount column, which sums debit_paise across the entry's lines).
      .select("id, entry_date, reference_no, narration, entry_type, is_posted, lines:journal_lines(account_id, debit_paise, credit_paise, narration)")
      .eq("client_id", clientId)
      .is("deleted_at", null)
      .order("entry_date", { ascending: false })
      .order("id"));
    setEntries((data as unknown as JournalEntry[]) ?? []);
    setEntriesLoading(false);
  }, [clientId]);

  useEffect(() => { loadEntries(); }, [loadEntries, success]);

  const journalColumns: Column<JournalEntry>[] = [
    { key: "entry_date", header: "Date", accessor: (e) => e.entry_date, sortable: true, sticky: true, hideable: false, width: "7rem",
      render: (e) => <span className="text-[#64748B] whitespace-nowrap">{e.entry_date}</span> },
    { key: "reference_no", header: "Ref", accessor: (e) => e.reference_no ?? "", searchable: true,
      render: (e) => <span className="font-mono text-[#94A3B8]">{e.reference_no || "—"}</span> },
    { key: "narration", header: "Narration", accessor: (e) => e.narration, searchable: true,
      render: (e) => <span className="text-[#334155]">{e.narration}</span> },
    { key: "entry_type", header: "Type", accessor: (e) => e.entry_type, sortable: true,
      render: (e) => <span className="text-[#94A3B8]">{e.entry_type}</span> },
    { key: "amount", header: "Amount", accessor: (e) => (e.lines ?? []).reduce((s, l) => s + l.debit_paise, 0), align: "right",
      exportValue: (e) => (e.lines ?? []).reduce((s, l) => s + l.debit_paise, 0) / 100,
      render: (e) => <span className="font-mono text-[#334155]">{fmt((e.lines ?? []).reduce((s, l) => s + l.debit_paise, 0))}</span> },
    { key: "status", header: "Status", accessor: (e) => (e.is_posted ? "Posted" : "Draft"),
      render: (e) => <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${e.is_posted ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"}`}>{e.is_posted ? "Posted" : "Draft"}</span> },
  ];

  const journalFilters: FilterDef<JournalEntry>[] = [
    { key: "entry_type", label: "Type", type: "select", accessor: (e) => e.entry_type,
      options: (ENTRY_TYPES as readonly string[]).map((t) => ({ value: t, label: t })) },
    { key: "entry_date", label: "Date", type: "dateRange", accessor: (e) => e.entry_date },
  ];

  function setLine(idx: number, patch: Partial<JournalLine>) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }

  function addLine() {
    setLines((prev) => [...prev, { account_id: "", debit_paise: 0, credit_paise: 0, narration: "" }]);
  }

  function removeLine(idx: number) {
    if (lines.length <= 2) return;
    setLines((prev) => prev.filter((_, i) => i !== idx));
  }

  async function handleSave(post: boolean) {
    if (!isBalanced) { setError("Debits must equal credits before saving."); return; }
    if (!narration.trim()) { setError("Narration is required."); return; }
    const validLines = lines.filter((l) => l.account_id && (l.debit_paise > 0 || l.credit_paise > 0));
    if (validLines.length < 2) { setError("At least 2 lines with account and amount required."); return; }
    setSaving(true); setError(null);
    try {
      // Posts through the backend's single posting kernel (manual_journal_service →
      // phase2_journal_service._create_journal), which writes the header and every
      // line in one DB transaction (post_journal_atomic) and authoritatively
      // enforces the FY lock server-side — no separate client-side pre-check or
      // direct-to-Supabase writes, so a failed second write can never leave a
      // posted header with zero lines.
      const firmId = await getFirmId();
      const res = await api.accounting.createJournalEntry({
        client_id: clientId,
        entry_date: entryDate,
        reference_no: referenceNo.trim() || undefined,
        narration: narration.trim(),
        entry_type: entryType,
        status: post ? "posted" : "draft",
        lines: validLines.map((l) => ({
          account_id: l.account_id,
          debit_paise: l.debit_paise,
          credit_paise: l.credit_paise,
          narration: l.narration.trim() || undefined,
        })),
      }) as { success: boolean; data: { id: string } };
      try {
        await writeTimelineEvent({ client_id: clientId, firm_id: firmId, financial_year: financialYear, category: "accounting", event_type: post ? "journal_entry_posted" : "journal_entry_saved", severity: "info", title: post ? "Journal entry posted" : "Journal entry saved (draft)", description: narration.trim(), entity_type: "journal_entry", entity_id: res.data.id, actor_type: "user" });
      } catch { /* non-blocking */ }
      setSuccess(true);
      setNarration(""); setReferenceNo("");
      setLines([{ account_id: "", debit_paise: 0, credit_paise: 0, narration: "" }, { account_id: "", debit_paise: 0, credit_paise: 0, narration: "" }]);
      onPosted();
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5 max-w-3xl mx-auto">
      {success && <div className="bg-green-50 border border-green-100 rounded-lg px-4 py-3 text-sm text-green-700 font-medium">Journal entry saved successfully.</div>}
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
        <h3 className="text-sm font-semibold text-[#0F172A]">New Journal Entry</h3>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Date *</label>
            <input type="date" value={entryDate} onChange={(e) => setEntryDate(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Type</label>
            <select value={entryType} onChange={(e) => setEntryType(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
              {ENTRY_TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Reference No.</label>
            <input value={referenceNo} onChange={(e) => setReferenceNo(e.target.value)} placeholder="INV-001" className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Narration *</label>
          <input value={narration} onChange={(e) => setNarration(e.target.value)} placeholder="Being goods sold to ABC Ltd..." className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                <th className="pb-2 text-left font-semibold">Account</th>
                <th className="pb-2 text-right font-semibold w-28">Debit (₹)</th>
                <th className="pb-2 text-right font-semibold w-28">Credit (₹)</th>
                <th className="pb-2 text-left font-semibold pl-3">Narration</th>
                <th className="pb-2 w-6" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {lines.map((line, idx) => (
                <tr key={idx}>
                  <td className="py-1.5 pr-2">
                    <AccountLookup
                      accounts={accounts}
                      value={line.account_id}
                      onChange={(id) => setLine(idx, { account_id: id })}
                      size="sm"
                      placeholder="— Select account —"
                      ariaLabel="Account"
                    />
                  </td>
                  <td className="py-1.5 px-2">
                    <input type="number" min="0" step="0.01" value={line.debit_paise === 0 ? "" : (line.debit_paise / 100).toFixed(2)} onChange={(e) => { const v = Math.round(parseFloat(e.target.value || "0") * 100); setLine(idx, { debit_paise: v, credit_paise: v > 0 ? 0 : line.credit_paise }); }} placeholder="0.00" className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs" />
                  </td>
                  <td className="py-1.5 px-2">
                    <input type="number" min="0" step="0.01" value={line.credit_paise === 0 ? "" : (line.credit_paise / 100).toFixed(2)} onChange={(e) => { const v = Math.round(parseFloat(e.target.value || "0") * 100); setLine(idx, { credit_paise: v, debit_paise: v > 0 ? 0 : line.debit_paise }); }} placeholder="0.00" className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs" />
                  </td>
                  <td className="py-1.5 pl-3"><input value={line.narration} onChange={(e) => setLine(idx, { narration: e.target.value })} placeholder="optional" className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs" /></td>
                  <td className="py-1.5 pl-1">{lines.length > 2 && <button onClick={() => removeLine(idx)} className="text-[#CBD5E1] hover:text-red-600 font-bold">×</button>}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-[#F1F5F9] text-xs font-semibold">
                <td className="pt-2 text-[#64748B]">Total</td>
                <td className="pt-2 text-right text-[#334155] px-2">{totalDebit > 0 ? `₹${(totalDebit/100).toFixed(2)}` : "—"}</td>
                <td className="pt-2 text-right text-[#334155] px-2">{totalCredit > 0 ? `₹${(totalCredit/100).toFixed(2)}` : "—"}</td>
                <td colSpan={2} className="pt-2 pl-3">
                  {totalDebit > 0 && totalDebit !== totalCredit && <span className="text-red-500 text-[10px]">Difference: ₹{(Math.abs(totalDebit - totalCredit)/100).toFixed(2)}</span>}
                  {isBalanced && <span className="text-green-600 text-[10px]">✓ Balanced</span>}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
        <button onClick={addLine} className="text-xs text-blue-600 hover:underline flex items-center gap-1"><Plus size={12} /> Add line</button>
        {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
        <div className="flex gap-3 justify-end pt-1">
          <button onClick={() => handleSave(false)} disabled={saving || !isBalanced} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] disabled:opacity-40">Save Draft</button>
          <button onClick={() => handleSave(true)} disabled={saving || !isBalanced} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">{saving ? "Saving…" : "Post Entry"}</button>
        </div>
      </div>

      {/* Full journal list — shared DataTable (search, type/date filters, sort,
          pagination, export). Replaces the old "recent 5" preview and is the
          destination the Dashboard "View all" navigates to. */}
      <div className="space-y-2">
        <p className="text-xs font-semibold text-[#334155]">All Journal Entries</p>
        <DataTable
          data={entries}
          columns={journalColumns}
          filters={journalFilters}
          getRowId={(e) => e.id}
          loading={entriesLoading}
          onRefresh={loadEntries}
          searchPlaceholder="Search by reference or narration…"
          initialSort={{ key: "entry_date", dir: "desc" }}
          exportFilename="journal"
          persistKey="accounting.journal"
          emptyTitle="No journal entries"
          emptyDescription="Post an entry above to see it listed here."
        />
      </div>
    </div>
  );
}

// ── Ledger Drill-Down Overlay ────────────────────────────────────────────────
// QuickBooks-style: click an amount/account on Trial Balance, P&L, or the
// Balance Sheet and this opens on top with that account's full ledger. Its
// account switcher and date range are entirely local state, seeded once on
// open from the report's FY — closing it never touches the tab, FY, or basis
// toggle underneath, so the report is exactly as it was left.

function LedgerDrillDown({
  accounts, clientId, financialYear, initialAccountId, onClose,
}: {
  accounts: Account[];
  clientId: string;
  financialYear: string;
  initialAccountId: string;
  onClose: () => void;
}) {
  const [accountId, setAccountId] = useState(initialAccountId);
  const fyRange = fyDateRange(financialYear);
  const [startDate, setStartDate] = useState(fyRange.start);
  const [endDate, setEndDate] = useState(fyRange.end);
  const [ledger, setLedger] = useState<LedgerView | null>(null);
  const [loading, setLoading] = useState(false);

  // The backend reporting engine computes opening/running/closing balances —
  // the browser only fetches and renders (Phase 3.4: no accounting math in React).
  const load = useCallback(async () => {
    if (!accountId || !clientId || clientId === "_placeholder") { setLedger(null); return; }
    setLoading(true);
    try {
      const res = (await cachedReport(
        reportKey([clientId, "ledger", accountId, startDate, endDate]),
        () => api.accounting.ledger({
          client_id: clientId, account_id: accountId, start_date: startDate, end_date: endDate,
        }),
      )) as { success: boolean; data: LedgerView };
      setLedger(res.success ? res.data : null);
    } catch { setLedger(null); } finally { setLoading(false); }
  }, [clientId, accountId, startDate, endDate]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const bal = (paise: number, isDebit: boolean) => (
    <>{fmt(Math.abs(paise))}<span className="text-[10px] font-normal ml-1 opacity-60">{isDebit ? "Dr" : "Cr"}</span></>
  );
  const hasActivity = !!ledger && (ledger.lines.length > 0 || ledger.opening_balance_paise !== 0);
  const accountName = ledger?.account_name ?? accounts.find((a) => a.id === accountId)?.account_name ?? "";

  // Ledger line columns. Money is paise → right-aligned via `fmt` (formatPaise).
  // The running balance is the backend's authoritative per-row figure — sorting
  // reorders rows but never recomputes it (Phase 3.4: no accounting math in React).
  const ledgerColumns: Column<LedgerLine>[] = [
    { key: "entry_date", header: "Date", accessor: (l) => l.entry_date, sortable: true, sticky: true, hideable: false, width: "7rem",
      render: (l) => <span className="text-[#64748B] whitespace-nowrap">{l.entry_date}</span> },
    { key: "narration", header: "Particulars", accessor: (l) => l.narration ?? "", searchable: true,
      render: (l) => <span className="text-[#334155]">{l.narration ?? "—"}</span> },
    { key: "reference_no", header: "Ref", accessor: (l) => l.reference_no ?? "", searchable: true,
      render: (l) => <span className="font-mono text-[#94A3B8]">{l.reference_no ?? "—"}</span> },
    { key: "debit", header: "Debit", accessor: (l) => l.debit_paise, sortable: true, align: "right",
      exportValue: (l) => l.debit_paise / 100,
      render: (l) => <span className="font-mono text-[#334155]">{fmt(l.debit_paise)}</span> },
    { key: "credit", header: "Credit", accessor: (l) => l.credit_paise, sortable: true, align: "right",
      exportValue: (l) => l.credit_paise / 100,
      render: (l) => <span className="font-mono text-[#334155]">{fmt(l.credit_paise)}</span> },
    // NOT sortable: a running balance is only meaningful in chronological (entry_date)
    // order — sorting rows by it would display a nonsensical, non-progressive sequence.
    { key: "running_balance", header: "Balance", accessor: (l) => l.running_balance_paise, sortable: false, align: "right",
      exportValue: (l) => l.running_balance_paise / 100,
      render: (l) => <span className={`font-mono font-semibold ${l.is_debit ? "text-blue-700" : "text-orange-700"}`}>{bal(l.running_balance_paise, l.is_debit)}</span> },
  ];

  const ledgerFilters: FilterDef<LedgerLine>[] = [
    { key: "entry_date", label: "Date", type: "dateRange", accessor: (l) => l.entry_date },
  ];

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-[100] flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-5xl max-h-[88vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-4 border-b border-[#F1F5F9] flex items-center justify-between shrink-0">
          <div>
            <p className="text-sm font-semibold text-[#0F172A]">{accountName || "Ledger"}</p>
            <p className="text-[11px] text-[#94A3B8] mt-0.5">Account ledger</p>
          </div>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#334155] text-xl leading-none" aria-label="Back">×</button>
        </div>

        <div className="px-5 py-3 border-b border-[#F1F5F9] flex items-end gap-3 flex-wrap shrink-0">
          <div className="w-64">
            <label className="block text-[10px] font-medium text-[#94A3B8] mb-1">Account</label>
            <AccountLookup
              accounts={accounts}
              value={accountId}
              onChange={setAccountId}
              placeholder="— Choose account —"
              ariaLabel="Select account"
            />
          </div>
          <div>
            <label className="block text-[10px] font-medium text-[#94A3B8] mb-1">From</label>
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
              className="px-2.5 py-[7px] text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-[10px] font-medium text-[#94A3B8] mb-1">To</label>
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
              className="px-2.5 py-[7px] text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <button onClick={() => { setStartDate(fyRange.start); setEndDate(fyRange.end); }} className="text-xs text-blue-600 hover:underline pb-1.5">
            Reset to FY {financialYear}
          </button>
          {loading && <RefreshCw size={13} className="animate-spin text-[#94A3B8] mb-1.5" />}
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {!accountId ? (
            <div className="text-center py-10 text-[#94A3B8] text-sm">Choose an account to view its ledger.</div>
          ) : !loading && ledger && hasActivity ? (
            <div className="space-y-3">
              {/* Opening / Closing are backend-computed context — kept outside the
                  table so search/sort/pagination never repositions them. */}
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#F1F5F9] bg-[#F8FAFC] px-4 py-2 text-xs text-[#64748B]">
                <span>Opening Balance</span>
                <span className="font-mono font-semibold text-[#334155]">{bal(ledger.opening_balance_paise, ledger.opening_is_debit)}</span>
              </div>

              <DataTable
                data={ledger.lines}
                columns={ledgerColumns}
                filters={ledgerFilters}
                getRowId={(l) => l.entry_id}
                searchPlaceholder="Search narration or reference…"
                initialSort={{ key: "entry_date", dir: "asc" }}
                initialPageSize={100}
                exportFilename="ledger"
                persistKey="accounting.ledger"
                emptyTitle="No transactions"
                emptyDescription="No posted transactions for this account in the selected range."
              />

              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] px-4 py-2.5 text-xs font-semibold text-[#334155]">
                <span>Closing Balance</span>
                <span className="flex items-center gap-4 font-mono">
                  <span className="text-[#64748B]">Dr {fmt(ledger.total_debit_paise)}</span>
                  <span className="text-[#64748B]">Cr {fmt(ledger.total_credit_paise)}</span>
                  <span className={ledger.closing_is_debit ? "text-blue-700" : "text-orange-700"}>{bal(ledger.closing_balance_paise, ledger.closing_is_debit)}</span>
                </span>
              </div>
            </div>
          ) : !loading ? (
            <div className="text-center py-10 text-[#94A3B8] text-sm">No posted transactions for this account in the selected range.</div>
          ) : (
            <div className="h-40 rounded-lg bg-[#F8FAFC] animate-pulse" />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Trial Balance ──────────────────────────────────────────────────────────

function TrialBalance({ clientId, financialYear, onDrillDown }: { clientId: string; financialYear: string; onDrillDown: (accountId: string) => void }) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const basis = (searchParams.get("basis") as "accrual" | "cash") ?? "accrual";

  const [rows, setRows] = useState<TrialRow[]>([]);
  // Authoritative totals come from the backend — never recomputed here.
  const [totals, setTotals] = useState({ debit: 0, credit: 0, balanced: true });
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const updateBasis = (b: "accrual" | "cash") => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("basis", b);
    router.replace(`?${params.toString()}`, { scroll: false });
  };

  const load = useCallback(async (force?: boolean) => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    // Both bases are computed server-side from the same posted ledger, scoped to
    // this client (IT Act §145). The frontend only passes parameters (CLAUDE.md).
    const { end } = fyDateRange(financialYear);
    try {
      const res = (await cachedReport(
        reportKey([clientId, financialYear, basis, "tb"]),
        () => api.accounting.trialBalance({ basis, as_of_date: end, client_id: clientId }),
        { force },
      )) as { success: boolean; data: TBApiData | null };
      if (res.success && res.data) {
        setRows(res.data.lines ?? []);
        setTotals({
          debit: res.data.total_debit_paise,
          credit: res.data.total_credit_paise,
          balanced: res.data.is_balanced,
        });
      } else {
        setRows([]);
        setTotals({ debit: 0, credit: 0, balanced: true });
      }
    } catch {
      // Backend error/timeout — degrade to empty, never an infinite skeleton (audit M17).
      setRows([]);
      setTotals({ debit: 0, credit: 0, balanced: true });
    } finally {
      setLoading(false); setLoaded(true);
    }
  }, [clientId, financialYear, basis]);

  useEffect(() => { load(); }, [load]);

  // Display totals are the backend's authoritative figures (single source of truth).
  const grandDebit = totals.debit;
  const grandCredit = totals.credit;
  const isBalanced = totals.balanced;

  return (
    <div className="space-y-4 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">Trial Balance — FY {financialYear}</p>
        <div className="flex items-center gap-2">
          {/* Accrual | Cash toggle — IT Act Section 145 */}
          <div className="flex rounded border border-[#E2E8F0] overflow-hidden text-xs">
            <button onClick={() => updateBasis("accrual")} className={`px-3 py-1 font-medium transition-colors ${basis === "accrual" ? "bg-[#1E293B] text-white" : "bg-white text-[#64748B] hover:bg-[#F8FAFC]"}`}>Accrual</button>
            <button onClick={() => updateBasis("cash")} className={`px-3 py-1 font-medium border-l border-[#E2E8F0] transition-colors ${basis === "cash" ? "bg-[#1E293B] text-white" : "bg-white text-[#64748B] hover:bg-[#F8FAFC]"}`}>Cash</button>
          </div>
          <button onClick={() => load(true)} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
        </div>
      </div>
      {basis === "cash" && (
        <div className="bg-amber-50 border border-amber-200 rounded px-3 py-2 text-xs text-amber-700">
          Cash basis — management reporting only (IT Act §145). GST returns remain invoice-based per CGST Act.
        </div>
      )}
      {loading ? <div className="h-40 rounded-lg bg-[#F8FAFC] animate-pulse" /> : loaded && rows.length > 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <table className="w-full text-xs">
            <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]"><th className="px-4 py-3 text-left font-semibold">Code</th><th className="px-3 py-3 text-left font-semibold">Account</th><th className="px-3 py-3 text-left font-semibold">Type</th><th className="px-3 py-3 text-right font-semibold">Debit (₹)</th><th className="px-4 py-3 text-right font-semibold">Credit (₹)</th></tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {rows.map((r) => (
                <tr key={r.account_id} className="hover:bg-[#F8FAFC] cursor-pointer" onClick={() => onDrillDown(r.account_id)}>
                  <td className="px-4 py-2 font-mono text-[#64748B]">{r.account_code}</td>
                  <td className="px-3 py-2 font-medium text-[#1E293B] hover:text-blue-700 hover:underline">{r.account_name}</td>
                  <td className="px-3 py-2 text-[#94A3B8]">{r.account_type}</td>
                  <td className="px-3 py-2 text-right font-mono text-[#334155] hover:text-blue-700 hover:underline">{r.total_debit_paise > 0 ? fmt(r.total_debit_paise) : "—"}</td>
                  <td className="px-4 py-2 text-right font-mono text-[#334155] hover:text-blue-700 hover:underline">{r.total_credit_paise > 0 ? fmt(r.total_credit_paise) : "—"}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-[#E2E8F0] font-semibold">
                <td colSpan={3} className="px-4 py-3 text-[#334155] text-sm">Total</td>
                <td className="px-3 py-3 text-right font-mono text-[#0F172A] text-sm">₹{(grandDebit/100).toFixed(2)}</td>
                <td className="px-4 py-3 text-right font-mono text-[#0F172A] text-sm">₹{(grandCredit/100).toFixed(2)}</td>
              </tr>
              <tr><td colSpan={5} className="px-4 pb-3">{isBalanced ? <span className="text-xs text-green-600 font-medium">✓ Trial Balance is balanced</span> : <span className="text-xs text-red-600 font-medium">✗ Out of balance by ₹{(Math.abs(grandDebit-grandCredit)/100).toFixed(2)}</span>}</td></tr>
            </tfoot>
          </table>
        </div>
      ) : loaded ? <div className="text-center py-12 text-[#94A3B8] text-sm">No posted journal entries for FY {financialYear}.</div> : null}
    </div>
  );
}

// ── FX Reports (Multi-Currency Phase 5) ──────────────────────────────────────
// Read-only foreign-exchange reporting. EVERY figure is computed server-side
// (services.fx_reporting_service) from posted accounting data; the component only
// presents it (CLAUDE.md — zero business logic in the frontend). The base (INR)
// amounts stay authoritative; foreign figures are display memo. For an INR-only
// client every report is empty, so this tab simply shows "no FX activity".

type FXView = "exposure" | "realized" | "unrealized" | "open" | "audit";
const FX_VIEWS: { id: FXView; label: string }[] = [
  { id: "exposure",   label: "Exposure" },
  { id: "realized",   label: "Realized" },
  { id: "unrealized", label: "Unrealized" },
  { id: "open",       label: "Open Balances" },
  { id: "audit",      label: "Rate Audit" },
];

interface FXExposureRow {
  currency: string;
  receivable_foreign_minor: number; receivable_base_paise: number;
  payable_foreign_minor: number; payable_base_paise: number;
  bank_foreign_minor: number; bank_base_paise: number;
  net_foreign_minor: number; net_base_paise: number;
}
interface FXRealizedData {
  gain_paise: number; loss_paise: number; net_paise: number;
  lines: { date: string; document_type: string; currency: string; settlement_rate: string | null; base_delta_paise: number; is_gain: boolean }[];
  by_currency: { currency: string; gain_paise: number; loss_paise: number; net_paise: number }[];
}
interface FXUnrealizedData {
  net_paise: number;
  lines: { period_end: string; currency: string; item_type: string; closing_rate: string | null; cumulative_delta_paise: number; runs: number }[];
  by_currency: { currency: string; net_paise: number }[];
}
interface FXOpenDoc { doc_no: string; currency: string; exchange_rate: string; foreign_outstanding_minor: number; base_outstanding_paise: number }
interface FXOpenData {
  receivables: FXOpenDoc[]; payables: FXOpenDoc[];
  bank_accounts: { name: string; currency: string; foreign_balance_minor: number; base_balance_paise: number }[];
}
interface FXAuditData {
  overridden_count: number;
  documents: { document_no: string; date: string; currency: string; exchange_rate: string; rate_source: string | null; rate_type: string | null; rate_overridden: boolean }[];
  adjustments: { date: string; kind: string; currency: string; settlement_rate: string | null; closing_rate: string | null; base_delta_paise: number }[];
}

function CcyBadge({ code }: { code: string }) {
  return <span className="inline-flex items-center rounded-full bg-[#EEF2FF] px-2 py-0.5 text-[10px] font-semibold text-[#4338CA]">{code}</span>;
}

/** Signed base amount with gain(green)/loss(red) colour — a realized/unrealized delta. */
function fxDelta(paise: number) {
  const cls = paise > 0 ? "text-green-600" : paise < 0 ? "text-red-600" : "text-[#94A3B8]";
  const sign = paise > 0 ? "+" : "";
  return <span className={`font-mono ${cls}`}>{paise === 0 ? "—" : `${sign}${formatPaise(paise)}`}</span>;
}

function FXReports({ clientId, financialYear }: { clientId: string; financialYear: string }) {
  const [view, setView] = useState<FXView>("exposure");
  const [ccy, setCcy] = useState<string>("all");
  const [data, setData] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true); setLoaded(false);
    const { start, end } = fyDateRange(financialYear);
    type FXResp = { success: boolean; data: unknown };
    try {
      let res: FXResp;
      if (view === "exposure") res = await api.accounting.fxReports.exposure({ client_id: clientId, as_of: end }) as FXResp;
      else if (view === "realized") res = await api.accounting.fxReports.realized({ client_id: clientId, start_date: start, end_date: end }) as FXResp;
      else if (view === "unrealized") res = await api.accounting.fxReports.unrealized({ client_id: clientId, period_end: end }) as FXResp;
      else if (view === "open") res = await api.accounting.fxReports.openBalances({ client_id: clientId, as_of: end }) as FXResp;
      else res = await api.accounting.fxReports.rateAudit({ client_id: clientId, start_date: start, end_date: end }) as FXResp;
      setData(res && res.success ? res.data : null);
    } catch {
      // Degrade to empty, never an infinite skeleton (matches every other report here).
      setData(null);
    } finally {
      setLoading(false); setLoaded(true);
    }
  }, [clientId, financialYear, view]);

  useEffect(() => { load(); }, [load]);

  const byC = <T extends { currency: string }>(rows: T[]): T[] => ccy === "all" ? rows : rows.filter((r) => r.currency === ccy);
  const currencyOptions = fxCurrencyOptions(view, data);

  return (
    <div className="space-y-4 max-w-4xl mx-auto">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex rounded border border-[#E2E8F0] overflow-hidden text-xs">
          {FX_VIEWS.map((v) => (
            <button key={v.id} onClick={() => setView(v.id)}
              className={`px-3 py-1 font-medium border-l first:border-l-0 border-[#E2E8F0] transition-colors ${view === v.id ? "bg-[#1E293B] text-white" : "bg-white text-[#64748B] hover:bg-[#F8FAFC]"}`}>
              {v.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {currencyOptions.length > 0 && (
            <select value={ccy} onChange={(e) => setCcy(e.target.value)}
              className="text-xs rounded border border-[#E2E8F0] px-2 py-1 text-[#475569] bg-white">
              <option value="all">All currencies</option>
              {currencyOptions.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          )}
          <button onClick={load} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
        </div>
      </div>

      {loading ? <div className="h-40 rounded-lg bg-[#F8FAFC] animate-pulse" /> : !loaded ? null : (
        <FXReportBody view={view} data={data} byC={byC} />
      )}
    </div>
  );
}

/** Distinct currency codes available for the filter, per view. */
function fxCurrencyOptions(view: FXView, data: unknown): string[] {
  const set = new Set<string>();
  const add = (rows?: { currency: string }[]) => (rows ?? []).forEach((r) => r.currency && set.add(r.currency));
  if (view === "exposure") add((data as { by_currency?: FXExposureRow[] } | null)?.by_currency);
  else if (view === "realized") add((data as FXRealizedData | null)?.by_currency);
  else if (view === "unrealized") add((data as FXUnrealizedData | null)?.by_currency);
  else if (view === "open") { const d = data as FXOpenData | null; add(d?.receivables); add(d?.payables); add(d?.bank_accounts); }
  else add((data as FXAuditData | null)?.documents);
  return Array.from(set).sort();
}

function FXEmpty() {
  return <div className="text-center py-12 text-[#94A3B8] text-sm">No foreign-currency activity for this period.</div>;
}

function FXReportBody({ view, data, byC }: {
  view: FXView; data: unknown; byC: <T extends { currency: string }>(rows: T[]) => T[];
}) {
  const wrap = "bg-white rounded-xl border border-[#F1F5F9] overflow-hidden";
  const th = "px-3 py-3 text-left font-semibold";
  const thr = "px-3 py-3 text-right font-semibold";

  if (view === "exposure") {
    const rows = byC((data as { by_currency?: FXExposureRow[] } | null)?.by_currency ?? []);
    if (rows.length === 0) return <FXEmpty />;
    return (
      <div className={wrap}>
        <table className="w-full text-xs">
          <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
            <th className={th}>Currency</th><th className={thr}>Receivable</th><th className={thr}>Payable</th>
            <th className={thr}>Bank</th><th className={thr}>Net (foreign)</th><th className={thr}>Net (₹ base)</th>
          </tr></thead>
          <tbody className="divide-y divide-[#F8FAFC]">
            {rows.map((r) => (
              <tr key={r.currency} className="hover:bg-[#F8FAFC]">
                <td className="px-3 py-2"><CcyBadge code={r.currency} /></td>
                <td className="px-3 py-2 text-right font-mono text-[#334155]">{formatMoney(r.receivable_foreign_minor, r.currency)}</td>
                <td className="px-3 py-2 text-right font-mono text-[#334155]">{formatMoney(r.payable_foreign_minor, r.currency)}</td>
                <td className="px-3 py-2 text-right font-mono text-[#334155]">{formatMoney(r.bank_foreign_minor, r.currency)}</td>
                <td className="px-3 py-2 text-right font-mono font-semibold text-[#1E293B]">{formatMoney(r.net_foreign_minor, r.currency)}</td>
                <td className="px-3 py-2 text-right font-mono text-[#334155]">{formatPaise(r.net_base_paise)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (view === "realized") {
    const d = data as FXRealizedData | null;
    const lines = byC(d?.lines ?? []);
    if (!d || lines.length === 0) return <FXEmpty />;
    return (
      <div className="space-y-3">
        <div className="flex gap-3 text-xs">
          <div className="flex-1 bg-green-50 border border-green-200 rounded-lg px-3 py-2"><p className="text-[#94A3B8]">Gain</p><p className="font-mono font-semibold text-green-700">{formatPaise(d.gain_paise)}</p></div>
          <div className="flex-1 bg-red-50 border border-red-200 rounded-lg px-3 py-2"><p className="text-[#94A3B8]">Loss</p><p className="font-mono font-semibold text-red-700">{formatPaise(d.loss_paise)}</p></div>
          <div className="flex-1 bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg px-3 py-2"><p className="text-[#94A3B8]">Net</p><p className="font-mono font-semibold text-[#1E293B]">{fxDelta(d.net_paise)}</p></div>
        </div>
        <div className={wrap}>
          <table className="w-full text-xs">
            <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]"><th className={th}>Date</th><th className={th}>Document</th><th className={th}>Currency</th><th className={thr}>Settle rate</th><th className={thr}>Gain / (Loss)</th></tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {lines.map((l, i) => (
                <tr key={i} className="hover:bg-[#F8FAFC]">
                  <td className="px-3 py-2 text-[#64748B]">{l.date}</td>
                  <td className="px-3 py-2 text-[#475569]">{(l.document_type ?? "").replace(/_/g, " ")}</td>
                  <td className="px-3 py-2"><CcyBadge code={l.currency} /></td>
                  <td className="px-3 py-2 text-right font-mono text-[#64748B]">{l.settlement_rate ?? "—"}</td>
                  <td className="px-3 py-2 text-right">{fxDelta(l.base_delta_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  if (view === "unrealized") {
    const d = data as FXUnrealizedData | null;
    const lines = byC(d?.lines ?? []);
    if (!d || lines.length === 0) return <FXEmpty />;
    return (
      <div className={wrap}>
        <table className="w-full text-xs">
          <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]"><th className={th}>Period end</th><th className={th}>Currency</th><th className={th}>Item</th><th className={thr}>Closing rate</th><th className={thr}>Cumulative</th><th className={thr}>Runs</th></tr></thead>
          <tbody className="divide-y divide-[#F8FAFC]">
            {lines.map((l, i) => (
              <tr key={i} className="hover:bg-[#F8FAFC]">
                <td className="px-3 py-2 text-[#64748B]">{l.period_end}</td>
                <td className="px-3 py-2"><CcyBadge code={l.currency} /></td>
                <td className="px-3 py-2 text-[#475569] capitalize">{l.item_type}</td>
                <td className="px-3 py-2 text-right font-mono text-[#64748B]">{l.closing_rate ?? "—"}</td>
                <td className="px-3 py-2 text-right">{fxDelta(l.cumulative_delta_paise)}</td>
                <td className="px-3 py-2 text-right font-mono text-[#94A3B8]">{l.runs}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (view === "open") {
    const d = data as FXOpenData | null;
    const recv = byC(d?.receivables ?? []);
    const pay = byC(d?.payables ?? []);
    const banks = byC(d?.bank_accounts ?? []);
    if (!d || (recv.length === 0 && pay.length === 0 && banks.length === 0)) return <FXEmpty />;
    const docTable = (title: string, rows: FXOpenDoc[]) => rows.length === 0 ? null : (
      <div className="space-y-1">
        <p className="text-xs font-semibold text-[#334155]">{title}</p>
        <div className={wrap}>
          <table className="w-full text-xs">
            <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]"><th className={th}>Document</th><th className={th}>Currency</th><th className={thr}>Rate</th><th className={thr}>Foreign outstanding</th><th className={thr}>Base (₹)</th></tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {rows.map((r, i) => (
                <tr key={i} className="hover:bg-[#F8FAFC]">
                  <td className="px-3 py-2 text-[#475569]">{r.doc_no}</td>
                  <td className="px-3 py-2"><CcyBadge code={r.currency} /></td>
                  <td className="px-3 py-2 text-right font-mono text-[#64748B]">{r.exchange_rate}</td>
                  <td className="px-3 py-2 text-right font-mono text-[#334155]">{formatMoney(r.foreign_outstanding_minor, r.currency)}</td>
                  <td className="px-3 py-2 text-right font-mono text-[#334155]">{formatPaise(r.base_outstanding_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
    return (
      <div className="space-y-4">
        {docTable("Receivables", recv)}
        {docTable("Payables", pay)}
        {banks.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-semibold text-[#334155]">Bank accounts</p>
            <div className={wrap}>
              <table className="w-full text-xs">
                <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]"><th className={th}>Account</th><th className={th}>Currency</th><th className={thr}>Foreign balance</th><th className={thr}>Base (₹)</th></tr></thead>
                <tbody className="divide-y divide-[#F8FAFC]">
                  {banks.map((b, i) => (
                    <tr key={i} className="hover:bg-[#F8FAFC]">
                      <td className="px-3 py-2 text-[#475569]">{b.name}</td>
                      <td className="px-3 py-2"><CcyBadge code={b.currency} /></td>
                      <td className="px-3 py-2 text-right font-mono text-[#334155]">{formatMoney(b.foreign_balance_minor, b.currency)}</td>
                      <td className="px-3 py-2 text-right font-mono text-[#334155]">{formatPaise(b.base_balance_paise)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    );
  }

  // Rate audit
  const d = data as FXAuditData | null;
  const docs = byC(d?.documents ?? []);
  if (!d || docs.length === 0) return <FXEmpty />;
  return (
    <div className="space-y-3">
      {d.overridden_count > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded px-3 py-2 text-xs text-amber-700">
          {d.overridden_count} document rate{d.overridden_count === 1 ? "" : "s"} manually overridden — review provenance below.
        </div>
      )}
      <div className={wrap}>
        <table className="w-full text-xs">
          <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]"><th className={th}>Date</th><th className={th}>Document</th><th className={th}>Currency</th><th className={thr}>Rate</th><th className={th}>Source</th><th className={th}>Overridden</th></tr></thead>
          <tbody className="divide-y divide-[#F8FAFC]">
            {docs.map((r, i) => (
              <tr key={i} className="hover:bg-[#F8FAFC]">
                <td className="px-3 py-2 text-[#64748B]">{r.date}</td>
                <td className="px-3 py-2 text-[#475569]">{r.document_no}</td>
                <td className="px-3 py-2"><CcyBadge code={r.currency} /></td>
                <td className="px-3 py-2 text-right font-mono text-[#334155]">{r.exchange_rate}</td>
                <td className="px-3 py-2 text-[#64748B]">{r.rate_source ?? "—"}</td>
                <td className="px-3 py-2">{r.rate_overridden ? <span className="text-amber-600 font-medium">Yes</span> : <span className="text-[#94A3B8]">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Profit & Loss ──────────────────────────────────────────────────────────
// All aggregation is server-side (domain.reporting). The component fetches
// account-level lines and groups them per Companies Act 2013, Schedule III,
// Part II for presentation only.

interface CashPLData {
  revenue: { lines: { account_id?: string; account_name: string; amount_paise: number }[]; total_paise: number };
  operating_expenses: { lines: { account_id?: string; account_name: string; amount_paise: number }[]; total_paise: number };
  net_profit_paise: number;
  start_date: string;
  end_date: string;
}

// Account-level line returned by the backend P&L (accrual & cash).
interface PLApiLine {
  account_id: string;
  account_name: string;
  account_code?: string;
  account_subtype?: string | null;
  amount_paise: number;
}
interface PLApiData {
  revenue: { lines: PLApiLine[]; total_paise: number };
  operating_expenses: { lines: PLApiLine[]; total_paise: number };
  net_profit_paise: number;
}

function ProfitAndLoss({ clientId, financialYear, onDrillDown }: { clientId: string; financialYear: string; onDrillDown: (accountId: string) => void }) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const basis = (searchParams.get("basis") as "accrual" | "cash") ?? "accrual";

  const [balances, setBalances] = useState<AccountBalance[]>([]);
  const [cashPL, setCashPL] = useState<CashPLData | null>(null);
  // Authoritative accrual totals from the backend — never recomputed here.
  const [plTotals, setPlTotals] = useState({ revenue: 0, expenses: 0, net: 0 });
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  // "Compare to prior year" — Schedule III requires the previous year's
  // figures alongside the current year on the P&L face. Fetched lazily, only
  // once the toggle is switched on.
  const [comparePY, setComparePY] = useState(false);
  const prevFY = shiftFY(financialYear, -1);
  const [prevBalances, setPrevBalances] = useState<AccountBalance[]>([]);
  const [prevCashPL, setPrevCashPL] = useState<CashPLData | null>(null);
  const [prevPlTotals, setPrevPlTotals] = useState<{ revenue: number; expenses: number; net: number } | null>(null);
  const [prevLoading, setPrevLoading] = useState(false);

  const updateBasis = (b: "accrual" | "cash") => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("basis", b);
    router.replace(`?${params.toString()}`, { scroll: false });
  };

  const load = useCallback(async (force?: boolean) => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    // Both bases computed server-side from the same posted ledger, scoped to this
    // client (IT Act §44AA). The frontend only passes parameters and groups the
    // returned account lines for display (Schedule III) — no financial math here.
    const { start, end } = fyDateRange(financialYear);
    try {
      const res = (await cachedReport(
        reportKey([clientId, financialYear, basis, "pl"]),
        () => api.accounting.profitLoss({ basis, start_date: start, end_date: end, client_id: clientId }),
        { force },
      )) as { success: boolean; data: PLApiData | null };

      if (basis === "cash") {
        if (res.success && res.data) setCashPL(res.data as unknown as CashPLData);
        else setCashPL(null);
      } else if (res.success && res.data) {
        const d = res.data;
        const toBal = (l: PLApiLine, type: string): AccountBalance => ({
          account_id: l.account_id, account_code: l.account_code ?? "",
          account_name: l.account_name, account_type: type,
          account_subtype: l.account_subtype ?? null, net_paise: l.amount_paise,
        });
        const rows = [
          ...(d.revenue?.lines ?? []).map((l) => toBal(l, "Revenue")),
          ...(d.operating_expenses?.lines ?? []).map((l) => toBal(l, "Expense")),
        ].filter((b) => b.net_paise !== 0).sort((a, b) => a.account_code.localeCompare(b.account_code));
        setBalances(rows);
        setPlTotals({
          revenue: d.revenue?.total_paise ?? 0,
          expenses: d.operating_expenses?.total_paise ?? 0,
          net: d.net_profit_paise ?? 0,
        });
      } else {
        setBalances([]);
        setPlTotals({ revenue: 0, expenses: 0, net: 0 });
      }
    } catch {
      // Backend error/timeout — degrade to empty, never an infinite skeleton (audit M17).
      setCashPL(null);
      setBalances([]);
      setPlTotals({ revenue: 0, expenses: 0, net: 0 });
    } finally {
      setLoading(false); setLoaded(true);
    }
  }, [clientId, financialYear, basis]);

  useEffect(() => { load(); }, [load]);

  const loadPrev = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setPrevLoading(true);
    const { start, end } = fyDateRange(prevFY);
    try {
      const res = (await cachedReport(
        reportKey([clientId, prevFY, basis, "pl"]),
        () => api.accounting.profitLoss({ basis, start_date: start, end_date: end, client_id: clientId }),
      )) as { success: boolean; data: PLApiData | null };
      if (basis === "cash") {
        setPrevCashPL(res.success && res.data ? (res.data as unknown as CashPLData) : null);
        setPrevPlTotals(null);
      } else if (res.success && res.data) {
        const d = res.data;
        const toBal = (l: PLApiLine, type: string): AccountBalance => ({
          account_id: l.account_id, account_code: l.account_code ?? "",
          account_name: l.account_name, account_type: type,
          account_subtype: l.account_subtype ?? null, net_paise: l.amount_paise,
        });
        setPrevBalances([
          ...(d.revenue?.lines ?? []).map((l) => toBal(l, "Revenue")),
          ...(d.operating_expenses?.lines ?? []).map((l) => toBal(l, "Expense")),
        ]);
        setPrevPlTotals({ revenue: d.revenue?.total_paise ?? 0, expenses: d.operating_expenses?.total_paise ?? 0, net: d.net_profit_paise ?? 0 });
      } else {
        setPrevBalances([]);
        setPrevPlTotals({ revenue: 0, expenses: 0, net: 0 });
      }
    } catch {
      setPrevCashPL(null);
      setPrevBalances([]);
      setPrevPlTotals({ revenue: 0, expenses: 0, net: 0 });
    } finally {
      setPrevLoading(false);
    }
  }, [clientId, prevFY, basis]);

  useEffect(() => { if (comparePY) loadPrev(); }, [comparePY, loadPrev]);

  const prevByAccount = useMemo(() => new Map(prevBalances.map((b) => [b.account_id, b.net_paise])), [prevBalances]);
  const prevCashByAccount = useMemo(() => {
    const m = new Map<string, number>();
    if (prevCashPL) {
      prevCashPL.revenue.lines.forEach((l) => { if (l.account_id) m.set(l.account_id, l.amount_paise); });
      prevCashPL.operating_expenses.lines.forEach((l) => { if (l.account_id) m.set(l.account_id, l.amount_paise); });
    }
    return m;
  }, [prevCashPL]);

  const revenue = balances.filter((b) => b.account_type === "Revenue");
  const expenses = balances.filter((b) => b.account_type === "Expense");
  // Grand totals are the backend's authoritative figures; bucket subtotals below
  // are presentation-only Schedule III grouping of the same backend line amounts.
  const totalRevenue = plTotals.revenue;
  const totalExpenses = plTotals.expenses;
  const netPL = plTotals.net;

  const revBuckets = groupBy(revenue, (b) => plBucket(b.account_type, b.account_subtype));
  const expBuckets = groupBy(expenses, (b) => plBucket(b.account_type, b.account_subtype));

  const PL_REV_ORDER = ["Revenue from Operations", "Other Income"];
  const PL_EXP_ORDER = ["Cost of Materials Consumed", "Employee Benefit Expense", "Finance Costs", "Depreciation & Amortisation", "Other Expenses"];

  const BasisToggle = () => (
    <div className="flex rounded border border-[#E2E8F0] overflow-hidden text-xs">
      <button onClick={() => updateBasis("accrual")} className={`px-3 py-1 font-medium transition-colors ${basis === "accrual" ? "bg-[#1E293B] text-white" : "bg-white text-[#64748B] hover:bg-[#F8FAFC]"}`}>Accrual</button>
      <button onClick={() => updateBasis("cash")} className={`px-3 py-1 font-medium border-l border-[#E2E8F0] transition-colors ${basis === "cash" ? "bg-[#1E293B] text-white" : "bg-white text-[#64748B] hover:bg-[#F8FAFC]"}`}>Cash</button>
    </div>
  );

  // CSV export — plain rupee numbers (no ₹ prefix / comma grouping) so the
  // amount column is directly usable as a spreadsheet number.
  const buildPlExportRows = (): { section: string; particulars: string; amount: string }[] => {
    const rows: { section: string; particulars: string; amount: string }[] = [];
    if (basis === "cash") {
      if (!cashPL) return rows;
      cashPL.revenue.lines.forEach((l) => rows.push({ section: "Revenue", particulars: l.account_name, amount: (l.amount_paise / 100).toFixed(2) }));
      cashPL.operating_expenses.lines.forEach((l) => rows.push({ section: "Expenses", particulars: l.account_name, amount: (l.amount_paise / 100).toFixed(2) }));
      rows.push({ section: "", particulars: "Total Revenue", amount: (cashPL.revenue.total_paise / 100).toFixed(2) });
      rows.push({ section: "", particulars: "Total Expenses", amount: (cashPL.operating_expenses.total_paise / 100).toFixed(2) });
      rows.push({ section: "", particulars: cashPL.net_profit_paise >= 0 ? "Net Profit" : "Net Loss", amount: (Math.abs(cashPL.net_profit_paise) / 100).toFixed(2) });
    } else {
      PL_REV_ORDER.forEach((bucket) => {
        (revBuckets[bucket] ?? []).forEach((item) => rows.push({ section: bucket, particulars: item.account_name, amount: (item.net_paise / 100).toFixed(2) }));
      });
      PL_EXP_ORDER.forEach((bucket) => {
        (expBuckets[bucket] ?? []).forEach((item) => rows.push({ section: bucket, particulars: item.account_name, amount: (item.net_paise / 100).toFixed(2) }));
      });
      rows.push({ section: "", particulars: "Total Revenue", amount: (totalRevenue / 100).toFixed(2) });
      rows.push({ section: "", particulars: "Total Expenses", amount: (totalExpenses / 100).toFixed(2) });
      rows.push({ section: "", particulars: netPL >= 0 ? "Net Profit" : "Net Loss", amount: (Math.abs(netPL) / 100).toFixed(2) });
    }
    return rows;
  };
  const plExportColumns: Column<{ section: string; particulars: string; amount: string }>[] = [
    { key: "section", header: "Section", accessor: (r) => r.section },
    { key: "particulars", header: "Particulars", accessor: (r) => r.particulars },
    { key: "amount", header: "Amount (₹)", accessor: (r) => r.amount },
  ];
  const plExportDisabled = !loaded || (basis === "cash" ? !cashPL : balances.length === 0);

  return (
    <div className="space-y-4 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">Statement of Profit & Loss — FY {financialYear}</p>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setComparePY((v) => !v)}
            className={`px-3 py-1.5 text-xs font-medium rounded border transition-colors ${comparePY ? "bg-[#1E293B] text-white border-[#1E293B]" : "bg-white text-[#64748B] border-[#E2E8F0] hover:bg-[#F8FAFC]"}`}
          >
            Compare vs FY {prevFY}
          </button>
          <BasisToggle />
          <button onClick={() => load(true)} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
          <button
            onClick={() => downloadCsv(`profit-and-loss-fy-${financialYear}.csv`, toCsv(buildPlExportRows(), plExportColumns))}
            disabled={plExportDisabled}
            className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"
            title="Export CSV"
          >
            <Download size={13} />
          </button>
          <button onClick={() => window.print()} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]" title="Print"><Printer size={13} /></button>
        </div>
      </div>

      {/* Cash basis disclaimer — IT Act §44AA */}
      {basis === "cash" && (
        <div className="bg-amber-50 border border-amber-200 rounded px-3 py-2 text-xs text-amber-700">
          Cash basis — management reporting only (IT Act §44AA). Revenue shown only when collected; expenses when paid. GST returns are not affected.
        </div>
      )}

      {comparePY && (
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: "Revenue", curr: totalRevenue, prev: prevPlTotals?.revenue },
            { label: "Expenses", curr: totalExpenses, prev: prevPlTotals?.expenses },
            { label: netPL >= 0 ? "Net Profit" : "Net Loss", curr: Math.abs(netPL), prev: prevPlTotals ? Math.abs(prevPlTotals.net) : undefined },
          ].map((s) => (
            <div key={s.label} className="rounded-lg border border-[#F1F5F9] bg-white p-3">
              <p className="text-[10px] text-[#94A3B8] font-medium">{s.label}</p>
              <p className="text-sm font-bold text-[#0F172A] mt-0.5">{fmt(s.curr)}</p>
              <div className="flex items-center justify-between mt-1 text-[10px] text-[#94A3B8]">
                <span>FY {prevFY}: {s.prev !== undefined ? fmt(s.prev) : (prevLoading ? "…" : "—")}</span>
                <ChangeCell curr={s.curr} prev={s.prev} />
              </div>
            </div>
          ))}
        </div>
      )}

      {loading && <div className="h-48 rounded-lg bg-[#F8FAFC] animate-pulse" />}

      {/* Cash basis P&L — simplified flat view (no Schedule III bucketing) */}
      {!loading && loaded && basis === "cash" && cashPL && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-5 py-4 bg-[#F8FAFC] border-b border-[#F1F5F9]">
            <p className="text-xs font-bold text-[#475569] uppercase tracking-wide">Statement of Profit & Loss (Cash Basis)</p>
            <p className="text-[10px] text-[#94A3B8] mt-0.5">For the year ended 31 March {parseInt(financialYear.split("-")[0]) + 1} · Management Report Only</p>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#F1F5F9] text-[#94A3B8] text-[10px]">
                <th className="px-5 py-2 text-left font-semibold">Particulars</th>
                <th className="px-4 py-2 text-right font-semibold">Amount (₹)</th>
                {comparePY && <><th className="px-4 py-2 text-right font-semibold">FY {prevFY} (₹)</th><th className="px-4 py-2 text-right font-semibold">Change</th></>}
              </tr>
            </thead>
            <tbody>
              <tr><td colSpan={comparePY ? 4 : 2} className="px-5 py-2 font-semibold text-[#334155] bg-[#F8FAFC] text-[10px] uppercase tracking-wide">I. Revenue (Collected)</td></tr>
              {cashPL.revenue.lines.map((l, i) => (
                <tr key={i} className={isDrillableAccount(l.account_id) ? "hover:bg-[#F8FAFC] cursor-pointer" : "hover:bg-[#F8FAFC]"} onClick={isDrillableAccount(l.account_id) ? () => onDrillDown(l.account_id as string) : undefined}>
                  <td className={`px-5 py-1.5 pl-10 text-[#334155] ${isDrillableAccount(l.account_id) ? "hover:text-blue-700 hover:underline" : ""}`}>{l.account_name}</td>
                  <td className={`px-4 py-1.5 text-right font-mono text-[#334155] ${isDrillableAccount(l.account_id) ? "hover:text-blue-700 hover:underline" : ""}`}>{fmt(l.amount_paise)}</td>
                  {comparePY && <><td className="px-4 py-1.5 text-right font-mono text-[#94A3B8]">{l.account_id && prevCashByAccount.has(l.account_id) ? fmt(prevCashByAccount.get(l.account_id) as number) : "—"}</td><td className="px-4 py-1.5 text-right"><ChangeCell curr={l.amount_paise} prev={l.account_id ? prevCashByAccount.get(l.account_id) : undefined} /></td></>}
                </tr>
              ))}
              <tr className="border-t border-[#E2E8F0] font-semibold">
                <td className="px-5 py-2.5 text-[#1E293B]">Total Revenue (I)</td>
                <td className="px-4 py-2.5 text-right font-mono text-[#0F172A]">{fmt(cashPL.revenue.total_paise)}</td>
                {comparePY && <><td colSpan={2}></td></>}
              </tr>
              <tr><td colSpan={comparePY ? 4 : 2} className="px-5 py-2 font-semibold text-[#334155] bg-[#F8FAFC] text-[10px] uppercase tracking-wide">II. Expenses (Paid)</td></tr>
              {cashPL.operating_expenses.lines.map((l, i) => (
                <tr key={i} className={isDrillableAccount(l.account_id) ? "hover:bg-[#F8FAFC] cursor-pointer" : "hover:bg-[#F8FAFC]"} onClick={isDrillableAccount(l.account_id) ? () => onDrillDown(l.account_id as string) : undefined}>
                  <td className={`px-5 py-1.5 pl-10 text-[#334155] ${isDrillableAccount(l.account_id) ? "hover:text-blue-700 hover:underline" : ""}`}>{l.account_name}</td>
                  <td className={`px-4 py-1.5 text-right font-mono text-[#334155] ${isDrillableAccount(l.account_id) ? "hover:text-blue-700 hover:underline" : ""}`}>{fmt(l.amount_paise)}</td>
                  {comparePY && <><td className="px-4 py-1.5 text-right font-mono text-[#94A3B8]">{l.account_id && prevCashByAccount.has(l.account_id) ? fmt(prevCashByAccount.get(l.account_id) as number) : "—"}</td><td className="px-4 py-1.5 text-right"><ChangeCell curr={l.amount_paise} prev={l.account_id ? prevCashByAccount.get(l.account_id) : undefined} /></td></>}
                </tr>
              ))}
              <tr className="border-t border-[#E2E8F0] font-semibold">
                <td className="px-5 py-2.5 text-[#1E293B]">Total Expenses (II)</td>
                <td className="px-4 py-2.5 text-right font-mono text-[#0F172A]">{fmt(cashPL.operating_expenses.total_paise)}</td>
                {comparePY && <><td colSpan={2}></td></>}
              </tr>
              <tr className={`border-t-2 border-gray-300 font-bold text-sm ${cashPL.net_profit_paise >= 0 ? "bg-green-50" : "bg-red-50"}`}>
                <td className="px-5 py-3 text-[#0F172A]">{cashPL.net_profit_paise >= 0 ? "III. Profit (I − II)" : "III. Loss (II − I)"}</td>
                <td className={`px-4 py-3 text-right font-mono ${cashPL.net_profit_paise >= 0 ? "text-green-700" : "text-red-700"}`}>{fmt(Math.abs(cashPL.net_profit_paise))}</td>
                {comparePY && <><td colSpan={2}></td></>}
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {/* Accrual basis P&L — Schedule III format */}
      {!loading && loaded && basis === "accrual" && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden print:border-0">
          <div className="px-5 py-4 bg-[#F8FAFC] border-b border-[#F1F5F9] print:bg-white">
            <p className="text-xs font-bold text-[#475569] uppercase tracking-wide">Statement of Profit & Loss</p>
            <p className="text-[10px] text-[#94A3B8] mt-0.5">For the year ended 31 March {parseInt(financialYear.split("-")[0]) + 1}</p>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#F1F5F9] text-[#94A3B8] text-[10px]">
                <th className="px-5 py-2 text-left font-semibold">Particulars</th>
                <th className="px-4 py-2 text-right font-semibold">Amount (₹)</th>
                {comparePY && <><th className="px-4 py-2 text-right font-semibold">FY {prevFY} (₹)</th><th className="px-4 py-2 text-right font-semibold">Change</th></>}
              </tr>
            </thead>
            <tbody>
              <tr><td colSpan={comparePY ? 4 : 2} className="px-5 py-2 font-semibold text-[#334155] bg-[#F8FAFC] text-[10px] uppercase tracking-wide">I. Revenue</td></tr>
              {PL_REV_ORDER.map((bucket) => {
                const items = revBuckets[bucket] ?? [];
                if (items.length === 0) return null;
                const total = items.reduce((s, b) => s + b.net_paise, 0);
                return <PLSection key={bucket} label={bucket} items={items} total={total} onDrillDown={onDrillDown} comparePY={comparePY} prevByAccount={prevByAccount} />;
              })}
              <tr className="border-t border-[#E2E8F0] font-semibold">
                <td className="px-5 py-2.5 text-[#1E293B]">Total Revenue (I)</td>
                <td className="px-4 py-2.5 text-right font-mono text-[#0F172A]">{fmt(totalRevenue)}</td>
                {comparePY && <><td colSpan={2}></td></>}
              </tr>
              <tr><td colSpan={comparePY ? 4 : 2} className="px-5 py-2 font-semibold text-[#334155] bg-[#F8FAFC] text-[10px] uppercase tracking-wide">II. Expenses</td></tr>
              {PL_EXP_ORDER.map((bucket) => {
                const items = expBuckets[bucket] ?? [];
                if (items.length === 0) return null;
                const total = items.reduce((s, b) => s + b.net_paise, 0);
                return <PLSection key={bucket} label={bucket} items={items} total={total} onDrillDown={onDrillDown} comparePY={comparePY} prevByAccount={prevByAccount} />;
              })}
              <tr className="border-t border-[#E2E8F0] font-semibold">
                <td className="px-5 py-2.5 text-[#1E293B]">Total Expenses (II)</td>
                <td className="px-4 py-2.5 text-right font-mono text-[#0F172A]">{fmt(totalExpenses)}</td>
                {comparePY && <><td colSpan={2}></td></>}
              </tr>
              <tr className={`border-t-2 border-gray-300 font-bold text-sm ${netPL >= 0 ? "bg-green-50" : "bg-red-50"}`}>
                <td className="px-5 py-3 text-[#0F172A]">{netPL >= 0 ? "III. Profit for the Year (I − II)" : "III. Loss for the Year (II − I)"}</td>
                <td className={`px-4 py-3 text-right font-mono ${netPL >= 0 ? "text-green-700" : "text-red-700"}`}>{fmt(Math.abs(netPL))}</td>
                {comparePY && <><td colSpan={2}></td></>}
              </tr>
            </tbody>
          </table>
          {balances.length === 0 && <div className="text-center py-12 text-[#94A3B8] text-sm">No posted entries with Revenue or Expense accounts in FY {financialYear}.</div>}
        </div>
      )}
    </div>
  );
}

function PLSection({
  label, items, total, onDrillDown, comparePY, prevByAccount,
}: {
  label: string; items: AccountBalance[]; total: number; onDrillDown: (accountId: string) => void;
  comparePY: boolean; prevByAccount: Map<string, number>;
}) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <tr className="cursor-pointer hover:bg-[#F8FAFC]" onClick={() => setOpen((o) => !o)}>
        <td className="px-5 py-2 text-[#334155] font-medium pl-8">{label}</td>
        <td className="px-4 py-2 text-right font-mono text-[#334155]">{fmt(total)}</td>
        {comparePY && <><td colSpan={2}></td></>}
      </tr>
      {open && items.map((item) => (
        <tr key={item.account_id} className="text-[#94A3B8] hover:bg-[#F8FAFC] cursor-pointer" onClick={() => onDrillDown(item.account_id)}>
          <td className="px-5 py-1.5 pl-14 hover:text-blue-700 hover:underline">{item.account_name}</td>
          <td className="px-4 py-1.5 text-right font-mono hover:text-blue-700 hover:underline">{fmt(item.net_paise)}</td>
          {comparePY && <>
            <td className="px-4 py-1.5 text-right font-mono">{prevByAccount.has(item.account_id) ? fmt(prevByAccount.get(item.account_id) as number) : "—"}</td>
            <td className="px-4 py-1.5 text-right"><ChangeCell curr={item.net_paise} prev={prevByAccount.get(item.account_id)} /></td>
          </>}
        </tr>
      ))}
    </>
  );
}

// ── Balance Sheet ──────────────────────────────────────────────────────────
// Cumulative balances up to FY end date.
// Companies Act 2013, Schedule III, Part I.

interface CashBSSection { label: string; lines: { account_id?: string; account_name: string; balance_paise: number }[]; total_paise: number }
interface CashBSData {
  assets: CashBSSection[];
  liabilities: CashBSSection[];
  equity: CashBSSection[];
  total_assets_paise: number;
  total_liabilities_equity_paise: number;
  is_balanced: boolean;
}

// Account-level shapes returned by the backend balance sheet (accrual & cash).
interface BSApiLine {
  account_id?: string;
  account_name: string;
  account_code?: string;
  account_subtype?: string | null;
  balance_paise: number;
}
interface BSApiSection { label: string; lines: BSApiLine[]; total_paise: number }
interface BSApiData {
  assets: BSApiSection[];
  liabilities: BSApiSection[];
  equity: BSApiSection[];
  total_assets_paise: number;
  total_liabilities_equity_paise: number;
  is_balanced: boolean;
}

function BalanceSheet({ clientId, financialYear, onDrillDown }: { clientId: string; financialYear: string; onDrillDown: (accountId: string) => void }) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const basis = (searchParams.get("basis") as "accrual" | "cash") ?? "accrual";

  const [balances, setBalances] = useState<AccountBalance[]>([]);
  const [cashBS, setCashBS] = useState<CashBSData | null>(null);
  // Authoritative accrual totals from the backend — never recomputed here.
  const [bsTotals, setBsTotals] = useState({ assets: 0, liab: 0, equity: 0, liabEquity: 0, balanced: true });
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  // "Compare to prior year" — Schedule III requires the previous year's
  // figures alongside the current year on the Balance Sheet face.
  const [comparePY, setComparePY] = useState(false);
  const prevFY = shiftFY(financialYear, -1);
  const [prevBalances, setPrevBalances] = useState<AccountBalance[]>([]);
  const [prevCashBS, setPrevCashBS] = useState<CashBSData | null>(null);
  const [prevBsTotals, setPrevBsTotals] = useState<{ assets: number; liab: number; equity: number } | null>(null);
  const [prevLoading, setPrevLoading] = useState(false);

  const updateBasis = (b: "accrual" | "cash") => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("basis", b);
    router.replace(`?${params.toString()}`, { scroll: false });
  };

  const load = useCallback(async (force?: boolean) => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    // Both bases computed server-side from the same posted ledger, scoped to this
    // client (Companies Act §128). Retained earnings / net profit is computed in
    // the backend and returned in the equity section. The frontend only groups
    // the returned balances for Schedule III presentation — no financial math.
    const { end } = fyDateRange(financialYear);
    try {
      const res = (await cachedReport(
        reportKey([clientId, financialYear, basis, "bs"]),
        () => api.accounting.balanceSheet({ basis, as_of_date: end, client_id: clientId }),
        { force },
      )) as { success: boolean; data: BSApiData | null };

      if (basis === "cash") {
        if (res.success && res.data) setCashBS(res.data as unknown as CashBSData);
        else setCashBS(null);
      } else if (res.success && res.data) {
        const d = res.data;
        const fromSection = (secs: BSApiSection[] | undefined, type: string): AccountBalance[] =>
          (secs ?? []).flatMap((s) => (s.lines ?? []).map((l) => ({
            account_id: l.account_id ?? l.account_name, account_code: l.account_code ?? "",
            account_name: l.account_name, account_type: type,
            account_subtype: l.account_subtype ?? null, net_paise: l.balance_paise,
          })));
        setBalances([
          ...fromSection(d.assets, "Asset"),
          ...fromSection(d.liabilities, "Liability"),
          ...fromSection(d.equity, "Equity"),
        ].sort((a, b) => a.account_code.localeCompare(b.account_code)));
        setBsTotals({
          assets: d.total_assets_paise ?? 0,
          liab: d.liabilities?.[0]?.total_paise ?? 0,
          equity: d.equity?.[0]?.total_paise ?? 0,
          liabEquity: d.total_liabilities_equity_paise ?? 0,
          balanced: d.is_balanced ?? false,
        });
      } else {
        setBalances([]);
        setBsTotals({ assets: 0, liab: 0, equity: 0, liabEquity: 0, balanced: true });
      }
    } catch {
      // Backend error/timeout — degrade to empty, never an infinite skeleton (audit M17).
      setCashBS(null);
      setBalances([]);
      setBsTotals({ assets: 0, liab: 0, equity: 0, liabEquity: 0, balanced: true });
    } finally {
      setLoading(false); setLoaded(true);
    }
  }, [clientId, financialYear, basis]);

  useEffect(() => { load(); }, [load]);

  const loadPrev = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setPrevLoading(true);
    const { end } = fyDateRange(prevFY);
    try {
      const res = (await cachedReport(
        reportKey([clientId, prevFY, basis, "bs"]),
        () => api.accounting.balanceSheet({ basis, as_of_date: end, client_id: clientId }),
      )) as { success: boolean; data: BSApiData | null };
      if (basis === "cash") {
        setPrevCashBS(res.success && res.data ? (res.data as unknown as CashBSData) : null);
        setPrevBsTotals(null);
      } else if (res.success && res.data) {
        const d = res.data;
        const fromSection = (secs: BSApiSection[] | undefined, type: string): AccountBalance[] =>
          (secs ?? []).flatMap((s) => (s.lines ?? []).map((l) => ({
            account_id: l.account_id ?? l.account_name, account_code: l.account_code ?? "",
            account_name: l.account_name, account_type: type,
            account_subtype: l.account_subtype ?? null, net_paise: l.balance_paise,
          })));
        setPrevBalances([
          ...fromSection(d.assets, "Asset"),
          ...fromSection(d.liabilities, "Liability"),
          ...fromSection(d.equity, "Equity"),
        ]);
        setPrevBsTotals({
          assets: d.total_assets_paise ?? 0,
          liab: d.liabilities?.[0]?.total_paise ?? 0,
          equity: d.equity?.[0]?.total_paise ?? 0,
        });
      } else {
        setPrevBalances([]);
        setPrevBsTotals({ assets: 0, liab: 0, equity: 0 });
      }
    } catch {
      setPrevCashBS(null);
      setPrevBalances([]);
      setPrevBsTotals({ assets: 0, liab: 0, equity: 0 });
    } finally {
      setPrevLoading(false);
    }
  }, [clientId, prevFY, basis]);

  useEffect(() => { if (comparePY) loadPrev(); }, [comparePY, loadPrev]);

  const prevByAccount = useMemo(() => new Map(prevBalances.map((b) => [b.account_id, b.net_paise])), [prevBalances]);
  const prevCashByAccount = useMemo(() => {
    const m = new Map<string, number>();
    if (prevCashBS) {
      [...prevCashBS.equity, ...prevCashBS.liabilities, ...prevCashBS.assets].forEach((sec) =>
        sec.lines.forEach((l) => { if (l.account_id) m.set(l.account_id, l.balance_paise); }));
    }
    return m;
  }, [prevCashBS]);

  // Line inclusion mirrors the backend section contents (non-zero balances) so
  // the displayed lines and the backend totals below always reconcile.
  const assets = balances.filter((b) => b.account_type === "Asset" && b.net_paise !== 0);
  const liabilities = balances.filter((b) => b.account_type === "Liability" && b.net_paise !== 0);
  const equity = balances.filter((b) => b.account_type === "Equity");

  // Grand totals are the backend's authoritative figures; bucket subtotals below
  // are presentation-only Schedule III grouping of the same backend line amounts.
  const totalAssets = bsTotals.assets;
  const totalLiab = bsTotals.liab;
  const totalEquity = bsTotals.equity;
  const isBalanced = bsTotals.balanced;

  const assetBuckets = groupBy(assets, (b) => bsBucket(b.account_type, b.account_subtype));
  const liabBuckets = groupBy(liabilities, (b) => bsBucket(b.account_type, b.account_subtype));
  const equityBuckets = groupBy(equity, (b) => bsBucket(b.account_type, b.account_subtype));

  const BS_ASSET_ORDER = ["Tangible Assets", "Intangible Assets", "Non-Current Investments", "Inventories", "Trade Receivables", "Short-term Loans & Advances", "Cash & Cash Equivalents", "Other Current Assets"];
  const BS_LIAB_ORDER = ["Long-term Borrowings", "Short-term Borrowings", "Trade Payables", "Tax Liabilities", "Other Current Liabilities"];
  const BS_EQ_ORDER = ["Share Capital", "Reserves & Surplus"];

  const BasisToggle = () => (
    <div className="flex rounded border border-[#E2E8F0] overflow-hidden text-xs">
      <button onClick={() => updateBasis("accrual")} className={`px-3 py-1 font-medium transition-colors ${basis === "accrual" ? "bg-[#1E293B] text-white" : "bg-white text-[#64748B] hover:bg-[#F8FAFC]"}`}>Accrual</button>
      <button onClick={() => updateBasis("cash")} className={`px-3 py-1 font-medium border-l border-[#E2E8F0] transition-colors ${basis === "cash" ? "bg-[#1E293B] text-white" : "bg-white text-[#64748B] hover:bg-[#F8FAFC]"}`}>Cash</button>
    </div>
  );

  // CSV export — plain rupee numbers (no ₹ prefix / comma grouping) so the
  // amount column is directly usable as a spreadsheet number.
  const buildBsExportRows = (): { section: string; particulars: string; amount: string }[] => {
    const rows: { section: string; particulars: string; amount: string }[] = [];
    if (basis === "cash") {
      if (!cashBS) return rows;
      [...cashBS.equity, ...cashBS.liabilities, ...cashBS.assets].forEach((sec) => {
        sec.lines.forEach((l) => rows.push({ section: sec.label, particulars: l.account_name, amount: (l.balance_paise / 100).toFixed(2) }));
      });
      rows.push({ section: "", particulars: "Total Assets", amount: (cashBS.total_assets_paise / 100).toFixed(2) });
      rows.push({ section: "", particulars: "Total Liabilities", amount: ((cashBS.liabilities[0]?.total_paise ?? 0) / 100).toFixed(2) });
      rows.push({ section: "", particulars: "Total Equity", amount: ((cashBS.equity[0]?.total_paise ?? 0) / 100).toFixed(2) });
    } else {
      BS_EQ_ORDER.forEach((bucket) => {
        (equityBuckets[bucket] ?? []).forEach((item) => rows.push({ section: bucket, particulars: item.account_name, amount: (item.net_paise / 100).toFixed(2) }));
      });
      BS_LIAB_ORDER.forEach((bucket) => {
        (liabBuckets[bucket] ?? []).forEach((item) => rows.push({ section: bucket, particulars: item.account_name, amount: (item.net_paise / 100).toFixed(2) }));
      });
      BS_ASSET_ORDER.forEach((bucket) => {
        (assetBuckets[bucket] ?? []).forEach((item) => rows.push({ section: bucket, particulars: item.account_name, amount: (item.net_paise / 100).toFixed(2) }));
      });
      rows.push({ section: "", particulars: "Total Assets", amount: (totalAssets / 100).toFixed(2) });
      rows.push({ section: "", particulars: "Total Liabilities", amount: (totalLiab / 100).toFixed(2) });
      rows.push({ section: "", particulars: "Total Equity", amount: (totalEquity / 100).toFixed(2) });
    }
    return rows;
  };
  const bsExportColumns: Column<{ section: string; particulars: string; amount: string }>[] = [
    { key: "section", header: "Section", accessor: (r) => r.section },
    { key: "particulars", header: "Particulars", accessor: (r) => r.particulars },
    { key: "amount", header: "Amount (₹)", accessor: (r) => r.amount },
  ];
  const bsExportDisabled = !loaded || (basis === "cash" ? !cashBS : balances.length === 0);

  return (
    <div className="space-y-4 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">Balance Sheet — as at 31 March {parseInt(financialYear.split("-")[0]) + 1}</p>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setComparePY((v) => !v)}
            className={`px-3 py-1.5 text-xs font-medium rounded border transition-colors ${comparePY ? "bg-[#1E293B] text-white border-[#1E293B]" : "bg-white text-[#64748B] border-[#E2E8F0] hover:bg-[#F8FAFC]"}`}
          >
            Compare vs FY {prevFY}
          </button>
          <BasisToggle />
          <button onClick={() => load(true)} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
          <button
            onClick={() => downloadCsv(`balance-sheet-fy-${financialYear}.csv`, toCsv(buildBsExportRows(), bsExportColumns))}
            disabled={bsExportDisabled}
            className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"
            title="Export CSV"
          >
            <Download size={13} />
          </button>
          <button onClick={() => window.print()} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]" title="Print"><Printer size={13} /></button>
        </div>
      </div>

      {/* Cash basis disclaimer — Companies Act §128 */}
      {basis === "cash" && (
        <div className="bg-amber-50 border border-amber-200 rounded px-3 py-2 text-xs text-amber-700">
          Cash basis — management reporting only (IT Act §145). Companies Act §128 requires accrual for statutory accounts. Unpaid receivables and payables are excluded from this view.
        </div>
      )}

      {comparePY && (
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: "Total Assets", curr: totalAssets, prev: prevBsTotals?.assets },
            { label: "Total Liabilities", curr: totalLiab, prev: prevBsTotals?.liab },
            { label: "Total Equity", curr: totalEquity, prev: prevBsTotals?.equity },
          ].map((s) => (
            <div key={s.label} className="rounded-lg border border-[#F1F5F9] bg-white p-3">
              <p className="text-[10px] text-[#94A3B8] font-medium">{s.label}</p>
              <p className="text-sm font-bold text-[#0F172A] mt-0.5">{fmt(s.curr)}</p>
              <div className="flex items-center justify-between mt-1 text-[10px] text-[#94A3B8]">
                <span>FY {prevFY}: {s.prev !== undefined ? fmt(s.prev) : (prevLoading ? "…" : "—")}</span>
                <ChangeCell curr={s.curr} prev={s.prev} />
              </div>
            </div>
          ))}
        </div>
      )}

      {loading && <div className="h-48 rounded-lg bg-[#F8FAFC] animate-pulse" />}

      {/* Cash basis balance sheet — simplified flat view */}
      {!loading && loaded && basis === "cash" && cashBS && (
        <div className="space-y-4">
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#F1F5F9]">
              <p className="text-xs font-bold text-[#475569] uppercase tracking-wide">I. Equity & Liabilities (Cash Basis)</p>
            </div>
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8] text-[10px]">
                  <th className="px-5 py-2 text-left font-semibold">Particulars</th>
                  <th className="px-4 py-2 text-right font-semibold">Amount (₹)</th>
                  {comparePY && <><th className="px-4 py-2 text-right font-semibold">FY {prevFY} (₹)</th><th className="px-4 py-2 text-right font-semibold">Change</th></>}
                </tr>
              </thead>
              <tbody>
                <tr><td colSpan={comparePY ? 4 : 2} className="px-5 py-2 font-semibold text-[#334155] bg-[#F8FAFC] text-[10px] uppercase tracking-wide">(A) Equity</td></tr>
                {(cashBS.equity[0]?.lines ?? []).map((l, i) => (
                  <tr key={i} className={isDrillableAccount(l.account_id) ? "hover:bg-[#F8FAFC] cursor-pointer" : "hover:bg-[#F8FAFC]"} onClick={isDrillableAccount(l.account_id) ? () => onDrillDown(l.account_id as string) : undefined}>
                    <td className={`px-5 py-1.5 pl-10 text-[#334155] ${isDrillableAccount(l.account_id) ? "hover:text-blue-700 hover:underline" : ""}`}>{l.account_name}</td>
                    <td className={`px-4 py-1.5 text-right font-mono text-[#334155] ${isDrillableAccount(l.account_id) ? "hover:text-blue-700 hover:underline" : ""}`}>{fmt(l.balance_paise)}</td>
                    {comparePY && <><td className="px-4 py-1.5 text-right font-mono text-[#94A3B8]">{l.account_id && prevCashByAccount.has(l.account_id) ? fmt(prevCashByAccount.get(l.account_id) as number) : "—"}</td><td className="px-4 py-1.5 text-right"><ChangeCell curr={l.balance_paise} prev={l.account_id ? prevCashByAccount.get(l.account_id) : undefined} /></td></>}
                  </tr>
                ))}
                <tr className="border-t border-[#E2E8F0] font-semibold"><td className="px-5 py-2.5 text-[#1E293B]">Total Equity</td><td className="px-4 py-2.5 text-right font-mono text-[#0F172A]">{fmt(cashBS.equity[0]?.total_paise ?? 0)}</td>{comparePY && <><td colSpan={2}></td></>}</tr>
                <tr><td colSpan={comparePY ? 4 : 2} className="px-5 py-2 font-semibold text-[#334155] bg-[#F8FAFC] text-[10px] uppercase tracking-wide">(B) Liabilities</td></tr>
                {(cashBS.liabilities[0]?.lines ?? []).map((l, i) => (
                  <tr key={i} className={isDrillableAccount(l.account_id) ? "hover:bg-[#F8FAFC] cursor-pointer" : "hover:bg-[#F8FAFC]"} onClick={isDrillableAccount(l.account_id) ? () => onDrillDown(l.account_id as string) : undefined}>
                    <td className={`px-5 py-1.5 pl-10 text-[#334155] ${isDrillableAccount(l.account_id) ? "hover:text-blue-700 hover:underline" : ""}`}>{l.account_name}</td>
                    <td className={`px-4 py-1.5 text-right font-mono text-[#334155] ${isDrillableAccount(l.account_id) ? "hover:text-blue-700 hover:underline" : ""}`}>{fmt(l.balance_paise)}</td>
                    {comparePY && <><td className="px-4 py-1.5 text-right font-mono text-[#94A3B8]">{l.account_id && prevCashByAccount.has(l.account_id) ? fmt(prevCashByAccount.get(l.account_id) as number) : "—"}</td><td className="px-4 py-1.5 text-right"><ChangeCell curr={l.balance_paise} prev={l.account_id ? prevCashByAccount.get(l.account_id) : undefined} /></td></>}
                  </tr>
                ))}
                <tr className="border-t border-[#E2E8F0] font-semibold"><td className="px-5 py-2.5 text-[#1E293B]">Total Liabilities</td><td className="px-4 py-2.5 text-right font-mono text-[#0F172A]">{fmt(cashBS.liabilities[0]?.total_paise ?? 0)}</td>{comparePY && <><td colSpan={2}></td></>}</tr>
                <tr className="border-t-2 border-gray-300 font-bold bg-[#F8FAFC]"><td className="px-5 py-3 text-[#0F172A] text-sm">Total Equity & Liabilities</td><td className="px-4 py-3 text-right font-mono text-[#0F172A] text-sm">{fmt(cashBS.total_liabilities_equity_paise)}</td>{comparePY && <><td colSpan={2}></td></>}</tr>
              </tbody>
            </table>
          </div>
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#F1F5F9]">
              <p className="text-xs font-bold text-[#475569] uppercase tracking-wide">II. Assets (Cash Basis)</p>
            </div>
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8] text-[10px]">
                  <th className="px-5 py-2 text-left font-semibold">Particulars</th>
                  <th className="px-4 py-2 text-right font-semibold">Amount (₹)</th>
                  {comparePY && <><th className="px-4 py-2 text-right font-semibold">FY {prevFY} (₹)</th><th className="px-4 py-2 text-right font-semibold">Change</th></>}
                </tr>
              </thead>
              <tbody>
                {(cashBS.assets[0]?.lines ?? []).map((l, i) => (
                  <tr key={i} className={isDrillableAccount(l.account_id) ? "hover:bg-[#F8FAFC] cursor-pointer" : "hover:bg-[#F8FAFC]"} onClick={isDrillableAccount(l.account_id) ? () => onDrillDown(l.account_id as string) : undefined}>
                    <td className={`px-5 py-1.5 pl-10 text-[#334155] ${isDrillableAccount(l.account_id) ? "hover:text-blue-700 hover:underline" : ""}`}>{l.account_name}</td>
                    <td className={`px-4 py-1.5 text-right font-mono text-[#334155] ${isDrillableAccount(l.account_id) ? "hover:text-blue-700 hover:underline" : ""}`}>{fmt(l.balance_paise)}</td>
                    {comparePY && <><td className="px-4 py-1.5 text-right font-mono text-[#94A3B8]">{l.account_id && prevCashByAccount.has(l.account_id) ? fmt(prevCashByAccount.get(l.account_id) as number) : "—"}</td><td className="px-4 py-1.5 text-right"><ChangeCell curr={l.balance_paise} prev={l.account_id ? prevCashByAccount.get(l.account_id) : undefined} /></td></>}
                  </tr>
                ))}
                <tr className="border-t-2 border-gray-300 font-bold bg-[#F8FAFC]"><td className="px-5 py-3 text-[#0F172A] text-sm">Total Assets</td><td className="px-4 py-3 text-right font-mono text-[#0F172A] text-sm">{fmt(cashBS.total_assets_paise)}</td>{comparePY && <><td colSpan={2}></td></>}</tr>
              </tbody>
            </table>
          </div>
          <div className={`rounded-lg px-4 py-3 text-xs font-medium ${cashBS.is_balanced ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
            {cashBS.is_balanced ? "✓ Balance Sheet balances — Assets = Equity + Liabilities" : "✗ Balance Sheet out of balance — check for errors"}
          </div>
        </div>
      )}

      {/* Accrual balance sheet — Schedule III format */}
      {!loading && loaded && basis === "accrual" && (
        <div className="space-y-4">
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#F1F5F9]">
              <p className="text-xs font-bold text-[#475569] uppercase tracking-wide">I. Equity & Liabilities</p>
            </div>
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8] text-[10px]">
                  <th className="px-5 py-2 text-left font-semibold">Particulars</th>
                  <th className="px-4 py-2 text-right font-semibold">Amount (₹)</th>
                  {comparePY && <><th className="px-4 py-2 text-right font-semibold">FY {prevFY} (₹)</th><th className="px-4 py-2 text-right font-semibold">Change</th></>}
                </tr>
              </thead>
              <tbody>
                <tr><td colSpan={comparePY ? 4 : 2} className="px-5 py-2 font-semibold text-[#334155] bg-[#F8FAFC] text-[10px] uppercase tracking-wide">(A) Equity</td></tr>
                {BS_EQ_ORDER.map((bucket) => { const items = equityBuckets[bucket] ?? []; if (!items.length) return null; return <BSSectionRows key={bucket} label={bucket} items={items} onDrillDown={onDrillDown} comparePY={comparePY} prevByAccount={prevByAccount} />; })}
                {equityBuckets["Capital Account"] && <BSSectionRows label="Capital Account" items={equityBuckets["Capital Account"]} onDrillDown={onDrillDown} comparePY={comparePY} prevByAccount={prevByAccount} />}
                <tr className="border-t border-[#E2E8F0] font-semibold"><td className="px-5 py-2.5 text-[#1E293B]">Total Equity</td><td className="px-4 py-2.5 text-right font-mono text-[#0F172A]">{fmt(totalEquity)}</td>{comparePY && <><td colSpan={2}></td></>}</tr>
                <tr><td colSpan={comparePY ? 4 : 2} className="px-5 py-2 font-semibold text-[#334155] bg-[#F8FAFC] text-[10px] uppercase tracking-wide">(B) Liabilities</td></tr>
                {BS_LIAB_ORDER.map((bucket) => { const items = liabBuckets[bucket] ?? []; if (!items.length) return null; return <BSSectionRows key={bucket} label={bucket} items={items} onDrillDown={onDrillDown} comparePY={comparePY} prevByAccount={prevByAccount} />; })}
                <tr className="border-t border-[#E2E8F0] font-semibold"><td className="px-5 py-2.5 text-[#1E293B]">Total Liabilities</td><td className="px-4 py-2.5 text-right font-mono text-[#0F172A]">{fmt(totalLiab)}</td>{comparePY && <><td colSpan={2}></td></>}</tr>
                <tr className="border-t-2 border-gray-300 font-bold bg-[#F8FAFC]"><td className="px-5 py-3 text-[#0F172A] text-sm">Total Equity & Liabilities</td><td className="px-4 py-3 text-right font-mono text-[#0F172A] text-sm">{fmt(totalLiab + totalEquity)}</td>{comparePY && <><td colSpan={2}></td></>}</tr>
              </tbody>
            </table>
          </div>
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#F1F5F9]">
              <p className="text-xs font-bold text-[#475569] uppercase tracking-wide">II. Assets</p>
            </div>
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8] text-[10px]">
                  <th className="px-5 py-2 text-left font-semibold">Particulars</th>
                  <th className="px-4 py-2 text-right font-semibold">Amount (₹)</th>
                  {comparePY && <><th className="px-4 py-2 text-right font-semibold">FY {prevFY} (₹)</th><th className="px-4 py-2 text-right font-semibold">Change</th></>}
                </tr>
              </thead>
              <tbody>
                {BS_ASSET_ORDER.map((bucket) => { const items = assetBuckets[bucket] ?? []; if (!items.length) return null; return <BSSectionRows key={bucket} label={bucket} items={items} onDrillDown={onDrillDown} comparePY={comparePY} prevByAccount={prevByAccount} />; })}
                <tr className="border-t-2 border-gray-300 font-bold bg-[#F8FAFC]"><td className="px-5 py-3 text-[#0F172A] text-sm">Total Assets</td><td className="px-4 py-3 text-right font-mono text-[#0F172A] text-sm">{fmt(totalAssets)}</td>{comparePY && <><td colSpan={2}></td></>}</tr>
              </tbody>
            </table>
          </div>
          <div className={`rounded-lg px-4 py-3 text-xs font-medium ${isBalanced ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
            {isBalanced ? "✓ Balance Sheet balances — Assets = Equity + Liabilities" : `✗ Out of balance by ${fmt(Math.abs(totalAssets - totalLiab - totalEquity))} — check for unposted entries`}
          </div>
          {balances.length === 0 && <div className="text-center py-8 text-[#94A3B8] text-sm">No posted journal entries found for this client.</div>}
        </div>
      )}
    </div>
  );
}

function BSSectionRows({
  label, items, onDrillDown, comparePY, prevByAccount,
}: {
  label: string; items: AccountBalance[]; onDrillDown: (accountId: string) => void;
  comparePY: boolean; prevByAccount: Map<string, number>;
}) {
  const [open, setOpen] = useState(true);
  const total = items.reduce((s, b) => s + b.net_paise, 0);
  return (
    <>
      <tr className="cursor-pointer hover:bg-[#F8FAFC]" onClick={() => setOpen((o) => !o)}>
        <td className="px-5 py-2 text-[#334155] font-medium pl-8">{label}</td>
        <td className="px-4 py-2 text-right font-mono text-[#334155]">{fmt(total)}</td>
        {comparePY && <><td colSpan={2}></td></>}
      </tr>
      {open && items.map((item) => {
        const drillable = isDrillableAccount(item.account_id);
        return (
          <tr key={item.account_id} className={drillable ? "text-[#94A3B8] hover:bg-[#F8FAFC] cursor-pointer" : "text-[#94A3B8]"} onClick={drillable ? () => onDrillDown(item.account_id) : undefined}>
            <td className={`px-5 py-1.5 pl-14 ${drillable ? "hover:text-blue-700 hover:underline" : ""}`}>{item.account_name}</td>
            <td className={`px-4 py-1.5 text-right font-mono ${drillable ? "hover:text-blue-700 hover:underline" : ""}`}>{fmt(item.net_paise)}</td>
            {comparePY && <>
              <td className="px-4 py-1.5 text-right font-mono">{prevByAccount.has(item.account_id) ? fmt(prevByAccount.get(item.account_id) as number) : "—"}</td>
              <td className="px-4 py-1.5 text-right"><ChangeCell curr={item.net_paise} prev={prevByAccount.get(item.account_id)} /></td>
            </>}
          </tr>
        );
      })}
    </>
  );
}

// ── Cash Flow Statement ────────────────────────────────────────────────────
// AS-3 (indirect), Companies Act 2013 Schedule III. ALL classification and
// arithmetic are server-side (domain.reporting); this component only passes the
// period + client_id and renders the authoritative response (CLAUDE.md).

interface CFLine { account_id: string; account_name: string; amount_paise: number }
interface CFSection { label: string; lines: CFLine[]; total_paise: number }
interface CFData {
  start_date: string;
  end_date: string;
  operating: CFSection;
  investing: CFSection;
  financing: CFSection;
  net_change_paise: number;
  opening_cash_paise: number;
  closing_cash_paise: number;
  reconciles: boolean;
  non_cash_excluded_count: number;
  operating_reconciliation: {
    net_profit_paise: number;
    non_operating_adjust_paise: number;
    depreciation_addback_paise: number;
    working_capital_change_paise: number;
    net_cash_operating_paise: number;
    ties_out: boolean;
  };
}

// Sign-preserving money format (cash flow direction matters — inflow vs outflow).
// The shared formatter already preserves the sign.
function fmtSigned(paise: number): string {
  return formatPaise(paise);
}

function CFSectionBlock({ title, section }: { title: string; section: CFSection }) {
  const pos = section.total_paise >= 0;
  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
      <div className={`px-5 py-3 border-b border-gray-50 flex items-center justify-between ${pos ? "bg-green-50/50" : "bg-red-50/50"}`}>
        <h3 className="text-xs font-semibold text-[#334155]">{title}</h3>
        <span className={`text-sm font-bold ${pos ? "text-green-700" : "text-red-700"}`}>{fmtSigned(section.total_paise)}</span>
      </div>
      {section.lines.length === 0 ? (
        <p className="px-5 py-4 text-xs text-[#94A3B8]">No transactions in this category</p>
      ) : (
        <table className="w-full text-xs">
          <tbody className="divide-y divide-[#F8FAFC]">
            {section.lines.map((l) => (
              <tr key={l.account_id} className="hover:bg-[#F8FAFC]">
                <td className="px-5 py-2 text-[#334155]">{l.account_name}</td>
                <td className={`px-5 py-2 text-right font-mono font-medium ${l.amount_paise >= 0 ? "text-green-700" : "text-red-700"}`}>{fmtSigned(l.amount_paise)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-[#E2E8F0] bg-[#F8FAFC]">
              <td className="px-5 py-2 text-xs font-semibold text-[#334155]">Net Cash</td>
              <td className={`px-5 py-2 text-right font-mono text-sm font-bold ${pos ? "text-green-700" : "text-red-700"}`}>{fmtSigned(section.total_paise)}</td>
            </tr>
          </tfoot>
        </table>
      )}
    </div>
  );
}

function CashFlow({ clientId, financialYear }: { clientId: string; financialYear: string }) {
  const [cf, setCf] = useState<CFData | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async (force?: boolean) => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    // Scoped to THIS client (each client is a separate entity — never aggregated
    // across the firm). A cash flow statement is intrinsically actual-cash; we
    // request the accrual stream because the operating reconciliation uses the
    // accrual P&L. All figures come from the backend AS-3 engine.
    const { start, end } = fyDateRange(financialYear);
    try {
      const res = (await cachedReport(
        reportKey([clientId, financialYear, "accrual", "cf"]),
        () => api.accounting.cashFlow({ basis: "accrual", start_date: start, end_date: end, client_id: clientId }),
        { force },
      )) as { success: boolean; data: CFData | null };
      setCf(res.success && res.data ? res.data : null);
    } catch {
      // Backend error/timeout — degrade to empty, never an infinite skeleton (audit M17).
      setCf(null);
    } finally {
      setLoading(false); setLoaded(true);
    }
  }, [clientId, financialYear]);

  useEffect(() => { load(); }, [load]);

  const r = cf?.operating_reconciliation;

  // CSV export — plain rupee numbers (no ₹ prefix / comma grouping) so the
  // amount column is directly usable as a spreadsheet number.
  const buildCfExportRows = (): { section: string; particulars: string; amount: string }[] => {
    if (!cf) return [];
    const rows: { section: string; particulars: string; amount: string }[] = [];
    const sections: { label: string; section: CFSection }[] = [
      { label: "Operating Activities", section: cf.operating },
      { label: "Investing Activities", section: cf.investing },
      { label: "Financing Activities", section: cf.financing },
    ];
    sections.forEach(({ label, section }) => {
      section.lines.forEach((l) => rows.push({ section: label, particulars: l.account_name, amount: (l.amount_paise / 100).toFixed(2) }));
      rows.push({ section: label, particulars: "Net Cash", amount: (section.total_paise / 100).toFixed(2) });
    });
    rows.push({ section: "", particulars: "Opening Cash", amount: (cf.opening_cash_paise / 100).toFixed(2) });
    rows.push({ section: "", particulars: "Net Change", amount: (cf.net_change_paise / 100).toFixed(2) });
    rows.push({ section: "", particulars: "Closing Cash", amount: (cf.closing_cash_paise / 100).toFixed(2) });
    return rows;
  };
  const cfExportColumns: Column<{ section: string; particulars: string; amount: string }>[] = [
    { key: "section", header: "Section", accessor: (row) => row.section },
    { key: "particulars", header: "Particulars", accessor: (row) => row.particulars },
    { key: "amount", header: "Amount (₹)", accessor: (row) => row.amount },
  ];

  return (
    <div className="space-y-4 max-w-3xl mx-auto">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">Cash Flow Statement — FY {financialYear}</p>
        <div className="flex items-center gap-2">
          <button onClick={() => load(true)} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
          <button
            onClick={() => downloadCsv(`cash-flow-fy-${financialYear}.csv`, toCsv(buildCfExportRows(), cfExportColumns))}
            disabled={!cf}
            className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"
            title="Export CSV"
          >
            <Download size={13} />
          </button>
          <button onClick={() => window.print()} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]" title="Print"><Printer size={13} /></button>
        </div>
      </div>

      {loading && <div className="h-48 rounded-lg bg-[#F8FAFC] animate-pulse" />}

      {!loading && loaded && !cf && (
        <div className="text-center py-12 text-[#94A3B8] text-sm">No posted journal entries for FY {financialYear}.</div>
      )}

      {!loading && cf && (
        <>
          {!cf.reconciles && (
            <div className="bg-amber-50 border border-amber-200 rounded px-3 py-2 text-xs text-amber-700">
              Cash flow does not reconcile to the change in cash balances for this period. Please review the ledger.
            </div>
          )}

          {/* Summary strip */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {[
              { label: "Operating", paise: cf.operating.total_paise },
              { label: "Investing", paise: cf.investing.total_paise },
              { label: "Financing", paise: cf.financing.total_paise },
              { label: "Net Change", paise: cf.net_change_paise },
            ].map((s) => (
              <div key={s.label} className="rounded-xl border border-[#F1F5F9] bg-white p-3 text-center">
                <p className="text-[10px] font-medium text-[#64748B] mb-1">{s.label}</p>
                <p className={`text-sm font-bold tabular-nums ${s.paise >= 0 ? "text-green-700" : "text-red-700"}`}>{fmtSigned(s.paise)}</p>
              </div>
            ))}
          </div>

          {/* Opening → Closing */}
          <div className="bg-white rounded-xl border border-[#F1F5F9] p-4 flex items-center gap-4 flex-wrap">
            <div>
              <p className="text-[10px] text-[#94A3B8]">Opening Cash</p>
              <p className="text-sm font-semibold text-[#0F172A]">{fmtSigned(cf.opening_cash_paise)}</p>
            </div>
            <span className="text-[#CBD5E1] font-medium">+</span>
            <div>
              <p className="text-[10px] text-[#94A3B8]">Net Change</p>
              <p className={`text-sm font-semibold ${cf.net_change_paise >= 0 ? "text-green-700" : "text-red-700"}`}>{fmtSigned(cf.net_change_paise)}</p>
            </div>
            <span className="text-[#CBD5E1] font-medium">=</span>
            <div>
              <p className="text-[10px] text-[#94A3B8]">Closing Cash</p>
              <p className="text-sm font-semibold text-[#0F172A]">{fmtSigned(cf.closing_cash_paise)}</p>
            </div>
            {cf.reconciles && <CheckCircle size={16} className="text-green-500 ml-auto shrink-0" />}
          </div>

          <CFSectionBlock title="A. Cash from Operating Activities" section={cf.operating} />
          <CFSectionBlock title="B. Cash from Investing Activities" section={cf.investing} />
          <CFSectionBlock title="C. Cash from Financing Activities" section={cf.financing} />

          {/* Operating reconciliation (indirect method) */}
          {r && (
            <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
              <div className="px-5 py-3 border-b border-gray-50 bg-[#F8FAFC]">
                <h3 className="text-xs font-semibold text-[#334155]">Operating Reconciliation — Indirect Method</h3>
              </div>
              <table className="w-full text-xs">
                <tbody className="divide-y divide-[#F8FAFC]">
                  {([
                    { label: "Net Profit for the Period", paise: r.net_profit_paise },
                    { label: "Add: Depreciation & Non-cash Items", paise: r.depreciation_addback_paise },
                    { label: "Non-operating Adjustments (Gain/Loss on Disposal)", paise: r.non_operating_adjust_paise },
                    { label: "Changes in Working Capital", paise: r.working_capital_change_paise },
                  ] as { label: string; paise: number }[]).map(({ label, paise }) =>
                    paise !== 0 ? (
                      <tr key={label} className="hover:bg-[#F8FAFC]">
                        <td className="px-5 py-2 pl-8 text-[#334155]">{label}</td>
                        <td className={`px-5 py-2 text-right font-mono font-medium ${paise >= 0 ? "text-green-700" : "text-red-700"}`}>{fmtSigned(paise)}</td>
                      </tr>
                    ) : null
                  )}
                </tbody>
                <tfoot>
                  <tr className="border-t border-[#E2E8F0] bg-[#F8FAFC]">
                    <td className="px-5 py-2 text-xs font-semibold text-[#334155]">Net Cash from Operations</td>
                    <td className={`px-5 py-2 text-right font-mono text-sm font-bold ${r.net_cash_operating_paise >= 0 ? "text-green-700" : "text-red-700"}`}>{fmtSigned(r.net_cash_operating_paise)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}

          <p className="text-[10px] text-[#94A3B8] text-center">
            AS-3 (Accounting Standard on Cash Flow Statements) · Companies Act 2013 Schedule III · Indirect Method
          </p>
        </>
      )}
    </div>
  );
}

// ── Bank Accounts & Statement Import ──────────────────────────────────────

// ── Bank Match & Categorize Queue (Banking B.2) ─────────────────────────────
// Suggestions + categorization workflow over B.1-imported transactions. No
// posting / reconciliation here — that is the Reconciliation tab / later phases.

const BANK_CATEGORIES = [
  "Sales Receipt", "Customer Payment", "Vendor Payment", "Expense", "GST Payment",
  "Salary", "Loan", "Capital", "Transfer", "Interest", "Other",
];

interface QueueTxn {
  id: string; transaction_date: string; description: string; reference_no: string | null;
  debit_paise: number; credit_paise: number; balance_paise: number; match_status: string;
  category: string | null; matched_entity_type: string | null; matched_entity_id: string | null;
  suggested_category: string | null; needs_review: boolean;
}
interface MatchSuggestion {
  matched_entity_type: string; matched_entity_id: string; label: string;
  amount_paise: number; confidence: number; confidence_label: string; reasons: string[];
}

const QUEUE_FILTERS: { id: string; label: string }[] = [
  { id: "unmatched", label: "Unmatched" },
  { id: "categorized", label: "Categorized" },
  { id: "needs_review", label: "Needs Review" },
  { id: "matched", label: "Matched" },
];

function BankMatchQueue({ clientId }: { clientId: string }) {
  const [status, setStatus] = useState("unmatched");
  const [rows, setRows] = useState<QueueTxn[]>([]);
  const [loading, setLoading] = useState(false);
  const [sugg, setSugg] = useState<Record<string, MatchSuggestion[]>>({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkCategory, setBulkCategory] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    try {
      const res = (await api.banking.queue({ client_id: clientId, status })) as { success: boolean; data: QueueTxn[] };
      setRows(res.success ? (res.data ?? []) : []);
    } catch { setRows([]); } finally { setLoading(false); }
  }, [clientId, status]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { setSelected(new Set()); }, [status]);

  async function categorize(id: string, category: string) {
    if (!category) return;
    setBusy((b) => ({ ...b, [id]: true }));
    try { await api.banking.categorize(id, { category }); await load(); }
    catch (e) { alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy((b) => ({ ...b, [id]: false })); }
  }

  function toggleRow(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }
  function toggleSelectAll() {
    setSelected((prev) => (prev.size === rows.length ? new Set() : new Set(rows.map((t) => t.id))));
  }
  function clearSelection() {
    setSelected(new Set());
    setBulkCategory("");
    setBulkError(null);
  }
  async function bulkCategorize() {
    if (!bulkCategory || selected.size === 0) return;
    setBulkBusy(true);
    setBulkError(null);
    const ids = Array.from(selected);
    const results = await Promise.all(
      ids.map((id) =>
        api.banking.categorize(id, { category: bulkCategory }).then(
          () => null,
          (e) => (e instanceof Error ? e.message : "Failed"),
        ),
      ),
    );
    const failCount = results.filter((r) => r !== null).length;
    await load();
    setBulkBusy(false);
    if (failCount > 0) {
      setBulkError(`Failed to categorize ${failCount} of ${ids.length} transaction${ids.length === 1 ? "" : "s"}.`);
    } else {
      clearSelection();
    }
  }
  async function loadSugg(id: string) {
    setBusy((b) => ({ ...b, [id]: true }));
    try {
      const res = (await api.banking.suggestions(id)) as { success: boolean; data: { suggestions: MatchSuggestion[] } };
      setSugg((s) => ({ ...s, [id]: res.success ? (res.data.suggestions ?? []) : [] }));
    } finally { setBusy((b) => ({ ...b, [id]: false })); }
  }
  async function accept(id: string, s: MatchSuggestion) {
    setBusy((b) => ({ ...b, [id]: true }));
    try { await api.banking.matchEntity(id, { matched_entity_type: s.matched_entity_type, matched_entity_id: s.matched_entity_id }); await load(); }
    catch (e) { alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy((b) => ({ ...b, [id]: false })); }
  }
  async function reject(id: string) {
    setBusy((b) => ({ ...b, [id]: true }));
    try { await api.banking.unmatch(id); setSugg((s) => ({ ...s, [id]: [] })); await load(); }
    finally { setBusy((b) => ({ ...b, [id]: false })); }
  }

  const confColor = (l: string) => l === "high" ? "text-green-700 bg-green-50" : l === "medium" ? "text-amber-700 bg-amber-50" : "text-[#64748B] bg-[#F1F5F9]";

  return (
    <div className="space-y-4 max-w-4xl mx-auto">
      <div className="flex gap-1 bg-[#F1F5F9] p-1 rounded-lg w-fit">
        {QUEUE_FILTERS.map((f) => (
          <button key={f.id} onClick={() => setStatus(f.id)}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${status === f.id ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"}`}>
            {f.label}
          </button>
        ))}
      </div>

      {loading ? <div className="h-40 bg-[#F8FAFC] rounded-lg animate-pulse" /> : rows.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-10 text-center text-sm text-[#94A3B8]">No transactions in this view.</div>
      ) : (
        <>
          <div className="flex items-center gap-2 px-1">
            <input
              type="checkbox"
              aria-label="Select all visible transactions"
              checked={rows.length > 0 && selected.size === rows.length}
              ref={(el) => { if (el) el.indeterminate = selected.size > 0 && selected.size < rows.length; }}
              onChange={toggleSelectAll}
              className="h-3.5 w-3.5 rounded border-[#CBD5E1]"
            />
            <span className="text-[10px] text-[#94A3B8]">Select all visible</span>
          </div>

          {/* ── Bulk categorize action bar ─────────────────────────────── */}
          {selected.size > 0 && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[#C7D2FE] bg-[#EEF2FF] px-3 py-2 text-xs">
              <span className="font-semibold text-[#3730A3]">{selected.size} selected</span>
              <div className="ml-auto flex flex-wrap items-center gap-2">
                <select
                  value={bulkCategory} disabled={bulkBusy}
                  onChange={(e) => setBulkCategory(e.target.value)}
                  className="px-2 py-1 text-xs border border-[#C7D2FE] rounded bg-white focus:outline-none focus:ring-1 focus:ring-blue-500">
                  <option value="">— Category —</option>
                  {BANK_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                <button
                  onClick={bulkCategorize}
                  disabled={bulkBusy || !bulkCategory}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[#C7D2FE] bg-white px-2.5 py-1.5 font-medium text-[#4338CA] hover:bg-[#E0E7FF] disabled:cursor-not-allowed disabled:opacity-50">
                  {bulkBusy ? "Applying…" : "Apply"}
                </button>
                <button onClick={clearSelection} disabled={bulkBusy} className="text-[#6366F1] hover:text-[#4338CA] disabled:opacity-50" aria-label="Clear selection">
                  <X size={14} />
                </button>
              </div>
            </div>
          )}
          {bulkError && <p className="text-[11px] text-red-600 px-1">{bulkError}</p>}

          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden divide-y divide-[#F8FAFC]">
            {rows.map((t) => (
              <div key={t.id} className="px-4 py-3 space-y-2">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-2 min-w-0">
                  <input
                    type="checkbox"
                    aria-label={`Select transaction ${t.description}`}
                    checked={selected.has(t.id)}
                    onChange={() => toggleRow(t.id)}
                    className="mt-0.5 h-3.5 w-3.5 rounded border-[#CBD5E1] shrink-0"
                  />
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-[#1E293B] truncate">{t.description}</p>
                    <p className="text-[10px] text-[#94A3B8] mt-0.5">{t.transaction_date} · {t.reference_no ?? ""}</p>
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  {t.debit_paise > 0 && <p className="text-xs font-mono text-red-700">{fmt(t.debit_paise)} Dr</p>}
                  {t.credit_paise > 0 && <p className="text-xs font-mono text-green-700">{fmt(t.credit_paise)} Cr</p>}
                </div>
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                {/* Categorize (B.2.2) */}
                <select
                  value={t.category ?? ""} disabled={busy[t.id]}
                  onChange={(e) => categorize(t.id, e.target.value)}
                  className="px-2 py-1 text-xs border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500">
                  <option value="">{t.suggested_category ? `Suggested: ${t.suggested_category}` : "— Category —"}</option>
                  {BANK_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                {t.category && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-700">{t.category}</span>}

                {/* Match (B.2.1 / B.2.5) */}
                {t.matched_entity_id ? (
                  <>
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-green-50 text-green-700">Matched · {t.matched_entity_type}</span>
                    <button onClick={() => reject(t.id)} disabled={busy[t.id]} className="text-[10px] text-red-600 hover:underline">Unmatch</button>
                  </>
                ) : (
                  <button onClick={() => loadSugg(t.id)} disabled={busy[t.id]} className="text-xs px-2.5 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569]">
                    Suggest matches
                  </button>
                )}
              </div>

              {/* Suggestion list */}
              {sugg[t.id] && sugg[t.id].length > 0 && (
                <div className="ml-1 border-l-2 border-[#F1F5F9] pl-3 space-y-1">
                  {sugg[t.id].map((s) => (
                    <div key={s.matched_entity_id} className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-[11px] text-[#334155] truncate">{s.label}</p>
                        <p className="text-[10px] text-[#94A3B8]">{s.reasons.join(" · ")}</p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${confColor(s.confidence_label)}`}>{s.confidence}%</span>
                        <button onClick={() => accept(t.id, s)} disabled={busy[t.id]} className="text-[10px] px-2 py-0.5 bg-blue-600 text-white rounded hover:bg-blue-700">Accept</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {sugg[t.id] && sugg[t.id].length === 0 && (
                <p className="text-[10px] text-[#94A3B8] ml-1">No match suggestions found.</p>
              )}
            </div>
          ))}
        </div>
        </>
      )}
      <p className="text-[10px] text-[#94A3B8] text-center">
        Suggestions &amp; categorization only — accepting a match links the transaction; it does not post a journal (that is a later phase).
      </p>
    </div>
  );
}

// ── Bank Posting (B.3) — Ready to Post / Posted / Review drawer ────────────
// Posting is EXPLICIT and human-initiated. The browser never builds journals;
// it only previews the backend's proposed entry and asks the user to confirm.

// Categories whose counter GL must be chosen explicitly (mirror of the backend
// posting_map.EXPLICIT_COUNTER — display logic only; the API re-validates).
const EXPLICIT_COUNTER_CATEGORIES = new Set([
  "Expense", "Salary", "Loan", "Capital", "Interest", "Sales Receipt", "Other",
]);
const TRANSFER_CATEGORY = "Transfer";

interface ReadyTxn {
  id: string; transaction_date: string; description: string; reference_no: string | null;
  debit_paise: number; credit_paise: number; match_status: string;
  category: string | null; matched_entity_type: string | null; matched_entity_id: string | null;
}
interface PostedTxn extends ReadyTxn {
  posted_journal_id: string; posted_at: string | null; posted_by: string | null;
}
interface PreviewLine { account_id: string; account_name: string; debit_paise: number; credit_paise: number; }
interface SettlementPreview {
  entity: string; label: string | null; allocate_paise: number;
  new_paid_paise: number; total_paise: number;
}
interface PostingPreview {
  transaction_id: string; category: string | null; entry_type: string; narration: string;
  lines: PreviewLine[]; total_debit_paise: number; total_credit_paise: number;
  settlement: SettlementPreview | null;
}

const isBankish = (a: Account) =>
  a.account_type === "Asset" && /bank|cash/i.test(`${a.account_subtype ?? ""} ${a.account_name}`);

function BankPostingQueue({ clientId, accounts }: { clientId: string; accounts: Account[] }) {
  const [view, setView] = useState<"ready" | "pending" | "posted">("ready");
  const [ready, setReady] = useState<ReadyTxn[]>([]);
  const [pending, setPending] = useState<ReadyTxn[]>([]);
  const [posted, setPosted] = useState<PostedTxn[]>([]);
  const [loading, setLoading] = useState(false);
  const [reviewing, setReviewing] = useState<ReadyTxn | null>(null);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    try {
      const [r, pen, p] = await Promise.all([
        api.banking.readyToPost({ client_id: clientId }) as Promise<{ success: boolean; data: ReadyTxn[] }>,
        api.banking.pending({ client_id: clientId }) as Promise<{ success: boolean; data: ReadyTxn[] }>,
        api.banking.posted({ client_id: clientId }) as Promise<{ success: boolean; data: PostedTxn[] }>,
      ]);
      setReady(r.success ? (r.data ?? []) : []);
      setPending(pen.success ? (pen.data ?? []) : []);
      setPosted(p.success ? (p.data ?? []) : []);
    } catch { setReady([]); setPending([]); setPosted([]); } finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div className="flex gap-1 bg-[#F1F5F9] p-1 rounded-lg w-fit">
          {([["ready", `Ready to Post (${ready.length})`], ["pending", `Pending Approval (${pending.length})`], ["posted", `Posted (${posted.length})`]] as const).map(([id, label]) => (
            <button key={id} onClick={() => setView(id)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${view === id ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"}`}>
              {label}
            </button>
          ))}
        </div>
        <button onClick={load} className="text-xs text-[#64748B] hover:text-[#334155]">Refresh</button>
      </div>

      {loading ? <div className="h-40 bg-[#F8FAFC] rounded-lg animate-pulse" /> : view === "pending" ? (
        pending.length === 0 ? (
          <div className="bg-white rounded-xl border border-[#F1F5F9] p-10 text-center text-sm text-[#94A3B8]">
            No drafts awaiting approval. Create one from “Ready to Post”, then approve it under the Approvals tab.
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-[#F8FAFC] text-[#64748B]"><tr>
                <th className="px-3 py-2 text-left font-medium">Date</th>
                <th className="px-3 py-2 text-right font-medium">Amount</th>
                <th className="px-3 py-2 text-left font-medium">Narration</th>
                <th className="px-3 py-2 text-left font-medium">Category</th>
                <th className="px-3 py-2 text-left font-medium">Status</th>
              </tr></thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {pending.map((t) => (
                  <tr key={t.id} className="hover:bg-[#F8FAFC]">
                    <td className="px-3 py-2 whitespace-nowrap text-[#475569]">{String(t.transaction_date).slice(0, 10)}</td>
                    <td className="px-3 py-2 text-right font-mono whitespace-nowrap">
                      {t.credit_paise > 0 ? <span className="text-green-700">{fmt(t.credit_paise)} Cr</span> : <span className="text-red-700">{fmt(t.debit_paise)} Dr</span>}
                    </td>
                    <td className="px-3 py-2 max-w-[220px] truncate text-[#334155]" title={t.description}>{t.description}</td>
                    <td className="px-3 py-2">{t.category ? <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-700">{t.category}</span> : <span className="text-[#94A3B8]">—</span>}</td>
                    <td className="px-3 py-2"><span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-700">Draft — awaiting approval</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : view === "ready" ? (
        ready.length === 0 ? (
          <div className="bg-white rounded-xl border border-[#F1F5F9] p-10 text-center text-sm text-[#94A3B8]">
            Nothing ready to post. Categorize transactions under the Categorize tab first.
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-[#F8FAFC] text-[#64748B]">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Date</th>
                  <th className="px-3 py-2 text-right font-medium">Amount</th>
                  <th className="px-3 py-2 text-left font-medium">Narration</th>
                  <th className="px-3 py-2 text-left font-medium">Category</th>
                  <th className="px-3 py-2 text-left font-medium">Match</th>
                  <th className="px-3 py-2 text-right font-medium">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {ready.map((t) => (
                  <tr key={t.id} className="hover:bg-[#F8FAFC]">
                    <td className="px-3 py-2 whitespace-nowrap text-[#475569]">{String(t.transaction_date).slice(0, 10)}</td>
                    <td className="px-3 py-2 text-right font-mono whitespace-nowrap">
                      {t.credit_paise > 0
                        ? <span className="text-green-700">{fmt(t.credit_paise)} Cr</span>
                        : <span className="text-red-700">{fmt(t.debit_paise)} Dr</span>}
                    </td>
                    <td className="px-3 py-2 max-w-[220px] truncate text-[#334155]" title={t.description}>{t.description}</td>
                    <td className="px-3 py-2">
                      {t.category
                        ? <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-700">{t.category}</span>
                        : <span className="text-[#94A3B8]">—</span>}
                    </td>
                    <td className="px-3 py-2">
                      {t.matched_entity_id
                        ? <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-green-50 text-green-700">{t.matched_entity_type}</span>
                        : <span className="text-[#94A3B8]">—</span>}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button onClick={() => setReviewing(t)}
                        className="text-xs px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
                        Review &amp; Create Draft
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : (
        posted.length === 0 ? (
          <div className="bg-white rounded-xl border border-[#F1F5F9] p-10 text-center text-sm text-[#94A3B8]">No posted transactions yet.</div>
        ) : (
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-[#F8FAFC] text-[#64748B]">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Date</th>
                  <th className="px-3 py-2 text-right font-medium">Amount</th>
                  <th className="px-3 py-2 text-left font-medium">Journal #</th>
                  <th className="px-3 py-2 text-left font-medium">Posted At</th>
                  <th className="px-3 py-2 text-left font-medium">Posted By</th>
                  <th className="px-3 py-2 text-left font-medium">Linked Entity</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {posted.map((t) => (
                  <tr key={t.id} className="hover:bg-[#F8FAFC]">
                    <td className="px-3 py-2 whitespace-nowrap text-[#475569]">{String(t.transaction_date).slice(0, 10)}</td>
                    <td className="px-3 py-2 text-right font-mono whitespace-nowrap">
                      {t.credit_paise > 0
                        ? <span className="text-green-700">{fmt(t.credit_paise)} Cr</span>
                        : <span className="text-red-700">{fmt(t.debit_paise)} Dr</span>}
                    </td>
                    <td className="px-3 py-2 font-mono text-[#475569]" title={t.posted_journal_id}>{t.posted_journal_id.slice(0, 8)}</td>
                    <td className="px-3 py-2 whitespace-nowrap text-[#475569]">{t.posted_at ? String(t.posted_at).slice(0, 16).replace("T", " ") : "—"}</td>
                    <td className="px-3 py-2 font-mono text-[#94A3B8]" title={t.posted_by ?? ""}>{t.posted_by ? t.posted_by.slice(0, 8) : "—"}</td>
                    <td className="px-3 py-2 text-[#475569]">{t.matched_entity_id ? t.matched_entity_type : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      <p className="text-[10px] text-[#94A3B8] text-center">
        Reviewing creates a DRAFT journal — it does not hit the books. Approve it under the Approvals tab to post and settle. Nothing is posted automatically.
      </p>

      {reviewing && (
        <PostingReviewDrawer
          txn={reviewing} accounts={accounts}
          onClose={() => setReviewing(null)}
          onPosted={() => { setReviewing(null); load(); }}
        />
      )}
    </div>
  );
}

function PostingReviewDrawer({
  txn, accounts, onClose, onPosted,
}: {
  txn: ReadyTxn; accounts: Account[]; onClose: () => void; onPosted: () => void;
}) {
  const [bankAccountId, setBankAccountId] = useState("");      // "" = auto (from statement)
  const [accountId, setAccountId] = useState("");             // counter GL (explicit categories)
  const [toBankAccountId, setToBankAccountId] = useState(""); // transfer destination
  const [preview, setPreview] = useState<PostingPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [posting, setPosting] = useState(false);
  const [postError, setPostError] = useState<string | null>(null);

  const category = txn.category ?? "";
  const needsCounter = EXPLICIT_COUNTER_CATEGORIES.has(category);
  const isTransfer = category === TRANSFER_CATEGORY;
  const bankAccounts = accounts.filter(isBankish);

  // Can we even attempt a preview yet? (the API enforces this too)
  const ready = (!needsCounter || !!accountId) && (!isTransfer || !!toBankAccountId);

  const loadPreview = useCallback(async () => {
    if (!ready) { setPreview(null); setPreviewError(null); return; }
    setLoadingPreview(true); setPreviewError(null);
    try {
      const res = (await api.banking.postingPreview(txn.id, {
        bank_account_id: bankAccountId || undefined,
        account_id: accountId || undefined,
        to_bank_account_id: toBankAccountId || undefined,
      })) as { success: boolean; data: PostingPreview; error: string | null };
      if (res.success) { setPreview(res.data); setPreviewError(null); }
      else { setPreview(null); setPreviewError(res.error ?? "Could not build the journal."); }
    } catch (e) {
      setPreview(null);
      setPreviewError(e instanceof Error ? e.message : "Could not build the journal.");
    } finally { setLoadingPreview(false); }
  }, [txn.id, bankAccountId, accountId, toBankAccountId, ready]);
  useEffect(() => { loadPreview(); }, [loadPreview]);

  const balanced = !!preview && preview.total_debit_paise === preview.total_credit_paise && preview.lines.length > 0;

  async function post() {
    setPosting(true); setPostError(null);
    try {
      const res = (await api.banking.postTransaction(txn.id, {
        bank_account_id: bankAccountId || undefined,
        account_id: accountId || undefined,
        to_bank_account_id: toBankAccountId || undefined,
      })) as { success: boolean; error: string | null };
      if (res.success) onPosted();
      else setPostError(res.error ?? "Posting failed.");
    } catch (e) {
      setPostError(e instanceof Error ? e.message : "Posting failed.");
    } finally { setPosting(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div className="w-full max-w-md h-full bg-white shadow-xl overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-4 border-b border-[#F1F5F9] flex items-center justify-between sticky top-0 bg-white">
          <h3 className="text-sm font-semibold text-[#0F172A]">Review &amp; Create Draft Journal</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#334155] text-lg leading-none">×</button>
        </div>

        <div className="p-5 space-y-4">
          {/* Transaction summary */}
          <div className="bg-[#F8FAFC] rounded-lg p-3 space-y-1">
            <p className="text-xs font-medium text-[#1E293B]">{txn.description}</p>
            <p className="text-[10px] text-[#94A3B8]">{String(txn.transaction_date).slice(0, 10)} · {txn.reference_no ?? "no ref"}</p>
            <div className="flex items-center justify-between pt-1">
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-700">{category || "Uncategorized"}</span>
              <span className="text-sm font-mono">
                {txn.credit_paise > 0
                  ? <span className="text-green-700">{fmt(txn.credit_paise)} Cr</span>
                  : <span className="text-red-700">{fmt(txn.debit_paise)} Dr</span>}
              </span>
            </div>
          </div>

          {/* Account inputs (only where the engine needs an explicit choice) */}
          <div className="space-y-3">
            <label className="block">
              <span className="text-[11px] font-medium text-[#475569]">Bank account</span>
              <select value={bankAccountId} onChange={(e) => setBankAccountId(e.target.value)}
                className="mt-1 w-full px-2 py-1.5 text-xs border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500">
                <option value="">Auto — from statement</option>
                {bankAccounts.map((a) => <option key={a.id} value={a.id}>{a.account_code} · {a.account_name}</option>)}
              </select>
            </label>

            {needsCounter && (
              <label className="block">
                <span className="text-[11px] font-medium text-[#475569]">Counter account (GL) <span className="text-red-500">*</span></span>
                <div className="mt-1">
                  <AccountLookup
                    accounts={accounts}
                    value={accountId}
                    onChange={setAccountId}
                    size="sm"
                    placeholder="— Select account —"
                    ariaLabel="Counter account"
                  />
                </div>
                <span className="text-[10px] text-[#94A3B8]">Required — the ledger account is never guessed.</span>
              </label>
            )}

            {isTransfer && (
              <label className="block">
                <span className="text-[11px] font-medium text-[#475569]">Transfer to (bank / cash) <span className="text-red-500">*</span></span>
                <select value={toBankAccountId} onChange={(e) => setToBankAccountId(e.target.value)}
                  className="mt-1 w-full px-2 py-1.5 text-xs border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500">
                  <option value="">— Select destination —</option>
                  {accounts.filter((a) => a.account_type === "Asset").map((a) => <option key={a.id} value={a.id}>{a.account_code} · {a.account_name}</option>)}
                </select>
              </label>
            )}
          </div>

          {/* Proposed journal (preview — no writes) */}
          <div>
            <p className="text-[11px] font-medium text-[#475569] mb-1">Proposed journal entry</p>
            {!ready ? (
              <p className="text-xs text-[#94A3B8] bg-[#F8FAFC] rounded-lg p-3">Select the required account(s) above to preview the entry.</p>
            ) : loadingPreview ? (
              <div className="h-20 bg-[#F8FAFC] rounded-lg animate-pulse" />
            ) : previewError ? (
              <p className="text-xs text-red-700 bg-red-50 border border-red-100 rounded-lg p-3">{previewError}</p>
            ) : preview ? (
              <div className="border border-[#F1F5F9] rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-[#F8FAFC] text-[#64748B]">
                    <tr><th className="px-3 py-1.5 text-left font-medium">Account</th><th className="px-3 py-1.5 text-right font-medium">Dr</th><th className="px-3 py-1.5 text-right font-medium">Cr</th></tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {preview.lines.map((l, i) => (
                      <tr key={i}>
                        <td className="px-3 py-1.5 text-[#334155]">{l.account_name}</td>
                        <td className="px-3 py-1.5 text-right font-mono text-[#334155]">{l.debit_paise > 0 ? fmt(l.debit_paise) : "—"}</td>
                        <td className="px-3 py-1.5 text-right font-mono text-[#334155]">{l.credit_paise > 0 ? fmt(l.credit_paise) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot className="bg-[#F8FAFC] font-medium">
                    <tr>
                      <td className="px-3 py-1.5 text-[#475569]">Total ({preview.entry_type})</td>
                      <td className="px-3 py-1.5 text-right font-mono">{fmt(preview.total_debit_paise)}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{fmt(preview.total_credit_paise)}</td>
                    </tr>
                  </tfoot>
                </table>
                {!balanced && <p className="text-[10px] text-red-600 px-3 py-1.5">Entry is not balanced — posting is blocked.</p>}
              </div>
            ) : null}
          </div>

          {/* Settlement effect */}
          {preview?.settlement && (
            <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-xs text-amber-900">
              <p className="font-medium">Settlement</p>
              <p className="mt-0.5">
                {preview.settlement.entity === "purchase_bill" ? "Bill" : "Invoice"} {preview.settlement.label ?? ""}:
                allocate <span className="font-mono">{fmt(preview.settlement.allocate_paise)}</span>
                {" "}(<span className="font-mono">{fmt(preview.settlement.new_paid_paise)}</span> of <span className="font-mono">{fmt(preview.settlement.total_paise)}</span> paid)
              </p>
            </div>
          )}

          {postError && <p className="text-xs text-red-700 bg-red-50 border border-red-100 rounded-lg p-3">{postError}</p>}
        </div>

        <div className="px-5 py-4 border-t border-[#F1F5F9] flex items-center justify-end gap-2 sticky bottom-0 bg-white">
          <button onClick={onClose} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded text-[#475569] hover:bg-[#F8FAFC]">Cancel</button>
          <button onClick={post} disabled={!balanced || posting || loadingPreview}
            className="text-xs px-4 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed">
            {posting ? "Creating…" : "Create Draft Journal"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Bank Accounts & Statement Import ──────────────────────────────────────

// ── Journal Approval Queue (Phase 3.5) — single Draft → Approve → Post review ──
// One queue for every draft (manual + auto-generated, e.g. bank). Approving posts
// the journal to the books (backend-driven: FY-locked, audited) and fires deferred
// downstream actions like bank settlement. Drafts are off-books until approved.

interface QueueJournal {
  id: string; entry_date: string | null; reference_no: string | null; narration: string | null;
  entry_type: string | null; source_type: string | null; created_by: string | null;
  created_at: string | null; is_posted: boolean; posted_at: string | null;
  total_debit_paise: number; total_credit_paise: number; line_count: number;
}

const SOURCE_LABEL: Record<string, string> = {
  bank_transaction: "Bank", sales_invoice: "Sales Invoice", purchase_bill: "Purchase Bill",
  manual: "Manual",
};

function ApprovalQueue({ clientId }: { clientId: string }) {
  const [status, setStatus] = useState<"draft" | "posted">("draft");
  const [rows, setRows] = useState<QueueJournal[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    try {
      const res = (await api.accounting.journalsQueue({ client_id: clientId, status })) as { success: boolean; data: QueueJournal[] };
      setRows(res.success ? (res.data ?? []) : []);
    } catch { setRows([]); } finally { setLoading(false); }
  }, [clientId, status]);
  useEffect(() => { load(); }, [load]);

  async function approve(id: string) {
    setBusy((b) => ({ ...b, [id]: true })); setError(null);
    try {
      const res = (await api.accounting.postDraftJournal(id)) as { success: boolean; error: string | null };
      if (res && res.success === false) setError(res.error ?? "Could not post the journal.");
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not post the journal."); }
    finally { setBusy((b) => ({ ...b, [id]: false })); }
  }

  return (
    <div className="space-y-4 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div className="flex gap-1 bg-[#F1F5F9] p-1 rounded-lg w-fit">
          {([["draft", "Draft"], ["posted", "Posted"]] as const).map(([id, label]) => (
            <button key={id} onClick={() => setStatus(id)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${status === id ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"}`}>
              {label}
            </button>
          ))}
        </div>
        <button onClick={load} className="text-xs text-[#64748B] hover:text-[#334155]">Refresh</button>
      </div>

      {error && <p className="text-xs text-red-700 bg-red-50 border border-red-100 rounded-lg p-3">{error}</p>}

      {loading ? <div className="h-40 bg-[#F8FAFC] rounded-lg animate-pulse" /> : rows.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-10 text-center text-sm text-[#94A3B8]">
          {status === "draft" ? "No drafts awaiting approval." : "No posted journals yet."}
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-[#F8FAFC] text-[#64748B]"><tr>
              <th className="px-3 py-2 text-left font-medium">Date</th>
              <th className="px-3 py-2 text-left font-medium">Ref</th>
              <th className="px-3 py-2 text-left font-medium">Narration</th>
              <th className="px-3 py-2 text-left font-medium">Source</th>
              <th className="px-3 py-2 text-right font-medium">Debit</th>
              <th className="px-3 py-2 text-right font-medium">Credit</th>
              <th className="px-3 py-2 text-right font-medium">{status === "draft" ? "Action" : "Posted At"}</th>
            </tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {rows.map((j) => {
                const balanced = j.total_debit_paise === j.total_credit_paise && j.total_debit_paise > 0;
                return (
                  <tr key={j.id} className="hover:bg-[#F8FAFC]">
                    <td className="px-3 py-2 whitespace-nowrap text-[#475569]">{j.entry_date ? String(j.entry_date).slice(0, 10) : "—"}</td>
                    <td className="px-3 py-2 font-mono text-[#94A3B8]">{j.reference_no ?? "—"}</td>
                    <td className="px-3 py-2 max-w-[240px] truncate text-[#334155]" title={j.narration ?? ""}>{j.narration ?? "—"}</td>
                    <td className="px-3 py-2"><span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[#F1F5F9] text-[#475569]">{SOURCE_LABEL[j.source_type ?? "manual"] ?? "Manual"}</span></td>
                    <td className="px-3 py-2 text-right font-mono text-[#334155]">{fmt(j.total_debit_paise)}</td>
                    <td className="px-3 py-2 text-right font-mono text-[#334155]">{fmt(j.total_credit_paise)}</td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      {status === "draft" ? (
                        <button onClick={() => approve(j.id)} disabled={busy[j.id] || !balanced}
                          title={balanced ? "Approve & post to the ledger" : "Entry is not balanced"}
                          className="text-xs px-3 py-1 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed">
                          {busy[j.id] ? "Posting…" : "Approve & Post"}
                        </button>
                      ) : (
                        <span className="text-[#475569]">{j.posted_at ? String(j.posted_at).slice(0, 16).replace("T", " ") : "—"}</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[10px] text-[#94A3B8] text-center">
        Approving posts the draft to the books and triggers any deferred action (e.g. bank settlement). Requires approval permission; locked financial years are blocked.
      </p>
    </div>
  );
}

function BankAccounts({ clientId }: { clientId: string }) {
  const [statements, setStatements] = useState<BankStatement[]>([]);
  const [loading, setLoading] = useState(true);
  const [showImport, setShowImport] = useState(false);
  const [selectedStmt, setSelectedStmt] = useState<string | null>(null);
  const [stmtTxns, setStmtTxns] = useState<BankTransaction[]>([]);
  const [txnsLoading, setTxnsLoading] = useState(false);

  const loadStatements = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    try { setStatements(await getBankStatements(clientId)); } catch { /* skip */ }
    setLoading(false);
  }, [clientId]);

  useEffect(() => { loadStatements(); }, [loadStatements]);

  async function openStatement(id: string) {
    setSelectedStmt(id); setTxnsLoading(true);
    try { setStmtTxns(await getBankTransactions(id)); } catch { setStmtTxns([]); }
    setTxnsLoading(false);
  }

  const STATUS_COLORS: Record<string, string> = {
    pending: "bg-amber-100 text-amber-700",
    reviewed: "bg-blue-100 text-blue-700",
    posted: "bg-green-100 text-green-700",
  };

  return (
    <div className="space-y-4 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">{statements.length} bank statement{statements.length !== 1 ? "s" : ""} imported</p>
        <div className="flex gap-2">
          <button onClick={loadStatements} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
          <button onClick={() => setShowImport(true)} className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
            <Upload size={12} /> Import Statement
          </button>
        </div>
      </div>

      {loading ? (
        <div className="space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-14 rounded-lg bg-[#F8FAFC] animate-pulse" />)}</div>
      ) : statements.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16 space-y-3">
          <FileText size={32} className="text-gray-200 mx-auto" />
          <p className="text-sm text-[#64748B]">No bank statements imported yet</p>
          <button onClick={() => setShowImport(true)} className="text-xs text-blue-600 hover:underline">Import your first statement</button>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <table className="w-full text-xs">
            <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]"><th className="px-4 py-3 text-left font-semibold">Bank</th><th className="px-3 py-3 text-left font-semibold">Account No.</th><th className="px-3 py-3 text-left font-semibold">Period</th><th className="px-3 py-3 text-right font-semibold">Credits</th><th className="px-3 py-3 text-right font-semibold">Debits</th><th className="px-3 py-3 text-left font-semibold">Status</th><th className="px-4 py-3 text-left font-semibold">Action</th></tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {statements.map((s) => (
                <tr key={s.id} className="hover:bg-[#F8FAFC]">
                  <td className="px-4 py-2.5 font-medium text-[#1E293B]">{s.bank_name}</td>
                  <td className="px-3 py-2.5 font-mono text-[#64748B] text-[10px]">{s.account_number ?? "—"}</td>
                  <td className="px-3 py-2.5 text-[#64748B]">{s.statement_from} → {s.statement_to}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-green-700">{fmt(s.total_credits_paise)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-red-700">{fmt(s.total_debits_paise)}</td>
                  <td className="px-3 py-2.5">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${STATUS_COLORS[s.import_status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>{s.import_status}</span>
                  </td>
                  <td className="px-4 py-2.5">
                    <button onClick={() => selectedStmt === s.id ? setSelectedStmt(null) : openStatement(s.id)} className="text-xs text-blue-600 hover:underline">
                      {selectedStmt === s.id ? "Hide" : "View"} ({s.row_count} txns)
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Statement transactions inline view */}
      {selectedStmt && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-50 flex items-center justify-between">
            <p className="text-xs font-semibold text-[#334155]">Transactions</p>
            {txnsLoading && <RefreshCw size={13} className="animate-spin text-[#94A3B8]" />}
          </div>
          {!txnsLoading && stmtTxns.length > 0 && (
            <div className="overflow-x-auto max-h-72 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-white"><tr className="border-b border-[#F1F5F9] text-[#94A3B8]"><th className="px-4 py-2 text-left font-semibold">Date</th><th className="px-3 py-2 text-left font-semibold">Description</th><th className="px-3 py-2 text-right font-semibold">Debit</th><th className="px-3 py-2 text-right font-semibold">Credit</th><th className="px-3 py-2 text-left font-semibold">Status</th></tr></thead>
                <tbody className="divide-y divide-[#F8FAFC]">
                  {stmtTxns.map((t) => (
                    <tr key={t.id} className="hover:bg-[#F8FAFC]">
                      <td className="px-4 py-2 text-[#64748B] whitespace-nowrap">{t.transaction_date}</td>
                      <td className="px-3 py-2 text-[#334155] max-w-xs truncate">{t.description}</td>
                      <td className="px-3 py-2 text-right font-mono text-red-700">{t.debit_paise > 0 ? fmt(t.debit_paise) : "—"}</td>
                      <td className="px-3 py-2 text-right font-mono text-green-700">{t.credit_paise > 0 ? fmt(t.credit_paise) : "—"}</td>
                      <td className="px-3 py-2">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${t.match_status === "posted" ? "bg-green-100 text-green-700" : t.match_status === "matched" ? "bg-blue-100 text-blue-700" : t.match_status === "ignored" ? "bg-[#F1F5F9] text-[#94A3B8]" : "bg-amber-100 text-amber-700"}`}>{t.match_status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!txnsLoading && stmtTxns.length === 0 && <div className="text-center py-8 text-[#94A3B8] text-sm">No transactions found.</div>}
        </div>
      )}

      {showImport && (
        <BankImportModal clientId={clientId} onClose={() => setShowImport(false)} onImported={() => { setShowImport(false); loadStatements(); }} />
      )}
    </div>
  );
}

// ── Bank Import Modal ──────────────────────────────────────────────────────

function BankImportModal({ clientId, onClose, onImported }: { clientId: string; onClose: () => void; onImported: () => void }) {
  const [bankName, setBankName] = useState("HDFC Bank");
  const [accountNumber, setAccountNumber] = useState("");
  const [parsed, setParsed] = useState<ReturnType<typeof parseCSV> | null>(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const text = ev.target?.result as string;
        const rows = parseCSV(text);
        if (rows.length === 0) { setError("No transactions found. Check CSV format."); return; }
        setParsed(rows); setError(null);
      } catch { setError("Failed to parse file. Ensure it is a valid CSV."); }
    };
    reader.readAsText(file);
  }

  async function handleImport() {
    if (!parsed || parsed.length === 0) return;
    if (!bankName.trim()) { setError("Bank name required."); return; }
    setImporting(true); setError(null);
    try {
      // The backend banking service records the import + its timeline event.
      await importBankStatement(clientId, bankName.trim(), accountNumber.trim(), parsed);
      onImported();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">Import Bank Statement</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Bank Name *</label>
            <select value={bankName} onChange={(e) => setBankName(e.target.value)} className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
              {["HDFC Bank","SBI","ICICI Bank","Axis Bank","Kotak Mahindra Bank","IndusInd Bank","Yes Bank","IDFC First Bank","Other"].map((b) => <option key={b}>{b}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Account Number</label>
            <input value={accountNumber} onChange={(e) => setAccountNumber(e.target.value)} placeholder="XXXX XXXX XXXX" className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">CSV File *</label>
            <input ref={fileRef} type="file" accept=".csv,.txt" onChange={handleFile} className="hidden" />
            <button onClick={() => fileRef.current?.click()} className="w-full border-2 border-dashed border-[#E2E8F0] rounded-lg py-4 text-sm text-[#64748B] hover:border-blue-300 hover:text-blue-600 transition-colors flex items-center justify-center gap-2">
              <Upload size={16} /> {parsed ? `${parsed.length} transactions loaded` : "Click to select CSV"}
            </button>
          </div>
        </div>
        {parsed && (
          <div className="bg-green-50 border border-green-100 rounded-lg px-3 py-2">
            <p className="text-xs text-green-700 font-medium">Preview: {parsed.length} transactions</p>
            <p className="text-[10px] text-green-600 mt-0.5">{parsed[0]?.date} → {parsed[parsed.length-1]?.date}</p>
          </div>
        )}
        {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
          <button onClick={handleImport} disabled={importing || !parsed} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
            {importing ? "Importing…" : "Import"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Bank Reconciliation ────────────────────────────────────────────────────

// ── Bank Reconciliation (B.4) — sessions, manual reconcile, tie-out, report ──
// Fully backend-driven: the browser renders the session tie-out and item buckets
// and triggers explicit reconcile / unreconcile / complete actions. No accounting
// math happens here. Posting/categorization live in their own tabs — this is the
// statement-vs-book reconciliation only.

interface ReconSummary {
  opening_balance_paise: number; deposits_paise: number; withdrawals_paise: number;
  adjustments_paise: number; reconciled_book_balance_paise: number;
  statement_closing_balance_paise: number; difference_paise: number; reconciles: boolean;
}
interface ReconSession {
  id: string; bank_account_id: string; account_no: string | null;
  statement_start_date: string; statement_end_date: string;
  opening_balance_paise: number; closing_balance_paise: number; adjustments_paise: number;
  status: "open" | "in_progress" | "completed"; completed_at: string | null;
}
interface ReconLine {
  id: string; transaction_date: string; description: string; reference_no: string | null;
  debit_paise: number; credit_paise: number; posted_journal_id: string | null;
  exception_reason: string | null;
}
interface ReconReport {
  reconciliation: ReconSession; summary: ReconSummary; ties_out: boolean;
  reconciled: ReconLine[]; unreconciled: ReconLine[]; exceptions: ReconLine[];
  counts: { reconciled: number; unreconciled: number; exceptions: number };
}

const toPaise = (s: string) => Math.round(parseFloat(s || "0") * 100);

function BankReconciliation({ clientId }: { clientId: string }) {
  const [sessions, setSessions] = useState<ReconSession[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [report, setReport] = useState<ReconReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingReport, setLoadingReport] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [view, setView] = useState<"unreconciled" | "reconciled" | "exceptions">("unreconciled");
  const [sel, setSel] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [bankAccounts, setBankAccounts] = useState<{ id: string; bank_name: string; account_no: string }[]>([]);
  const [form, setForm] = useState({ bank_account_id: "", start: "", end: "", opening: "", closing: "" });
  const [adj, setAdj] = useState("");

  const loadSessions = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    try {
      const res = (await api.banking.reconciliations.list({ client_id: clientId })) as { success: boolean; data: ReconSession[] };
      setSessions(res.success ? (res.data ?? []) : []);
    } catch { setSessions([]); } finally { setLoading(false); }
  }, [clientId]);

  const loadBankAccounts = useCallback(async () => {
    try {
      const res = (await api.banking.listBankAccounts({ client_id: clientId })) as { success: boolean; data: { id: string; bank_name: string; account_no: string }[] };
      if (res.success) setBankAccounts(res.data ?? []);
    } catch { /* non-blocking */ }
  }, [clientId]);

  useEffect(() => { loadSessions(); loadBankAccounts(); }, [loadSessions, loadBankAccounts]);

  const loadReport = useCallback(async (id: string) => {
    setLoadingReport(true); setSel({}); setError(null);
    try {
      const res = (await api.banking.reconciliations.report(id)) as { success: boolean; data: ReconReport };
      setReport(res.success ? res.data : null);
      if (res.success) setAdj(((res.data.reconciliation.adjustments_paise || 0) / 100).toFixed(2));
    } catch { setReport(null); } finally { setLoadingReport(false); }
  }, []);
  useEffect(() => { if (selectedId) loadReport(selectedId); else setReport(null); }, [selectedId, loadReport]);

  async function refresh() { await loadReport(selectedId); await loadSessions(); }

  async function createSession() {
    setError(null);
    if (!form.bank_account_id || !form.start || !form.end) { setError("Bank account and statement dates are required."); return; }
    setBusy(true);
    try {
      const res = (await api.banking.reconciliations.create({
        client_id: clientId, bank_account_id: form.bank_account_id,
        statement_start_date: form.start, statement_end_date: form.end,
        opening_balance_paise: toPaise(form.opening), closing_balance_paise: toPaise(form.closing),
      })) as { success: boolean; data: ReconSession; error: string | null };
      if (res.success) { setShowNew(false); setForm({ bank_account_id: "", start: "", end: "", opening: "", closing: "" }); await loadSessions(); setSelectedId(res.data.id); }
      else setError(res.error ?? "Could not open reconciliation.");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not open reconciliation."); }
    finally { setBusy(false); }
  }

  async function act(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try {
      const res = (await fn()) as { success: boolean; error: string | null };
      if (res && res.success === false) setError(res.error ?? "Action failed.");
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Action failed."); }
    finally { setBusy(false); }
  }

  const completed = report?.reconciliation.status === "completed";
  const lines = report ? report[view] : [];
  const selectedIds = Object.keys(sel).filter((k) => sel[k]);
  const statusBadge = (s: string) => s === "completed" ? "bg-green-100 text-green-700" : s === "in_progress" ? "bg-amber-100 text-amber-700" : "bg-[#F1F5F9] text-[#64748B]";

  return (
    <div className="space-y-4 max-w-4xl mx-auto">
      {/* Session selector */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-4 flex items-end gap-3 flex-wrap">
        <div className="flex-1 min-w-[240px]">
          <label className="block text-xs font-medium text-[#475569] mb-1.5">Reconciliation session</label>
          {loading ? <div className="h-9 bg-[#F8FAFC] rounded animate-pulse" /> : (
            <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)} className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">— Select a reconciliation —</option>
              {sessions.map((s) => <option key={s.id} value={s.id}>{s.statement_start_date} → {s.statement_end_date} · {s.account_no ?? "account"} · {s.status}</option>)}
            </select>
          )}
        </div>
        <button onClick={() => { setShowNew((v) => !v); setSelectedId(""); }} className="text-xs px-3 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569]">
          {showNew ? "Cancel" : "New Reconciliation"}
        </button>
      </div>

      {error && <p className="text-xs text-red-700 bg-red-50 border border-red-100 rounded-lg p-3">{error}</p>}

      {/* New session form */}
      {showNew && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4 space-y-3">
          <p className="text-xs font-semibold text-[#334155]">Open a reconciliation</p>
          <div className="grid grid-cols-2 gap-3">
            <label className="block col-span-2">
              <span className="text-[11px] font-medium text-[#475569]">Bank account</span>
              <select value={form.bank_account_id} onChange={(e) => setForm((f) => ({ ...f, bank_account_id: e.target.value }))} className="mt-1 w-full px-2 py-1.5 text-xs border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500">
                <option value="">— Select bank account —</option>
                {bankAccounts.map((b) => <option key={b.id} value={b.id}>{b.bank_name} · {b.account_no}</option>)}
              </select>
            </label>
            <label className="block"><span className="text-[11px] font-medium text-[#475569]">Statement start</span>
              <input type="date" value={form.start} onChange={(e) => setForm((f) => ({ ...f, start: e.target.value }))} className="mt-1 w-full px-2 py-1.5 text-xs border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500" /></label>
            <label className="block"><span className="text-[11px] font-medium text-[#475569]">Statement end</span>
              <input type="date" value={form.end} onChange={(e) => setForm((f) => ({ ...f, end: e.target.value }))} className="mt-1 w-full px-2 py-1.5 text-xs border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500" /></label>
            <label className="block"><span className="text-[11px] font-medium text-[#475569]">Opening balance (₹)</span>
              <input type="number" step="0.01" value={form.opening} onChange={(e) => setForm((f) => ({ ...f, opening: e.target.value }))} placeholder="0.00" className="mt-1 w-full px-2 py-1.5 text-xs border border-[#E2E8F0] rounded text-right focus:outline-none focus:ring-1 focus:ring-blue-500" /></label>
            <label className="block"><span className="text-[11px] font-medium text-[#475569]">Closing balance (₹)</span>
              <input type="number" step="0.01" value={form.closing} onChange={(e) => setForm((f) => ({ ...f, closing: e.target.value }))} placeholder="0.00" className="mt-1 w-full px-2 py-1.5 text-xs border border-[#E2E8F0] rounded text-right focus:outline-none focus:ring-1 focus:ring-blue-500" /></label>
          </div>
          <button onClick={createSession} disabled={busy} className="text-xs px-4 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">Open Reconciliation</button>
        </div>
      )}

      {/* Selected session */}
      {selectedId && (loadingReport ? <div className="h-48 bg-[#F8FAFC] rounded-lg animate-pulse" /> : report && (
        <>
          {/* Tie-out summary (cash-flow style reconciles flag) */}
          <div className="bg-white rounded-xl border border-[#F1F5F9] p-4 space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold text-[#334155]">Balance tie-out</p>
              <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${statusBadge(report.reconciliation.status)}`}>{report.reconciliation.status}</span>
            </div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs font-mono">
              <Row label="Opening balance" paise={report.summary.opening_balance_paise} />
              <Row label="+ Deposits (reconciled)" paise={report.summary.deposits_paise} />
              <Row label="− Withdrawals (reconciled)" paise={report.summary.withdrawals_paise} />
              <Row label="± Adjustments" paise={report.summary.adjustments_paise} />
              <Row label="= Reconciled book balance" paise={report.summary.reconciled_book_balance_paise} strong />
              <Row label="Statement closing balance" paise={report.summary.statement_closing_balance_paise} strong />
            </div>
            <div className={`flex items-center justify-between rounded-lg px-3 py-2 ${report.ties_out ? "bg-green-50" : "bg-red-50"}`}>
              <span className={`text-xs font-medium flex items-center gap-1.5 ${report.ties_out ? "text-green-700" : "text-red-700"}`}>
                {report.ties_out ? <><CheckCircle size={14} /> Statement ties out to the book balance</> : <>Difference {fmt(Math.abs(report.summary.difference_paise))} — does not tie out</>}
              </span>
            </div>
            {!completed && (
              <div className="flex items-center gap-2 pt-1">
                <span className="text-[11px] text-[#64748B]">Adjustment (₹)</span>
                <input type="number" step="0.01" value={adj} onChange={(e) => setAdj(e.target.value)} className="w-28 px-2 py-1 text-xs border border-[#E2E8F0] rounded text-right focus:outline-none focus:ring-1 focus:ring-blue-500" />
                <button onClick={() => act(() => api.banking.reconciliations.update(selectedId, { adjustments_paise: toPaise(adj) }))} disabled={busy} className="text-[11px] px-2 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569]">Apply</button>
              </div>
            )}
            <div className="flex items-center gap-2 pt-1 border-t border-[#F8FAFC]">
              <button onClick={() => api.banking.reconciliations.exportCsv(selectedId)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569] flex items-center gap-1.5"><Download size={12} /> Export CSV</button>
              {!completed && (
                <button onClick={() => act(() => api.banking.reconciliations.complete(selectedId))} disabled={busy || !report.ties_out} title={report.ties_out ? "" : "Reconcile until the statement ties out"} className="text-xs px-4 py-1.5 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed ml-auto">Complete Reconciliation</button>
              )}
              {completed && <span className="text-[11px] text-green-700 ml-auto flex items-center gap-1"><CheckCircle size={12} /> Completed {report.reconciliation.completed_at ? String(report.reconciliation.completed_at).slice(0, 10) : ""} · locked</span>}
            </div>
          </div>

          {/* Item buckets */}
          <div className="flex gap-1 bg-[#F1F5F9] p-1 rounded-lg w-fit">
            {([["unreconciled", "Unreconciled", report.counts.unreconciled], ["reconciled", "Reconciled", report.counts.reconciled], ["exceptions", "Exceptions", report.counts.exceptions]] as const).map(([id, label, n]) => (
              <button key={id} onClick={() => { setView(id); setSel({}); }} className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${view === id ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"}`}>{label} ({n})</button>
            ))}
          </div>

          {!completed && view !== "exceptions" && selectedIds.length > 0 && (
            <div className="flex items-center gap-2">
              {view === "unreconciled"
                ? <button onClick={() => act(() => api.banking.reconciliations.reconcile(selectedId, selectedIds))} disabled={busy} className="text-xs px-4 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">Reconcile {selectedIds.length} selected</button>
                : <button onClick={() => act(() => api.banking.reconciliations.unreconcile(selectedId, selectedIds))} disabled={busy} className="text-xs px-4 py-1.5 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569]">Unreconcile {selectedIds.length} selected</button>}
            </div>
          )}

          {lines.length === 0 ? (
            <div className="bg-white rounded-xl border border-[#F1F5F9] p-8 text-center text-xs text-[#94A3B8]">No {view} transactions.</div>
          ) : (
            <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden divide-y divide-[#F8FAFC]">
              {lines.map((t) => (
                <label key={t.id} className="flex items-center gap-3 px-4 py-2.5 hover:bg-[#F8FAFC] cursor-pointer">
                  {!completed && view !== "exceptions" && (
                    <input type="checkbox" checked={!!sel[t.id]} onChange={(e) => setSel((m) => ({ ...m, [t.id]: e.target.checked }))} className="shrink-0" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium text-[#1E293B] truncate">{t.description}</p>
                    <p className="text-[10px] text-[#94A3B8]">{t.transaction_date} · {t.reference_no ?? ""}{t.exception_reason ? ` · ⚠ ${t.exception_reason}` : ""}</p>
                  </div>
                  <div className="shrink-0 text-right font-mono">
                    {t.credit_paise > 0 ? <span className="text-xs text-green-700">{fmt(t.credit_paise)} Cr</span> : <span className="text-xs text-red-700">{fmt(t.debit_paise)} Dr</span>}
                  </div>
                </label>
              ))}
            </div>
          )}
        </>
      ))}

      {!selectedId && !showNew && !loading && (
        <div className="text-center py-12 text-[#94A3B8] text-sm">
          {sessions.length === 0 ? "No reconciliations yet. Click “New Reconciliation” to begin." : "Select a reconciliation to view its tie-out."}
        </div>
      )}
    </div>
  );
}

function Row({ label, paise, strong }: { label: string; paise: number; strong?: boolean }) {
  return (
    <div className={`flex items-center justify-between ${strong ? "text-[#0F172A] font-semibold border-t border-[#F8FAFC] pt-1" : "text-[#475569]"}`}>
      <span className="font-sans text-[11px]">{label}</span>
      <span>{fmt(paise)}</span>
    </div>
  );
}

// ── Financial Reports ──────────────────────────────────────────────────────

function YearEndClose({ financialYear }: { financialYear: string }) {
  const [locked, setLocked] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    async function check() {
      try {
        const supabase = getSupabaseClient();
        const firmId = await getFirmId();
        const { data } = await supabase.from("firms").select("locked_financial_years").eq("id", firmId).maybeSingle();
        const years: string[] = (data as { locked_financial_years?: string[] } | null)?.locked_financial_years ?? [];
        setLocked(years.includes(financialYear));
      } catch { setLocked(false); } finally { setLoading(false); }
    }
    check();
  }, [financialYear]);

  async function toggleLock() {
    setSaving(true);
    try {
      const supabase = getSupabaseClient();
      const firmId = await getFirmId();
      const { data } = await supabase.from("firms").select("locked_financial_years").eq("id", firmId).maybeSingle();
      const years: string[] = (data as { locked_financial_years?: string[] } | null)?.locked_financial_years ?? [];
      const updated = locked
        ? years.filter((y) => y !== financialYear)
        : Array.from(new Set([...years, financialYear]));
      await supabase.from("firms").update({ locked_financial_years: updated }).eq("id", firmId);
      setLocked(!locked);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to update lock");
    } finally { setSaving(false); }
  }

  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-50">
        <p className="text-xs font-semibold text-[#334155]">Year-End Close — FY {financialYear}</p>
        <p className="text-[10px] text-[#94A3B8] mt-0.5">
          Lock the financial year to prevent new journal entries. Locked years remain viewable.
        </p>
      </div>
      <div className="px-5 py-4 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className={`w-3 h-3 rounded-full ${loading ? "bg-[#E2E8F0]" : locked ? "bg-red-400" : "bg-green-400"}`} />
          <span className="text-sm text-[#334155]">
            {loading ? "Checking…" : locked ? `FY ${financialYear} is locked` : `FY ${financialYear} is open`}
          </span>
        </div>
        <button
          onClick={toggleLock}
          disabled={loading || saving}
          className={`flex items-center gap-2 text-xs px-4 py-2 rounded-lg font-medium transition-colors disabled:opacity-50 ${
            locked
              ? "bg-green-600 text-white hover:bg-green-700"
              : "bg-red-600 text-white hover:bg-red-700"
          }`}
        >
          {saving ? "Saving…" : locked ? "🔓 Unlock FY" : "🔒 Lock FY (Year-End Close)"}
        </button>
      </div>
      {locked && (
        <div className="mx-5 mb-4 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
          <p className="text-xs text-red-700">
            <strong>Locked:</strong> No new journal entries can be posted to FY {financialYear}.
            Corrections require unlocking or reversal entries in the next period.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Financial Reports ──────────────────────────────────────────────────────

function FinancialReports({ clientId, financialYear }: { clientId: string; financialYear: string }) {
  // Exports follow the same basis the user is viewing (URL-persisted).
  const searchParams = useSearchParams();
  const basis = (searchParams.get("basis") as "accrual" | "cash") ?? "accrual";
  const basisLabel = basis === "cash" ? "Cash" : "Accrual";

  const [sharedReports, setSharedReports] = useState<{
    id: string; report_type: string; report_label: string; financial_year: string; file_name: string; created_at: string; storage_path: string;
  }[]>([]);
  const [loadingShared, setLoadingShared] = useState(true);
  const [exporting, setExporting] = useState<string | null>(null);
  const [sharing, setSharing] = useState<string | null>(null);
  const [shareSuccess, setShareSuccess] = useState<string | null>(null);

  const loadShared = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    try {
      const supabase = getSupabaseClient();
      const { data } = await supabase.from("shared_reports")
        .select("id, report_type, report_label, financial_year, file_name, created_at, storage_path")
        .eq("client_id", clientId).order("created_at", { ascending: false }).limit(20);
      setSharedReports(data ?? []);
    } catch { /* skip */ } finally {
      setLoadingShared(false);
    }
  }, [clientId]);

  useEffect(() => { loadShared(); }, [loadShared]);

  // Build report rows from the backend reporting engine — the SAME API the
  // on-screen reports use — so exported figures match the screen exactly for the
  // selected basis. No journal aggregation in the browser (single source of truth).
  async function buildReportSheet(
    reportType: "pl" | "bs" | "trial",
  ): Promise<{ rows: Record<string, string | number>[]; sheetName: string }> {
    const { start, end } = fyDateRange(financialYear);
    const money = (p: number) => (p / 100).toFixed(2);

    if (reportType === "trial") {
      const res = (await api.accounting.trialBalance({ basis, as_of_date: end, client_id: clientId })) as
        { success: boolean; data: TBApiData | null };
      const d = res.data;
      const rows: Record<string, string | number>[] = (d?.lines ?? []).map((l) => ({
        "Account Code": l.account_code, "Account Name": l.account_name, "Type": l.account_type,
        "Debit (₹)": money(l.total_debit_paise), "Credit (₹)": money(l.total_credit_paise),
      }));
      rows.push({
        "Account Code": "TOTAL", "Account Name": "", "Type": "",
        "Debit (₹)": money(d?.total_debit_paise ?? 0), "Credit (₹)": money(d?.total_credit_paise ?? 0),
      });
      return { rows, sheetName: `Trial Balance ${basisLabel}`.slice(0, 31) };
    }

    if (reportType === "pl") {
      const res = (await api.accounting.profitLoss({ basis, start_date: start, end_date: end, client_id: clientId })) as
        { success: boolean; data: PLApiData | null };
      const d = res.data;
      const rows: Record<string, string | number>[] = [];
      for (const l of d?.revenue.lines ?? [])
        rows.push({ "Schedule III Category": plBucket("Revenue", l.account_subtype ?? null), "Account Code": l.account_code ?? "", "Account Name": l.account_name, "Type": "Revenue", "Amount (₹)": money(l.amount_paise) });
      rows.push({ "Schedule III Category": "", "Account Code": "", "Account Name": "Total Revenue", "Type": "", "Amount (₹)": money(d?.revenue.total_paise ?? 0) });
      for (const l of d?.operating_expenses.lines ?? [])
        rows.push({ "Schedule III Category": plBucket("Expense", l.account_subtype ?? null), "Account Code": l.account_code ?? "", "Account Name": l.account_name, "Type": "Expense", "Amount (₹)": money(l.amount_paise) });
      rows.push({ "Schedule III Category": "", "Account Code": "", "Account Name": "Total Expenses", "Type": "", "Amount (₹)": money(d?.operating_expenses.total_paise ?? 0) });
      rows.push({ "Schedule III Category": "", "Account Code": "", "Account Name": "Net Profit", "Type": "", "Amount (₹)": money(d?.net_profit_paise ?? 0) });
      return { rows, sheetName: `P&L ${basisLabel}`.slice(0, 31) };
    }

    const res = (await api.accounting.balanceSheet({ basis, as_of_date: end, client_id: clientId })) as
      { success: boolean; data: BSApiData | null };
    const d = res.data;
    const rows: Record<string, string | number>[] = [];
    const section = (secs: BSApiSection[] | undefined, type: string) => {
      for (const s of secs ?? []) for (const l of s.lines ?? [])
        rows.push({ "Schedule III Category": bsBucket(type, l.account_subtype ?? null), "Account Code": l.account_code ?? "", "Account Name": l.account_name, "Type": type, "Amount (₹)": money(l.balance_paise) });
    };
    section(d?.assets, "Asset");
    rows.push({ "Schedule III Category": "", "Account Code": "", "Account Name": "Total Assets", "Type": "", "Amount (₹)": money(d?.total_assets_paise ?? 0) });
    section(d?.liabilities, "Liability");
    section(d?.equity, "Equity");
    rows.push({ "Schedule III Category": "", "Account Code": "", "Account Name": "Total Equity & Liabilities", "Type": "", "Amount (₹)": money(d?.total_liabilities_equity_paise ?? 0) });
    return { rows, sheetName: `Balance Sheet ${basisLabel}`.slice(0, 31) };
  }

  async function exportXLSX(reportType: "pl" | "bs" | "trial") {
    setExporting(reportType);
    try {
      const XLSX = (await import("xlsx")).default;
      const { rows, sheetName } = await buildReportSheet(reportType);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), sheetName);
      const base = reportType === "pl" ? "PL" : reportType === "bs" ? "BalanceSheet" : "Trial-Balance";
      XLSX.writeFile(wb, `${base}-FY${financialYear}-${basisLabel}.xlsx`);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Export failed");
    } finally {
      setExporting(null);
    }
  }

  async function shareToPortal(reportType: "pl" | "bs" | "trial") {
    setSharing(reportType);
    try {
      const XLSX = (await import("xlsx")).default;
      const supabase = getSupabaseClient();
      const firmId = await getFirmId();
      const labelMap = { pl: "Profit & Loss", bs: "Balance Sheet", trial: "Trial Balance" };
      const label = `${labelMap[reportType]} (${basisLabel}) — FY ${financialYear}`;
      const fileName = `${reportType}-${basis}-FY${financialYear}-${Date.now()}.xlsx`;

      // Same backend-sourced report as the on-screen view and the XLSX export.
      const { rows, sheetName } = await buildReportSheet(reportType);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), sheetName);
      const buf = XLSX.write(wb, { type: "array", bookType: "xlsx" }) as ArrayBuffer;
      const file = new Blob([buf], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });

      const storagePath = `shared_reports/${clientId}/${fileName}`;
      const { error: uploadErr } = await supabase.storage
        .from("Documents")
        .upload(storagePath, file, { contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
      if (uploadErr) throw new Error(uploadErr.message);

      const { error: dbErr } = await supabase.from("shared_reports").insert({
        firm_id: firmId,
        client_id: clientId,
        report_type: reportType === "bs" ? "balance_sheet" : reportType,
        report_label: label,
        financial_year: financialYear,
        storage_path: storagePath,
        file_name: fileName,
        file_size_bytes: file.size,
      });
      if (dbErr) throw new Error(dbErr.message);

      setShareSuccess(reportType);
      setTimeout(() => setShareSuccess(null), 3000);
      await loadShared();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Share failed");
    } finally {
      setSharing(null);
    }
  }

  const REPORT_LINKS: { id: "pl" | "bs" | "trial"; label: string; description: string; icon: string }[] = [
    { id: "pl",    label: "Profit & Loss",  description: "Statement of P&L for FY — Schedule III Part II", icon: "📈" },
    { id: "bs",    label: "Balance Sheet",  description: "Balance Sheet as at FY end — Schedule III Part I", icon: "⚖️" },
    { id: "trial", label: "Trial Balance",  description: "Unadjusted trial balance for FY", icon: "📋" },
  ];

  return (
    <div className="space-y-5 max-w-3xl mx-auto">
      {/* Generate / export reports */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <p className="text-xs font-semibold text-[#334155]">Generate Reports — FY {financialYear}</p>
          <p className="text-[10px] text-[#94A3B8] mt-0.5">Export to XLSX or share directly to the client portal.</p>
        </div>
        <div className="divide-y divide-[#F8FAFC]">
          {REPORT_LINKS.map((r) => (
            <div key={r.id} className="px-5 py-4 flex items-center gap-4">
              <span className="text-2xl">{r.icon}</span>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-[#1E293B]">{r.label}</p>
                <p className="text-[10px] text-[#94A3B8] mt-0.5">{r.description}</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => window.print()}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569]"
                  title="Print as PDF"
                >
                  <Printer size={12} />
                </button>
                <button
                  onClick={() => exportXLSX(r.id)}
                  disabled={exporting === r.id}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569] disabled:opacity-50"
                >
                  <Download size={12} />
                  {exporting === r.id ? "…" : "XLSX"}
                </button>
                <button
                  onClick={() => shareToPortal(r.id)}
                  disabled={sharing === r.id}
                  className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50 ${
                    shareSuccess === r.id
                      ? "bg-green-100 text-green-700 border border-green-200"
                      : "bg-blue-600 text-white hover:bg-blue-700"
                  }`}
                >
                  <Share2 size={12} />
                  {sharing === r.id ? "Sharing…" : shareSuccess === r.id ? "Shared ✓" : "Share"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Year-End Close */}
      <YearEndClose financialYear={financialYear} />

      {/* Schedule III note */}
      <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-3">
        <p className="text-xs font-semibold text-blue-800">Schedule III Compliance</p>
        <p className="text-[11px] text-blue-600 mt-1">
          P&L and Balance Sheet are structured per <strong>Companies Act 2013, Schedule III</strong> (as amended).
          Account classification follows account_subtype mapping.
        </p>
      </div>

      {/* Shared reports history */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <p className="text-xs font-semibold text-[#334155]">Shared Reports</p>
          <p className="text-[10px] text-[#94A3B8] mt-0.5">Reports previously shared with this client via portal.</p>
        </div>
        {loadingShared ? (
          <div className="px-5 py-6"><div className="h-12 bg-[#F8FAFC] rounded animate-pulse" /></div>
        ) : sharedReports.length === 0 ? (
          <div className="text-center py-8 text-[#94A3B8] text-sm">No reports shared yet.</div>
        ) : (
          <table className="w-full text-xs">
            <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]"><th className="px-5 py-2 text-left font-semibold">Report</th><th className="px-3 py-2 text-left font-semibold">FY</th><th className="px-3 py-2 text-left font-semibold">File</th><th className="px-4 py-2 text-left font-semibold">Shared On</th><th className="px-3 py-2"></th></tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {sharedReports.map((r) => (
                <tr key={r.id} className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-2.5 font-medium text-[#1E293B]">{r.report_label}</td>
                  <td className="px-3 py-2.5 text-[#64748B]">FY {r.financial_year}</td>
                  <td className="px-3 py-2.5 text-[#64748B] font-mono text-[10px] truncate max-w-[130px]">{r.file_name}</td>
                  <td className="px-4 py-2.5 text-[#94A3B8]">{new Date(r.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</td>
                  <td className="px-3 py-2.5">
                    <button
                      onClick={async () => {
                        const supabase = getSupabaseClient();
                        const { data } = await supabase.storage.from("Documents").createSignedUrl(r.storage_path, 3600);
                        if (data) window.open(data.signedUrl, "_blank");
                      }}
                      className="text-[10px] text-blue-600 hover:underline flex items-center gap-1"
                    >
                      <Download size={10} /> Download
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ── Utility ────────────────────────────────────────────────────────────────

function groupBy<T>(arr: T[], key: (item: T) => string): Record<string, T[]> {
  return arr.reduce<Record<string, T[]>>((acc, item) => {
    const k = key(item);
    if (!acc[k]) acc[k] = [];
    acc[k].push(item);
    return acc;
  }, {});
}
