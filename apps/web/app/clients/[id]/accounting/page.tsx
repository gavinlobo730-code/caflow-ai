"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Plus, RefreshCw, CheckCircle, Printer, Download, Share2 } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { formatPaise, formatMoney } from "@/lib/services/formatting";
import { DataTable, downloadCsv } from "@/components/ui/data-table";
import { toCsv } from "@/lib/table/process";
import { AccountLookup } from "@/components/lookups/AccountLookup";
import type { Column, FilterDef } from "@/lib/table/types";
import { getFirmId } from "@/lib/data/getFirmId";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { api, type ReconciliationRun, type ReconciliationFinding } from "@/lib/api";
import { cachedReport, reportKey, clearReports } from "@/lib/accounting/reportCache";
import {
  plBucket, bsBucket, PL_REV_ORDER, PL_EXP_ORDER, BS_ASSET_ORDER, BS_LIAB_ORDER, BS_EQ_ORDER,
} from "@/lib/accounting/scheduleIiiCaptions";
import { writeTimelineEvent } from "@/lib/services/timeline";
import { todayLocalISO } from "@/lib/dateMath";
import PeriodPicker from "@/components/PeriodPicker";
import { splitPeriodColumns, periodSplitNotice, type PeriodMode, type Granularity } from "@/lib/dates/periods";
import { useLedgerSpan } from "@/lib/accounting/useLedgerSpan";
import { TableSkeleton, StatementSkeleton, MetricCardSkeleton } from "@/components/ui/skeleton";

// ── Tab definitions ────────────────────────────────────────────────────────

type AccountingTab =
  | "dashboard"
  | "coa"
  | "journal"
  | "trial"
  | "pl"
  | "balance-sheet"
  | "cashflow"
  | "approvals"
  | "verify-books"
  | "reports";

const TABS: { id: AccountingTab; label: string }[] = [
  { id: "dashboard",     label: "Dashboard" },
  { id: "coa",           label: "Accounts" },
  { id: "journal",       label: "Journal" },
  { id: "trial",         label: "Trial Balance" },
  { id: "pl",            label: "P & L" },
  { id: "balance-sheet", label: "Balance Sheet" },
  { id: "cashflow",      label: "Cash Flow" },
  { id: "approvals",     label: "Approvals" },
  { id: "verify-books",  label: "Verify Books" },
  { id: "reports",       label: "Reports" },
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
  // "manual" = a CA typed this in via New Journal Entry; anything else (or
  // null, for entries posted before this column was consistently set) is a
  // system-generated posting (invoice/bill GL entries, inventory COGS/
  // capitalisation, opening balances, corrections, etc.) — see the "Show
  // system entries" toggle below.
  source_type: string | null;
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
  // Authoritative Schedule III caption from the backend (domain/reporting/
  // builders.py via schedule_iii.pl_bucket), when the caller supplies one.
  // Optional so non-P&L callers of this type (Trial Balance, Balance Sheet
  // rows) are unaffected.
  schedule_iii_caption?: string | null;
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

// Report lines can carry a synthetic id (e.g. "__retained__" for a computed
// Retained Earnings rollup) instead of a real chart-of-accounts id — those
// have no ledger of their own, so drill-down must skip them.
function isDrillableAccount(id?: string): boolean {
  return !!id && !id.startsWith("__");
}

// Schedule III caption classification (plBucket/bsBucket/PL_REV_ORDER/
// PL_EXP_ORDER) now lives in lib/accounting/scheduleIiiCaptions.ts, imported
// above — pulled out of this file so it's covered by an automated test
// (a page.tsx with JSX can't be imported by the project's plain Node test
// runner).

// ── Main Page ──────────────────────────────────────────────────────────────

export default function AccountingPage() {
  const { clientId, financialYear } = useClientNav();
  const [tab, setTab] = useState<AccountingTab>("dashboard");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accsLoading, setAccsLoading] = useState(true);
  // Distinguishes "load failed" from "firm genuinely has zero accounts" — a
  // silently-swallowed fetch failure would otherwise render as an empty chart
  // of accounts, which every tab on this page (dashboard, journal lines,
  // bank posting) treats as authoritative.
  const [accountsError, setAccountsError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  // Multi-Currency Phase 5 — the FX Reports card (Reports tab) is shown ONLY when
  // multi-currency is active for this client, so an INR-only client sees no added
  // complexity (CLAUDE.md). Passed down to FinancialReports as `mcActive`.
  const [mcActive, setMcActive] = useState(false);
  // QuickBooks-style drill-down: set by clicking an amount on Trial Balance,
  // P&L, or the Balance Sheet. Lives outside `tab`/basis/FY state entirely, so
  // opening or closing it never touches the report underneath.
  const [drillDown, setDrillDown] = useState<{ accountId: string } | null>(null);
  const openDrillDown = useCallback((accountId: string) => setDrillDown({ accountId }), []);

  const loadAccounts = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setAccsLoading(true);
    try {
      const supabase = getSupabaseClient();
      const { data, error } = await selectAll(() => supabase
        .from("chart_of_accounts")
        .select("id, account_code, account_name, account_type, account_subtype, is_active, client_id")
        .or(`client_id.eq.${clientId},client_id.is.null`)
        .eq("is_active", true)
        .order("account_code")
        .order("id"));
      if (error) throw error;
      setAccounts((data as Account[]) ?? []);
      setAccountsError(null);
    } catch (e) {
      setAccountsError(e instanceof Error ? e.message : "Couldn't load the chart of accounts.");
    } finally {
      setAccsLoading(false);
    }
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



  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Sub-tab bar */}
      <div className="flex-shrink-0 overflow-x-auto px-6 pt-5 pb-0">
        <div className="flex gap-0.5 bg-[#F8FAFC] rounded-lg p-1 w-fit">
          {TABS.map((t) => (
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
          <ChartOfAccounts accounts={accounts} loading={accsLoading} error={accountsError} onRefresh={loadAccounts} />
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
        {tab === "approvals" && (
          <ApprovalQueue clientId={clientId} />
        )}
        {tab === "verify-books" && (
          <VerifyBooks clientId={clientId} />
        )}
        {tab === "reports" && (
          <FinancialReports clientId={clientId} financialYear={financialYear} mcActive={mcActive} />
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
  // Bank moved to its own section, so this card navigates across routes rather
  // than switching a tab on this page.
  const router = useRouter();
  const [stats, setStats] = useState({
    revenue_paise: 0, expenses_paise: 0, cash_paise: 0,
    unmatched_bank: 0, journal_count: 0,
  });
  const [recentEntries, setRecentEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  // Distinguishes "the fetch failed" from "this client genuinely has no
  // activity yet". Both used to render as ₹0 across every tile, which is the
  // worst possible way to be wrong on an accounting dashboard.
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    async function load() {
      setLoading(true);
      setLoadFailed(false);
      const supabase = getSupabaseClient();
      const { start, end } = fyDateRange(financialYear);

      // Headline figures come from the SINGLE backend reporting engine — never
      // recomputed in the browser (Phase 3: frontend renders only).
      //
      // All five requests go out together. They used to be four sequential
      // steps — P&L + cash flow, then the unmatched-bank count, then recent
      // entries, then the FY journal count — and none of the last three needs
      // anything the others return, so the dashboard sat through four round
      // trips to paint one screen. This is the page a CA lands on first.
      //
      // The two report calls keep a .catch each, which is what the try/catch
      // that used to wrap only them gave them: a reporting engine that is
      // briefly unavailable leaves its own tiles at zero and lets the rest of
      // the dashboard load. Merging them into the shared Promise.all without
      // that would have made an unrelated P&L timeout blank the journal list
      // too. The Supabase calls report failure through `error` instead of
      // rejecting, so they need no equivalent — hence the explicit check below.
      let revenue = 0, expenses = 0, cash = 0;
      try {
        const [plRes, cfRes, unmatched, recentRes, journalCount] = await Promise.all([
          (api.accounting.profitLoss({ client_id: clientId, start_date: start, end_date: end }) as Promise<{ success: boolean; data: { revenue: { total_paise: number }; cost_of_sales: { total_paise: number }; operating_expenses: { total_paise: number } } }>).catch(() => null),
          (api.accounting.cashFlow({ client_id: clientId, start_date: start, end_date: end }) as Promise<{ success: boolean; data: { closing_cash_paise: number } }>).catch(() => null),
          // Unmatched bank transactions
          supabase
            .from("bank_transactions")
            .select("id", { count: "exact", head: true })
            .eq("client_id", clientId)
            .eq("match_status", "unmatched"),
          // Recent journal entries
          supabase
            .from("journal_entries")
            .select("id, entry_date, reference_no, narration, entry_type, is_posted")
            .eq("client_id", clientId)
            .is("deleted_at", null)
            .order("created_at", { ascending: false })
            .limit(5),
          // Journal count for FY
          supabase
            .from("journal_entries")
            .select("id", { count: "exact", head: true })
            .eq("client_id", clientId)
            .eq("is_posted", true)
            .is("deleted_at", null)
            .gte("entry_date", start)
            .lte("entry_date", end),
        ]);

        if (plRes?.success) {
          revenue = plRes.data.revenue?.total_paise ?? 0;
          // Cost of Goods Sold lives in its own section, separate from
          // operating_expenses (see PLApiData above) — must be added in or the
          // dashboard's headline "Expenses" stat undercounts the same way the
          // P&L tab did.
          expenses = (plRes.data.cost_of_sales?.total_paise ?? 0) + (plRes.data.operating_expenses?.total_paise ?? 0);
        }
        if (cfRes?.success) cash = cfRes.data.closing_cash_paise ?? 0;

        if (unmatched.error || recentRes.error || journalCount.error) throw new Error("dashboard query failed");

        setStats({
          revenue_paise: revenue, expenses_paise: expenses, cash_paise: cash,
          unmatched_bank: unmatched.count ?? 0, journal_count: journalCount.count ?? 0,
        });
        setRecentEntries((recentRes.data as JournalEntry[]) ?? []);
      } catch {
        setStats({ revenue_paise: 0, expenses_paise: 0, cash_paise: 0, unmatched_bank: 0, journal_count: 0 });
        setRecentEntries([]);
        setLoadFailed(true);
      } finally {
        // In a finally, not on the happy path: this loader had no error
        // handling at all, so a rejected request left it with setLoading(true)
        // still in effect and the skeleton spun for as long as the CA cared to
        // wait. 28 other loaders across the app are still written that way —
        // see the note in the commit; they are a separate pass, not this one.
        setLoading(false);
      }
    }
    load();
  }, [clientId, financialYear]);

  const netPL = stats.revenue_paise - stats.expenses_paise;
  /** A figure, or "—" when the load failed. Never a zero we cannot stand behind. */
  const unknownIfFailed = (value: string) => (loadFailed ? "—" : value);

  if (loading) return (
    <div className="space-y-3 max-w-4xl mx-auto">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[...Array(4)].map((_, i) => <MetricCardSkeleton key={i} />)}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        {[...Array(3)].map((_, i) => <MetricCardSkeleton key={i} />)}
      </div>
    </div>
  );

  return (
    <div className="space-y-5 max-w-4xl mx-auto">
      {/* Say so, rather than presenting a failed load as a client with no
          activity. Zeros on an accounting dashboard are a claim about the
          books, and this one would be false. */}
      {loadFailed && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
          These figures could not be loaded, so they are not shown. Check your
          connection and reopen this tab.
        </div>
      )}

      {/* Stat strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <DashCard label="Revenue" value={unknownIfFailed(fmt(stats.revenue_paise))} accent="green" action={() => onNavigate("pl")} />
        <DashCard label="Expenses" value={unknownIfFailed(fmt(stats.expenses_paise))} accent="red" action={() => onNavigate("pl")} />
        <DashCard
          label={netPL >= 0 ? "Net Profit" : "Net Loss"}
          value={unknownIfFailed(fmt(Math.abs(netPL)))}
          accent={netPL >= 0 ? "emerald" : "orange"}
          action={() => onNavigate("pl")}
        />
        <DashCard label="Cash & Bank" value={unknownIfFailed(fmt(stats.cash_paise))} accent="blue" action={() => onNavigate("balance-sheet")} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <DashCard label="Posted Entries (FY)" value={unknownIfFailed(String(stats.journal_count))} accent="gray" action={() => onNavigate("journal")} />
        <DashCard label="Unmatched Bank Txns" value={unknownIfFailed(String(stats.unmatched_bank))} accent={!loadFailed && stats.unmatched_bank > 0 ? "amber" : "gray"} action={() => router.push(`/clients/${clientId}/bank/`)} />
        {/* Not behind the placeholder: the chart of accounts has its own loader
            and its own error, so it is still trustworthy when this one failed. */}
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

function ChartOfAccounts({ accounts, loading, error, onRefresh }: { accounts: Account[]; loading: boolean; error?: string | null; onRefresh: () => void }) {
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
        error={error}
        onRetry={onRefresh}
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
  // Separate from `error` above (which is the create/post-entry form's own
  // validation/save error) — a failed list fetch must not be conflated with,
  // or silently cleared by, an unrelated form action.
  const [entriesError, setEntriesError] = useState<string | null>(null);
  // Mirrors how QuickBooks/Xero/Zoho/Tally all scope their "Journal" screen to
  // manually-created entries by default, keeping every auto-posted GL entry
  // (invoices, bills, inventory COGS/capitalisation, opening balances, ...)
  // out of the CA's view of their own adjusting entries. The full picture is
  // still one click away via this toggle, or always visible per-account in
  // the Trial Balance / Ledger drill-down.
  const [showSystemEntries, setShowSystemEntries] = useState(false);
  const visibleEntries = useMemo(
    () => (showSystemEntries ? entries : entries.filter((e) => e.source_type === "manual")),
    [entries, showSystemEntries]
  );

  const totalDebit = lines.reduce((s, l) => s + l.debit_paise, 0);
  const totalCredit = lines.reduce((s, l) => s + l.credit_paise, 0);
  const isBalanced = totalDebit > 0 && totalDebit === totalCredit;

  const loadEntries = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setEntriesLoading(true);
    try {
      const supabase = getSupabaseClient();
      const { data, error: fetchErr } = await selectAll(() => supabase
        .from("journal_entries")
        // Alias the embed to `lines` so it matches the JournalEntry type (and the
        // amount column, which sums debit_paise across the entry's lines).
        .select("id, entry_date, reference_no, narration, entry_type, is_posted, source_type, lines:journal_lines(account_id, debit_paise, credit_paise, narration)")
        .eq("client_id", clientId)
        .is("deleted_at", null)
        .order("entry_date", { ascending: false })
        .order("id"));
      if (fetchErr) throw fetchErr;
      setEntries((data as unknown as JournalEntry[]) ?? []);
      setEntriesError(null);
    } catch (e) {
      setEntriesError(e instanceof Error ? e.message : "Couldn't load journal entries.");
    } finally {
      setEntriesLoading(false);
    }
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
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold text-[#334155]">All Journal Entries</p>
          <label className="flex items-center gap-1.5 text-xs text-[#64748B] cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showSystemEntries}
              onChange={(e) => setShowSystemEntries(e.target.checked)}
              className="rounded border-[#CBD5E1]"
            />
            Show system-generated entries
            <span className="text-[#94A3B8]">
              ({entries.length - entries.filter((e) => e.source_type === "manual").length} auto-posted)
            </span>
          </label>
        </div>
        <DataTable
          data={visibleEntries}
          columns={journalColumns}
          filters={journalFilters}
          getRowId={(e) => e.id}
          loading={entriesLoading}
          error={entriesError}
          onRetry={loadEntries}
          onRefresh={loadEntries}
          searchPlaceholder="Search by reference or narration…"
          initialSort={{ key: "entry_date", dir: "desc" }}
          exportFilename="journal"
          persistKey="accounting.journal"
          emptyTitle={!showSystemEntries && entries.length > 0 ? "No manual journal entries" : "No journal entries"}
          emptyDescription={
            !showSystemEntries && entries.length > 0
              ? "This client has system-generated entries only — tick “Show system-generated entries” above to see them."
              : "Post an entry above to see it listed here."
          }
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
  // Distinguishes "backend call failed" from "account genuinely has no posted
  // activity in this window" — matches TrialBalance/ProfitAndLoss/BalanceSheet
  // (audit M17): a large ledger's per-account fetch can fail/timeout, and
  // silently rendering that as "no transactions" would misreport a real account
  // as bookless instead of surfacing a retryable error.
  const [loadFailed, setLoadFailed] = useState(false);

  // The backend reporting engine computes opening/running/closing balances —
  // the browser only fetches and renders (Phase 3.4: no accounting math in React).
  const load = useCallback(async (force?: boolean) => {
    if (!accountId || !clientId || clientId === "_placeholder") { setLedger(null); setLoadFailed(false); return; }
    setLoading(true);
    try {
      const res = (await cachedReport(
        reportKey([clientId, "ledger", accountId, startDate, endDate]),
        () => api.accounting.ledger({
          client_id: clientId, account_id: accountId, start_date: startDate, end_date: endDate,
        }),
        { force },
      )) as { success: boolean; data: LedgerView | null };
      if (res.success && res.data) {
        setLedger(res.data);
        setLoadFailed(false);
      } else {
        // res.success===false only ever comes from a backend error path — a
        // genuinely empty account still returns success=true with empty lines.
        setLedger(null);
        setLoadFailed(true);
      }
    } catch {
      setLedger(null);
      setLoadFailed(true);
    } finally { setLoading(false); }
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
            loadFailed ? (
              <div className="text-center py-10">
                <p className="text-sm text-red-600 font-medium mb-2">Couldn&apos;t load this ledger — the request failed or timed out.</p>
                <button onClick={() => load(true)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
              </div>
            ) : (
              <div className="text-center py-10 text-[#94A3B8] text-sm">No posted transactions for this account in the selected range.</div>
            )
          ) : (
            <TableSkeleton cols={6} rows={6} />
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
  // True when the LAST load attempt failed (error/timeout) rather than
  // genuinely finding zero posted entries — a large ledger can otherwise look
  // bookless when the report simply couldn't load (found via a real 500 on a
  // paginated fetch for a 12k-entry client; see domain/reporting/sources.py).
  const [loadFailed, setLoadFailed] = useState(false);

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
        setLoadFailed(false);
      } else {
        // res.success===false only ever comes from a backend error path — a
        // genuinely empty ledger still returns success=true with empty lines.
        setRows([]);
        setTotals({ debit: 0, credit: 0, balanced: true });
        setLoadFailed(true);
      }
    } catch {
      // Backend error/timeout — degrade to empty, never an infinite skeleton
      // (audit M17), but flagged so the UI shows a retry banner rather than
      // rendering as if this client has no transactions.
      setRows([]);
      setTotals({ debit: 0, credit: 0, balanced: true });
      setLoadFailed(true);
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
      {loading ? <TableSkeleton cols={5} rows={6} /> : loaded && rows.length > 0 ? (
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
      ) : loaded ? (
        loadFailed ? (
          <div className="text-center py-12">
            <p className="text-sm text-red-600 font-medium mb-2">Couldn&apos;t load the trial balance — the request failed or timed out.</p>
            <button onClick={() => load(true)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
          </div>
        ) : (
          <div className="text-center py-12 text-[#94A3B8] text-sm">No posted journal entries for FY {financialYear}.</div>
        )
      ) : null}
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

      {loading ? <TableSkeleton cols={5} rows={5} /> : !loaded ? null : (
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

// Account-level line returned by the backend P&L (accrual & cash).
interface PLApiLine {
  account_id: string;
  account_name: string;
  account_code?: string;
  account_subtype?: string | null;
  // Authoritative Schedule III caption computed server-side (domain/
  // reporting/builders.py, via the same pl_bucket() the /schedule-iii
  // endpoint uses). Optional only so a not-yet-redeployed backend degrades
  // gracefully to the local plBucket() fallback below, never a blank/broken
  // grouping — Cloudflare Pages and Render deploy independently here.
  schedule_iii_caption?: string | null;
  amount_paise: number;
}
interface PLApiData {
  revenue: { lines: PLApiLine[]; total_paise: number };
  // Cost of Goods Sold — kept in its OWN section by the backend (domain/
  // reporting/builders.py::profit_loss), separate from operating_expenses, so
  // Gross Profit can be computed there. A Schedule III P&L has one "Cost of
  // Materials Consumed" caption that this section's lines bucket into
  // alongside operating_expenses' "Purchases" line (see plBucket below) —
  // omitting this section here silently dropped COGS from every on-screen
  // and exported P&L (same defect class as the backend fix in
  // domain/reporting/schedule_iii.py, task 2026-07-25).
  cost_of_sales: { lines: PLApiLine[]; total_paise: number };
  operating_expenses: { lines: PLApiLine[]; total_paise: number };
  net_profit_paise: number;
}

interface PLColumnResult {
  label: string;
  balances: AccountBalance[];
  totals: { revenue: number; expenses: number; net: number };
  // True when this column's backend call failed (error/timeout) rather than
  // genuinely returning zero rows — kept distinct so the UI never renders a
  // failed fetch as "no transactions" (a large-ledger client can otherwise
  // look bookless when the report simply couldn't load).
  error?: boolean;
}

function ProfitAndLoss({ clientId, financialYear, onDrillDown }: { clientId: string; financialYear: string; onDrillDown: (accountId: string) => void }) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const basis = (searchParams.get("basis") as "accrual" | "cash") ?? "accrual";

  // Period + "Display columns by" (QuickBooks-style multi-period comparison):
  // pick a window (PeriodPicker), then optionally split it into Monthly/
  // Quarterly/Yearly columns instead of one lump sum. Each column is an
  // independent backend profit_loss() call for its own [start,end] — the
  // frontend only decides which windows to ask for and lays results out
  // side by side (IT Act §44AA; no financial math here).
  const [periodMode, setPeriodMode] = useState<PeriodMode>("this_fy");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [granularity, setGranularity] = useState<Granularity>("total");
  // "All Time" means the client's actual posted books, not the 1900-2999
  // placeholder — without this a Monthly/Quarterly split over All Time exceeds
  // the column cap and silently collapses back to a single total.
  const ledgerSpan = useLedgerSpan(clientId);
  const columnDefs = useMemo(
    () => splitPeriodColumns(periodMode, financialYear, { from: customFrom, to: customTo }, granularity, undefined, ledgerSpan),
    [periodMode, financialYear, customFrom, customTo, granularity, ledgerSpan],
  );
  const splitNotice = useMemo(
    () => periodSplitNotice(periodMode, financialYear, { from: customFrom, to: customTo }, granularity, undefined, ledgerSpan),
    [periodMode, financialYear, customFrom, customTo, granularity, ledgerSpan],
  );

  const [columns, setColumns] = useState<PLColumnResult[]>([]);
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
    const results = await Promise.all(columnDefs.map(async (col): Promise<PLColumnResult> => {
      try {
        const res = (await cachedReport(
          reportKey([clientId, col.start, col.end, basis, "pl"]),
          () => api.accounting.profitLoss({ basis, start_date: col.start, end_date: col.end, client_id: clientId }),
          { force },
        )) as { success: boolean; data: PLApiData | null };
        // res.success===false only ever comes from a backend error path (see
        // api_response(False, ...) call sites) — a genuinely empty period still
        // returns success=true with empty line arrays. So this branch is always
        // a real failure, never legitimate emptiness; tag it as such.
        if (!res.success || !res.data) return { label: col.label, balances: [], totals: { revenue: 0, expenses: 0, net: 0 }, error: true };
        const d = res.data;
        // Cash-basis lines carry no account_code/account_subtype (the cash
        // engine doesn't classify by Schedule III subtype) — they default
        // to "" / null and fall into that bucket's catch-all below, same
        // shape as accrual otherwise, so both bases share one renderer.
        const toBal = (l: PLApiLine, type: string): AccountBalance => ({
          account_id: l.account_id, account_code: l.account_code ?? "",
          account_name: l.account_name, account_type: type,
          account_subtype: l.account_subtype ?? null,
          schedule_iii_caption: l.schedule_iii_caption ?? null,
          net_paise: l.amount_paise,
        });
        const balances = [
          ...(d.revenue?.lines ?? []).map((l) => toBal(l, "Revenue")),
          ...(d.cost_of_sales?.lines ?? []).map((l) => toBal(l, "Expense")),
          ...(d.operating_expenses?.lines ?? []).map((l) => toBal(l, "Expense")),
        ];
        const expensesTotal = (d.cost_of_sales?.total_paise ?? 0) + (d.operating_expenses?.total_paise ?? 0);
        return {
          label: col.label,
          balances,
          totals: { revenue: d.revenue?.total_paise ?? 0, expenses: expensesTotal, net: d.net_profit_paise ?? 0 },
        };
      } catch {
        // Backend error/timeout for this column — degrade the COLUMN to empty
        // rather than an infinite skeleton (audit M17), but tag it as a failure
        // (not silently-empty) so the UI can show a retry banner instead of
        // rendering a large ledger's report as if it had no transactions.
        return { label: col.label, balances: [], totals: { revenue: 0, expenses: 0, net: 0 }, error: true };
      }
    }));
    setColumns(results);
    setLoading(false); setLoaded(true);
  }, [clientId, basis, columnDefs]);

  useEffect(() => { load(); }, [load]);

  // Row identity (account name/subtype for bucket grouping) is the union of
  // every account with activity in ANY column; the VALUE shown for a row
  // always comes from that column's own lookup map — never re-derived
  // across columns, never summed client-side.
  const columnMaps = useMemo(() => columns.map((c) => new Map(c.balances.map((b) => [b.account_id, b.net_paise]))), [columns]);
  const unionAccounts = useMemo(() => {
    const byId = new Map<string, AccountBalance>();
    for (const col of columns) for (const b of col.balances) if (b.net_paise !== 0 && !byId.has(b.account_id)) byId.set(b.account_id, b);
    return Array.from(byId.values());
  }, [columns]);

  const revenue = unionAccounts.filter((b) => b.account_type === "Revenue");
  const expenses = unionAccounts.filter((b) => b.account_type === "Expense");
  // Prefer the backend's own Schedule III caption (single source of truth —
  // see PLApiLine above); plBucket() is only a fallback for the brief window
  // where the frontend has redeployed ahead of the backend.
  const captionOf = (b: AccountBalance) => b.schedule_iii_caption ?? plBucket(b.account_type, b.account_subtype);
  const revBuckets = groupBy(revenue, captionOf);
  const expBuckets = groupBy(expenses, captionOf);

  // Defence-in-depth against the exact 2026-07-25 incident: a caption
  // captionOf() produces that ISN'T one of the names above (a mismatch
  // between this file's vocabulary and the backend's pl_bucket(), or a
  // legitimate new category like "Tax Expense" this simpler tab doesn't have
  // a dedicated row for) used to make that whole bucket silently vanish from
  // the statement — the grand total stayed right (summed independently,
  // below) while the line itself just disappeared. Rendering every bucket
  // groupBy() actually produced, not just the ones this list anticipated,
  // means a naming mismatch can no longer hide money from the CA — worst
  // case it shows up out of statutory order under its own heading.
  const revExtraBuckets = Object.keys(revBuckets).filter((k) => !PL_REV_ORDER.includes(k));
  const expExtraBuckets = Object.keys(expBuckets).filter((k) => !PL_EXP_ORDER.includes(k));

  // Grand totals per column are the backend's own authoritative figures —
  // never re-derived from the union above.
  const totalRevenueByCol = columns.map((c) => c.totals.revenue);
  const totalExpensesByCol = columns.map((c) => c.totals.expenses);
  const netByCol = columns.map((c) => c.totals.net);
  const netPL = netByCol[netByCol.length - 1] ?? 0; // most-recent column's sign drives the Profit/Loss label

  const BasisToggle = () => (
    <div className="flex rounded border border-[#E2E8F0] overflow-hidden text-xs">
      <button onClick={() => updateBasis("accrual")} className={`px-3 py-1 font-medium transition-colors ${basis === "accrual" ? "bg-[#1E293B] text-white" : "bg-white text-[#64748B] hover:bg-[#F8FAFC]"}`}>Accrual</button>
      <button onClick={() => updateBasis("cash")} className={`px-3 py-1 font-medium border-l border-[#E2E8F0] transition-colors ${basis === "cash" ? "bg-[#1E293B] text-white" : "bg-white text-[#64748B] hover:bg-[#F8FAFC]"}`}>Cash</button>
    </div>
  );

  // CSV export — plain rupee numbers (no ₹ prefix / comma grouping), one
  // column per displayed period.
  const buildPlExportRows = (): Record<string, string>[] => {
    const rows: Record<string, string>[] = [];
    const pushRow = (section: string, particulars: string, values: number[]) => {
      const row: Record<string, string> = { section, particulars };
      columns.forEach((c, i) => { row[c.label] = ((values[i] ?? 0) / 100).toFixed(2); });
      rows.push(row);
    };
    [...PL_REV_ORDER, ...revExtraBuckets].forEach((bucket) => {
      (revBuckets[bucket] ?? []).forEach((item) => pushRow(bucket, item.account_name, columnMaps.map((m) => m.get(item.account_id) ?? 0)));
    });
    pushRow("", "Total Revenue", totalRevenueByCol);
    [...PL_EXP_ORDER, ...expExtraBuckets].forEach((bucket) => {
      (expBuckets[bucket] ?? []).forEach((item) => pushRow(bucket, item.account_name, columnMaps.map((m) => m.get(item.account_id) ?? 0)));
    });
    pushRow("", "Total Expenses", totalExpensesByCol);
    pushRow("", "Net Profit / (Loss)", netByCol);
    return rows;
  };
  const plExportColumns: Column<Record<string, string>>[] = [
    { key: "section", header: "Section", accessor: (r) => r.section },
    { key: "particulars", header: "Particulars", accessor: (r) => r.particulars },
    ...columns.map((c, i): Column<Record<string, string>> => ({ key: `col${i}`, header: `${c.label} (₹)`, accessor: (r) => r[c.label] ?? "" })),
  ];
  const plExportDisabled = !loaded || unionAccounts.length === 0;

  return (
    <div className="space-y-4 max-w-5xl mx-auto">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p className="text-xs font-semibold text-[#334155]">Statement of Profit & Loss</p>
        <div className="flex items-center gap-2 flex-wrap">
          <PeriodPicker
            mode={periodMode} onModeChange={setPeriodMode} financialYear={financialYear}
            customFrom={customFrom} customTo={customTo} onCustomFromChange={setCustomFrom} onCustomToChange={setCustomTo}
            granularity={granularity} onGranularityChange={setGranularity}
            ariaLabel="Period"
          />
          <BasisToggle />
          <button onClick={() => load(true)} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
          <button
            onClick={() => downloadCsv(`profit-and-loss-${financialYear}.csv`, toCsv(buildPlExportRows(), plExportColumns))}
            disabled={plExportDisabled}
            className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"
            title="Export CSV"
          >
            <Download size={13} />
          </button>
          <button onClick={() => window.print()} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]" title="Print"><Printer size={13} /></button>
        </div>
      </div>

      {/* Why a requested column split did not happen. Previously this collapsed
          in silence, so "Display: Quarterly" looked like a broken control. */}
      {splitNotice && (
        <div role="status" className="bg-slate-50 border border-[#E2E8F0] rounded px-3 py-2 text-xs text-[#64748B]">
          {splitNotice}
        </div>
      )}

      {/* Cash basis disclaimer — IT Act §44AA */}
      {basis === "cash" && (
        <div className="bg-amber-50 border border-amber-200 rounded px-3 py-2 text-xs text-amber-700">
          Cash basis — management reporting only (IT Act §44AA). Revenue shown only when collected; expenses when paid. GST returns are not affected.
        </div>
      )}

      {loading && <StatementSkeleton sections={2} rowsPerSection={3} />}

      {!loading && loaded && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-x-auto print:border-0">
          <div className="px-5 py-4 bg-[#F8FAFC] border-b border-[#F1F5F9] print:bg-white">
            <p className="text-xs font-bold text-[#475569] uppercase tracking-wide">Statement of Profit & Loss{basis === "cash" ? " (Cash Basis)" : ""}</p>
            <p className="text-[10px] text-[#94A3B8] mt-0.5">
              {columns.length > 1 ? `${columns.length} periods: ${columns[0]?.label} – ${columns[columns.length - 1]?.label}` : columns[0]?.label}
            </p>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#F1F5F9] text-[#94A3B8] text-[10px]">
                <th className="px-5 py-2 text-left font-semibold">Particulars</th>
                {columns.map((c, i) => <th key={i} className="px-4 py-2 text-right font-semibold whitespace-nowrap">{c.label} (₹)</th>)}
              </tr>
            </thead>
            <tbody>
              <tr><td colSpan={columns.length + 1} className="px-5 py-2 font-semibold text-[#334155] bg-[#F8FAFC] text-[10px] uppercase tracking-wide">I. Revenue</td></tr>
              {[...PL_REV_ORDER, ...revExtraBuckets].map((bucket) => {
                const items = revBuckets[bucket] ?? [];
                if (items.length === 0) return null;
                return <PLSection key={bucket} label={bucket} items={items} columnMaps={columnMaps} onDrillDown={onDrillDown} />;
              })}
              <tr className="border-t border-[#E2E8F0] font-semibold">
                <td className="px-5 py-2.5 text-[#1E293B]">Total Revenue (I)</td>
                {totalRevenueByCol.map((v, i) => <td key={i} className="px-4 py-2.5 text-right font-mono text-[#0F172A]">{fmt(v)}</td>)}
              </tr>
              <tr><td colSpan={columns.length + 1} className="px-5 py-2 font-semibold text-[#334155] bg-[#F8FAFC] text-[10px] uppercase tracking-wide">II. Expenses</td></tr>
              {[...PL_EXP_ORDER, ...expExtraBuckets].map((bucket) => {
                const items = expBuckets[bucket] ?? [];
                if (items.length === 0) return null;
                return <PLSection key={bucket} label={bucket} items={items} columnMaps={columnMaps} onDrillDown={onDrillDown} />;
              })}
              <tr className="border-t border-[#E2E8F0] font-semibold">
                <td className="px-5 py-2.5 text-[#1E293B]">Total Expenses (II)</td>
                {totalExpensesByCol.map((v, i) => <td key={i} className="px-4 py-2.5 text-right font-mono text-[#0F172A]">{fmt(v)}</td>)}
              </tr>
              <tr className={`border-t-2 border-gray-300 font-bold text-sm ${netPL >= 0 ? "bg-green-50" : "bg-red-50"}`}>
                <td className="px-5 py-3 text-[#0F172A]">{netPL >= 0 ? "III. Profit for the Period (I − II)" : "III. Loss for the Period (II − I)"}</td>
                {netByCol.map((v, i) => <td key={i} className={`px-4 py-3 text-right font-mono ${v >= 0 ? "text-green-700" : "text-red-700"}`}>{fmt(Math.abs(v))}</td>)}
              </tr>
            </tbody>
          </table>
          {columns.some((c) => c.error) ? (
            <div className="text-center py-12">
              <p className="text-sm text-red-600 font-medium mb-2">
                Couldn&apos;t load {columns.filter((c) => c.error).length > 1 ? "some periods" : "this report"} — the request failed or timed out.
              </p>
              <button onClick={() => load(true)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
            </div>
          ) : unionAccounts.length === 0 && (
            <div className="text-center py-12 text-[#94A3B8] text-sm">No posted entries with Revenue or Expense accounts in the selected period.</div>
          )}
        </div>
      )}
    </div>
  );
}

function PLSection({
  label, items, columnMaps, onDrillDown,
}: {
  label: string; items: AccountBalance[]; columnMaps: Map<string, number>[]; onDrillDown: (accountId: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const totals = columnMaps.map((m) => items.reduce((s, item) => s + (m.get(item.account_id) ?? 0), 0));
  return (
    <>
      <tr className="cursor-pointer hover:bg-[#F8FAFC]" onClick={() => setOpen((o) => !o)}>
        <td className="px-5 py-2 text-[#334155] font-medium pl-8">{label}</td>
        {totals.map((t, i) => <td key={i} className="px-4 py-2 text-right font-mono text-[#334155]">{fmt(t)}</td>)}
      </tr>
      {open && items.map((item) => (
        <tr key={item.account_id} className="text-[#94A3B8] hover:bg-[#F8FAFC] cursor-pointer" onClick={() => onDrillDown(item.account_id)}>
          <td className="px-5 py-1.5 pl-14 hover:text-blue-700 hover:underline">{item.account_name}</td>
          {columnMaps.map((m, i) => <td key={i} className="px-4 py-1.5 text-right font-mono hover:text-blue-700 hover:underline">{fmt(m.get(item.account_id) ?? 0)}</td>)}
        </tr>
      ))}
    </>
  );
}

// ── Balance Sheet ──────────────────────────────────────────────────────────
// Cumulative balances up to FY end date.
// Companies Act 2013, Schedule III, Part I.

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

interface BSColumnResult {
  label: string;
  balances: AccountBalance[];
  totals: { assets: number; liab: number; equity: number; liabEquity: number; balanced: boolean };
  // See PLColumnResult.error — a failed fetch must never render as "no data".
  error?: boolean;
}

function BalanceSheet({ clientId, financialYear, onDrillDown }: { clientId: string; financialYear: string; onDrillDown: (accountId: string) => void }) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const basis = (searchParams.get("basis") as "accrual" | "cash") ?? "accrual";

  // Period + "Display columns by" — see ProfitAndLoss for the shared design.
  // A Balance Sheet is a point-in-time snapshot, so each column fetches "as
  // of" its own END date rather than a flow over [start,end].
  const [periodMode, setPeriodMode] = useState<PeriodMode>("this_fy");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [granularity, setGranularity] = useState<Granularity>("total");
  // "All Time" means the client's actual posted books, not the 1900-2999
  // placeholder — without this a Monthly/Quarterly split over All Time exceeds
  // the column cap and silently collapses back to a single total.
  const ledgerSpan = useLedgerSpan(clientId);
  const columnDefs = useMemo(
    () => splitPeriodColumns(periodMode, financialYear, { from: customFrom, to: customTo }, granularity, undefined, ledgerSpan),
    [periodMode, financialYear, customFrom, customTo, granularity, ledgerSpan],
  );
  const splitNotice = useMemo(
    () => periodSplitNotice(periodMode, financialYear, { from: customFrom, to: customTo }, granularity, undefined, ledgerSpan),
    [periodMode, financialYear, customFrom, customTo, granularity, ledgerSpan],
  );

  const [columns, setColumns] = useState<BSColumnResult[]>([]);
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
    const results = await Promise.all(columnDefs.map(async (col): Promise<BSColumnResult> => {
      try {
        const res = (await cachedReport(
          reportKey([clientId, col.end, basis, "bs"]),
          () => api.accounting.balanceSheet({ basis, as_of_date: col.end, client_id: clientId }),
          { force },
        )) as { success: boolean; data: BSApiData | null };
        // See ProfitAndLoss.load — res.success===false is always a real backend
        // failure, never legitimate emptiness.
        if (!res.success || !res.data) return { label: col.label, balances: [], totals: { assets: 0, liab: 0, equity: 0, liabEquity: 0, balanced: true }, error: true };
        const d = res.data;
        const fromSection = (secs: BSApiSection[] | undefined, type: string): AccountBalance[] =>
          (secs ?? []).flatMap((s) => (s.lines ?? []).map((l) => ({
            account_id: l.account_id ?? l.account_name, account_code: l.account_code ?? "",
            account_name: l.account_name, account_type: type,
            account_subtype: l.account_subtype ?? null, net_paise: l.balance_paise,
          })));
        const balances = [
          ...fromSection(d.assets, "Asset"),
          ...fromSection(d.liabilities, "Liability"),
          ...fromSection(d.equity, "Equity"),
        ];
        return {
          label: col.label,
          balances,
          totals: {
            assets: d.total_assets_paise ?? 0,
            liab: d.liabilities?.[0]?.total_paise ?? 0,
            equity: d.equity?.[0]?.total_paise ?? 0,
            liabEquity: d.total_liabilities_equity_paise ?? 0,
            balanced: d.is_balanced ?? false,
          },
        };
      } catch {
        // Backend error/timeout for this column — degrade the COLUMN to empty
        // (audit M17), tagged as a failure so the UI never renders it as a
        // bookless client.
        return { label: col.label, balances: [], totals: { assets: 0, liab: 0, equity: 0, liabEquity: 0, balanced: true }, error: true };
      }
    }));
    setColumns(results);
    setLoading(false); setLoaded(true);
  }, [clientId, basis, columnDefs]);

  useEffect(() => { load(); }, [load]);

  const columnMaps = useMemo(() => columns.map((c) => new Map(c.balances.map((b) => [b.account_id, b.net_paise]))), [columns]);
  // Row identity is the union across columns. Equity rows are always kept
  // even at a zero balance (Share Capital/Reserves should still appear for
  // a new company) — Asset/Liability rows only appear where at least one
  // column has a nonzero balance, mirroring the original single-column filter.
  const unionAccounts = useMemo(() => {
    const byId = new Map<string, AccountBalance>();
    for (const col of columns) for (const b of col.balances) {
      const keep = b.account_type === "Equity" || b.net_paise !== 0;
      if (keep && !byId.has(b.account_id)) byId.set(b.account_id, b);
    }
    return Array.from(byId.values());
  }, [columns]);

  const assets = unionAccounts.filter((b) => b.account_type === "Asset");
  const liabilities = unionAccounts.filter((b) => b.account_type === "Liability");
  const equity = unionAccounts.filter((b) => b.account_type === "Equity");

  // Grand totals per column are the backend's own authoritative figures —
  // never re-derived from the union above.
  const totalAssetsByCol = columns.map((c) => c.totals.assets);
  const totalLiabByCol = columns.map((c) => c.totals.liab);
  const totalEquityByCol = columns.map((c) => c.totals.equity);
  const totalLiabEquityByCol = columns.map((c) => c.totals.liabEquity);
  const isBalanced = columns.length === 0 || columns.every((c) => c.totals.balanced);

  const assetBuckets = groupBy(assets, (b) => bsBucket(b.account_type, b.account_subtype));
  const liabBuckets = groupBy(liabilities, (b) => bsBucket(b.account_type, b.account_subtype));
  const equityBuckets = groupBy(equity, (b) => bsBucket(b.account_type, b.account_subtype));

  // Same defence-in-depth as the P&L tab (see ProfitAndLoss above): the Total
  // Assets/Liabilities/Equity figures are the backend's own totals, computed
  // independently of this grouping — if bsBucket() ever produced a caption
  // not in the lists above, that account's balance would silently vanish
  // from the visible breakdown while the total stayed (invisibly) correct.
  // bsBucket()'s current outputs are all covered by the lists above, but
  // rendering anything uncovered anyway means that can never again go
  // unnoticed the way Cost of Materials Consumed did.
  const assetExtraBuckets = Object.keys(assetBuckets).filter((k) => !BS_ASSET_ORDER.includes(k));
  const liabExtraBuckets = Object.keys(liabBuckets).filter((k) => !BS_LIAB_ORDER.includes(k));
  const eqExtraBuckets = Object.keys(equityBuckets).filter((k) => !BS_EQ_ORDER.includes(k));

  const BasisToggle = () => (
    <div className="flex rounded border border-[#E2E8F0] overflow-hidden text-xs">
      <button onClick={() => updateBasis("accrual")} className={`px-3 py-1 font-medium transition-colors ${basis === "accrual" ? "bg-[#1E293B] text-white" : "bg-white text-[#64748B] hover:bg-[#F8FAFC]"}`}>Accrual</button>
      <button onClick={() => updateBasis("cash")} className={`px-3 py-1 font-medium border-l border-[#E2E8F0] transition-colors ${basis === "cash" ? "bg-[#1E293B] text-white" : "bg-white text-[#64748B] hover:bg-[#F8FAFC]"}`}>Cash</button>
    </div>
  );

  // CSV export — plain rupee numbers (no ₹ prefix / comma grouping), one
  // column per displayed period.
  const buildBsExportRows = (): Record<string, string>[] => {
    const rows: Record<string, string>[] = [];
    const pushRow = (section: string, particulars: string, values: number[]) => {
      const row: Record<string, string> = { section, particulars };
      columns.forEach((c, i) => { row[c.label] = ((values[i] ?? 0) / 100).toFixed(2); });
      rows.push(row);
    };
    [...BS_EQ_ORDER, ...eqExtraBuckets].forEach((bucket) => {
      (equityBuckets[bucket] ?? []).forEach((item) => pushRow(bucket, item.account_name, columnMaps.map((m) => m.get(item.account_id) ?? 0)));
    });
    pushRow("", "Total Equity", totalEquityByCol);
    [...BS_LIAB_ORDER, ...liabExtraBuckets].forEach((bucket) => {
      (liabBuckets[bucket] ?? []).forEach((item) => pushRow(bucket, item.account_name, columnMaps.map((m) => m.get(item.account_id) ?? 0)));
    });
    pushRow("", "Total Liabilities", totalLiabByCol);
    [...BS_ASSET_ORDER, ...assetExtraBuckets].forEach((bucket) => {
      (assetBuckets[bucket] ?? []).forEach((item) => pushRow(bucket, item.account_name, columnMaps.map((m) => m.get(item.account_id) ?? 0)));
    });
    pushRow("", "Total Assets", totalAssetsByCol);
    return rows;
  };
  const bsExportColumns: Column<Record<string, string>>[] = [
    { key: "section", header: "Section", accessor: (r) => r.section },
    { key: "particulars", header: "Particulars", accessor: (r) => r.particulars },
    ...columns.map((c, i): Column<Record<string, string>> => ({ key: `col${i}`, header: `${c.label} (₹)`, accessor: (r) => r[c.label] ?? "" })),
  ];
  const bsExportDisabled = !loaded || unionAccounts.length === 0;

  return (
    <div className="space-y-4 max-w-5xl mx-auto">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p className="text-xs font-semibold text-[#334155]">Balance Sheet</p>
        <div className="flex items-center gap-2 flex-wrap">
          <PeriodPicker
            mode={periodMode} onModeChange={setPeriodMode} financialYear={financialYear}
            customFrom={customFrom} customTo={customTo} onCustomFromChange={setCustomFrom} onCustomToChange={setCustomTo}
            granularity={granularity} onGranularityChange={setGranularity}
            ariaLabel="As of / period"
          />
          <BasisToggle />
          <button onClick={() => load(true)} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
          <button
            onClick={() => downloadCsv(`balance-sheet-${financialYear}.csv`, toCsv(buildBsExportRows(), bsExportColumns))}
            disabled={bsExportDisabled}
            className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"
            title="Export CSV"
          >
            <Download size={13} />
          </button>
          <button onClick={() => window.print()} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]" title="Print"><Printer size={13} /></button>
        </div>
      </div>

      {/* Why a requested column split did not happen — see ProfitAndLoss. */}
      {splitNotice && (
        <div role="status" className="bg-slate-50 border border-[#E2E8F0] rounded px-3 py-2 text-xs text-[#64748B]">
          {splitNotice}
        </div>
      )}

      {/* Cash basis disclaimer — Companies Act §128 */}
      {basis === "cash" && (
        <div className="bg-amber-50 border border-amber-200 rounded px-3 py-2 text-xs text-amber-700">
          Cash basis — management reporting only (IT Act §145). Companies Act §128 requires accrual for statutory accounts. Unpaid receivables and payables are excluded from this view.
        </div>
      )}

      {loading && <StatementSkeleton sections={3} rowsPerSection={3} />}

      {!loading && loaded && (
        <div className="space-y-4">
          {columns.length > 1 && (
            <p className="text-[10px] text-[#94A3B8]">
              {columns.length} snapshots, each as of the end of its period: {columns[0]?.label} – {columns[columns.length - 1]?.label}
            </p>
          )}
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-x-auto">
            <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#F1F5F9]">
              <p className="text-xs font-bold text-[#475569] uppercase tracking-wide">I. Equity & Liabilities{basis === "cash" ? " (Cash Basis)" : ""}</p>
            </div>
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8] text-[10px]">
                  <th className="px-5 py-2 text-left font-semibold">Particulars</th>
                  {columns.map((c, i) => <th key={i} className="px-4 py-2 text-right font-semibold whitespace-nowrap">{c.label} (₹)</th>)}
                </tr>
              </thead>
              <tbody>
                <tr><td colSpan={columns.length + 1} className="px-5 py-2 font-semibold text-[#334155] bg-[#F8FAFC] text-[10px] uppercase tracking-wide">(A) Equity</td></tr>
                {[...BS_EQ_ORDER, ...eqExtraBuckets].map((bucket) => { const items = equityBuckets[bucket] ?? []; if (!items.length) return null; return <BSSectionRows key={bucket} label={bucket} items={items} columnMaps={columnMaps} onDrillDown={onDrillDown} />; })}
                <tr className="border-t border-[#E2E8F0] font-semibold">
                  <td className="px-5 py-2.5 text-[#1E293B]">Total Equity</td>
                  {totalEquityByCol.map((v, i) => <td key={i} className="px-4 py-2.5 text-right font-mono text-[#0F172A]">{fmt(v)}</td>)}
                </tr>
                <tr><td colSpan={columns.length + 1} className="px-5 py-2 font-semibold text-[#334155] bg-[#F8FAFC] text-[10px] uppercase tracking-wide">(B) Liabilities</td></tr>
                {[...BS_LIAB_ORDER, ...liabExtraBuckets].map((bucket) => { const items = liabBuckets[bucket] ?? []; if (!items.length) return null; return <BSSectionRows key={bucket} label={bucket} items={items} columnMaps={columnMaps} onDrillDown={onDrillDown} />; })}
                <tr className="border-t border-[#E2E8F0] font-semibold">
                  <td className="px-5 py-2.5 text-[#1E293B]">Total Liabilities</td>
                  {totalLiabByCol.map((v, i) => <td key={i} className="px-4 py-2.5 text-right font-mono text-[#0F172A]">{fmt(v)}</td>)}
                </tr>
                <tr className="border-t-2 border-gray-300 font-bold bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-[#0F172A] text-sm">Total Equity & Liabilities</td>
                  {totalLiabEquityByCol.map((v, i) => <td key={i} className="px-4 py-3 text-right font-mono text-[#0F172A] text-sm">{fmt(v)}</td>)}
                </tr>
              </tbody>
            </table>
          </div>
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-x-auto">
            <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#F1F5F9]">
              <p className="text-xs font-bold text-[#475569] uppercase tracking-wide">II. Assets{basis === "cash" ? " (Cash Basis)" : ""}</p>
            </div>
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8] text-[10px]">
                  <th className="px-5 py-2 text-left font-semibold">Particulars</th>
                  {columns.map((c, i) => <th key={i} className="px-4 py-2 text-right font-semibold whitespace-nowrap">{c.label} (₹)</th>)}
                </tr>
              </thead>
              <tbody>
                {[...BS_ASSET_ORDER, ...assetExtraBuckets].map((bucket) => { const items = assetBuckets[bucket] ?? []; if (!items.length) return null; return <BSSectionRows key={bucket} label={bucket} items={items} columnMaps={columnMaps} onDrillDown={onDrillDown} />; })}
                <tr className="border-t-2 border-gray-300 font-bold bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-[#0F172A] text-sm">Total Assets</td>
                  {totalAssetsByCol.map((v, i) => <td key={i} className="px-4 py-3 text-right font-mono text-[#0F172A] text-sm">{fmt(v)}</td>)}
                </tr>
              </tbody>
            </table>
          </div>
          <div className={`rounded-lg px-4 py-3 text-xs font-medium ${isBalanced ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
            {isBalanced ? "✓ Balance Sheet balances — Assets = Equity + Liabilities" : "✗ Out of balance in at least one period — check for unposted entries"}
          </div>
          {columns.some((c) => c.error) ? (
            <div className="text-center py-8">
              <p className="text-sm text-red-600 font-medium mb-2">
                Couldn&apos;t load {columns.filter((c) => c.error).length > 1 ? "some periods" : "this report"} — the request failed or timed out.
              </p>
              <button onClick={() => load(true)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
            </div>
          ) : unionAccounts.length === 0 && (
            <div className="text-center py-8 text-[#94A3B8] text-sm">No posted journal entries found for this client.</div>
          )}
        </div>
      )}
    </div>
  );
}

function BSSectionRows({
  label, items, columnMaps, onDrillDown,
}: {
  label: string; items: AccountBalance[]; columnMaps: Map<string, number>[]; onDrillDown: (accountId: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const totals = columnMaps.map((m) => items.reduce((s, b) => s + (m.get(b.account_id) ?? 0), 0));
  return (
    <>
      <tr className="cursor-pointer hover:bg-[#F8FAFC]" onClick={() => setOpen((o) => !o)}>
        <td className="px-5 py-2 text-[#334155] font-medium pl-8">{label}</td>
        {totals.map((t, i) => <td key={i} className="px-4 py-2 text-right font-mono text-[#334155]">{fmt(t)}</td>)}
      </tr>
      {open && items.map((item) => {
        const drillable = isDrillableAccount(item.account_id);
        return (
          <tr key={item.account_id} className={drillable ? "text-[#94A3B8] hover:bg-[#F8FAFC] cursor-pointer" : "text-[#94A3B8]"} onClick={drillable ? () => onDrillDown(item.account_id) : undefined}>
            <td className={`px-5 py-1.5 pl-14 ${drillable ? "hover:text-blue-700 hover:underline" : ""}`}>{item.account_name}</td>
            {columnMaps.map((m, i) => <td key={i} className={`px-4 py-1.5 text-right font-mono ${drillable ? "hover:text-blue-700 hover:underline" : ""}`}>{fmt(m.get(item.account_id) ?? 0)}</td>)}
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
  // See TrialBalance.loadFailed — distinguishes "backend call failed" from
  // "genuinely no cash flow data" so a large ledger never silently renders as bookless.
  const [loadFailed, setLoadFailed] = useState(false);

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
      // res.success===false only ever comes from a backend error path.
      setCf(res.success && res.data ? res.data : null);
      setLoadFailed(!res.success);
    } catch {
      // Backend error/timeout — degrade to empty, never an infinite skeleton
      // (audit M17), flagged so the UI shows a retry banner, not a false "no data".
      setCf(null);
      setLoadFailed(true);
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

      {loading && <StatementSkeleton sections={3} rowsPerSection={2} />}

      {!loading && loaded && !cf && (
        loadFailed ? (
          <div className="text-center py-12">
            <p className="text-sm text-red-600 font-medium mb-2">Couldn&apos;t load the cash flow statement — the request failed or timed out.</p>
            <button onClick={() => load(true)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
          </div>
        ) : (
          <div className="text-center py-12 text-[#94A3B8] text-sm">No posted journal entries for FY {financialYear}.</div>
        )
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
      if (!res.success) throw new Error("Couldn't load the approval queue.");
      setRows(res.data ?? []);
      setError(null);
    } catch (e) {
      setRows([]);
      setError(e instanceof Error ? e.message : "Couldn't load the approval queue.");
    } finally {
      setLoading(false);
    }
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

      {loading ? <TableSkeleton cols={6} rows={5} /> : rows.length === 0 ? (
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

// ── Verify Books (task #244) ─────────────────────────────────────────────
// On-demand books-integrity check, mirroring QuickBooks' Verify/Rebuild:
// trial balance, missing COGS/inventory-receipt journals, inventory
// cache-vs-ledger drift, AR/AP sub-ledger vs GL. Same engine
// (services/reconciliation_service.py) the nightly scheduled sweep already
// runs — this just triggers it live and shows the result. Report-only:
// nothing here auto-corrects a finding, matching the same "a human decides
// the fix" posture this session's own manual corrections used.
const SEVERITY_STYLE: Record<string, string> = {
  critical: "bg-red-50 text-red-700 border-red-100",
  warning: "bg-amber-50 text-amber-700 border-amber-100",
};

const CHECK_LABEL: Record<string, string> = {
  trial_balance: "Trial Balance",
  missing_cogs_journal: "Missing COGS Journal",
  missing_inventory_receipt_journal: "Missing Inventory Receipt Journal",
  inventory_cache_drift: "Inventory Cache Drift",
  ar_subledger_vs_gl: "AR Sub-ledger vs GL",
  ap_subledger_vs_gl: "AP Sub-ledger vs GL",
};

function checkLabel(name: string): string {
  return CHECK_LABEL[name] ?? (name.endsWith(".execution_error") ? `Check failed to run (${name.replace(".execution_error", "")})` : name);
}

function VerifyBooks({ clientId }: { clientId: string }) {
  const [runs, setRuns] = useState<ReconciliationRun[]>([]);
  const [activeRun, setActiveRun] = useState<ReconciliationRun | null>(null);
  const [findings, setFindings] = useState<ReconciliationFinding[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [loadingFindings, setLoadingFindings] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const loadRuns = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoadingRuns(true);
    try {
      const res = await api.reconciliation.listRuns(clientId);
      if (!res.success) throw new Error(res.error ?? "Couldn't load past runs.");
      const list = res.data?.runs ?? [];
      setRuns(list);
      if (list.length > 0) setActiveRun((prev) => prev ?? list[0]);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load past runs.");
    } finally {
      setLoadingRuns(false);
    }
  }, [clientId]);
  useEffect(() => { loadRuns(); }, [loadRuns]);

  const loadFindings = useCallback(async (runId: string) => {
    setLoadingFindings(true);
    try {
      const res = await api.reconciliation.getRun(runId);
      if (!res.success) throw new Error(res.error ?? "Couldn't load this run's findings.");
      setFindings(res.data?.findings ?? []);
      setActiveRun(res.data?.run ?? null);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load this run's findings.");
    } finally {
      setLoadingFindings(false);
    }
  }, []);
  // Depends on activeRun?.id, not activeRun itself — loadFindings below calls
  // setActiveRun with a freshly-fetched object each time, which would re-trigger
  // this effect every load if the whole object were a dependency.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (activeRun) loadFindings(activeRun.id); }, [activeRun?.id, loadFindings]);

  async function runVerification() {
    if (!clientId || clientId === "_placeholder") return;
    setVerifying(true); setError(null);
    try {
      const res = await api.reconciliation.verify(clientId);
      if (!res.success) throw new Error(res.error ?? "Verification failed to run.");
      await loadRuns();
      if (res.data?.run_id) await loadFindings(res.data.run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Verification failed to run.");
    } finally {
      setVerifying(false);
    }
  }

  async function resolveFinding(findingId: string) {
    setResolvingId(findingId);
    try {
      const res = await api.reconciliation.resolveFinding(findingId, noteDrafts[findingId] ?? "");
      if (!res.success) throw new Error(res.error ?? "Couldn't mark this finding resolved.");
      if (activeRun) await loadFindings(activeRun.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't mark this finding resolved.");
    } finally {
      setResolvingId(null);
    }
  }

  const openFindings = findings.filter((f) => !f.resolved_at);
  const resolvedFindings = findings.filter((f) => f.resolved_at);

  return (
    <div className="space-y-4 max-w-4xl mx-auto">
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 flex items-center justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-[#0F172A]">Verify Books</h3>
          <p className="text-xs text-[#64748B] mt-1">
            Checks trial balance, missing COGS/inventory journals, inventory cache drift, and AR/AP vs the GL — the
            same checks the nightly sweep runs, on demand.
          </p>
        </div>
        <button
          onClick={runVerification}
          disabled={verifying || !clientId || clientId === "_placeholder"}
          className="flex-shrink-0 text-xs font-medium px-4 py-2 bg-[#0F172A] text-white rounded-lg hover:bg-[#1E293B] disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {verifying ? "Verifying…" : "Verify Books"}
        </button>
      </div>

      {error && <p className="text-xs text-red-700 bg-red-50 border border-red-100 rounded-lg p-3">{error}</p>}

      {runs.length > 0 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-3 flex items-center gap-2 overflow-x-auto">
          <span className="text-[10px] text-[#94A3B8] flex-shrink-0 pl-1">Past runs:</span>
          {runs.map((r) => (
            <button
              key={r.id}
              onClick={() => setActiveRun(r)}
              className={`flex-shrink-0 text-xs px-2.5 py-1 rounded-md whitespace-nowrap ${
                activeRun?.id === r.id ? "bg-[#0F172A] text-white" : "bg-[#F1F5F9] text-[#475569] hover:bg-[#E2E8F0]"
              }`}
            >
              {String(r.started_at).slice(0, 16).replace("T", " ")} · {r.trigger === "manual" ? "Manual" : "Scheduled"} ·{" "}
              {r.status === "failed" ? "Failed" : `${r.findings_count} finding${r.findings_count === 1 ? "" : "s"}`}
            </button>
          ))}
        </div>
      )}

      {loadingRuns || loadingFindings ? (
        <TableSkeleton cols={3} rows={4} />
      ) : !activeRun ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-10 text-center text-sm text-[#94A3B8]">
          No verification has been run for this client yet. Click &ldquo;Verify Books&rdquo; to check it now.
        </div>
      ) : activeRun.status === "failed" ? (
        <div className="bg-red-50 border border-red-100 rounded-xl p-5 text-sm text-red-700">
          The verification run itself failed to complete: {activeRun.error}
        </div>
      ) : findings.length === 0 ? (
        <div className="bg-green-50 border border-green-100 rounded-xl p-10 text-center text-sm text-green-700">
          ✓ No issues found — the books reconcile across every check ({activeRun.checks_run} run).
        </div>
      ) : (
        <div className="space-y-3">
          {openFindings.map((f) => (
            <div key={f.id} className="bg-white rounded-xl border border-[#F1F5F9] p-4 space-y-2">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${SEVERITY_STYLE[f.severity] ?? SEVERITY_STYLE.warning}`}>
                      {f.severity === "critical" ? "Critical" : "Warning"}
                    </span>
                    <span className="text-[10px] text-[#94A3B8]">{checkLabel(f.check_name)}</span>
                  </div>
                  <p className="text-sm text-[#334155] mt-1.5">{f.summary}</p>
                  {f.amount_paise != null && (
                    <p className="text-xs text-[#64748B] mt-1 font-mono">{formatPaise(Math.abs(f.amount_paise))}</p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2 pt-1">
                <input
                  type="text"
                  placeholder="Resolution note (what did you find / fix)…"
                  value={noteDrafts[f.id] ?? ""}
                  onChange={(e) => setNoteDrafts((d) => ({ ...d, [f.id]: e.target.value }))}
                  className="flex-1 text-xs border border-[#E2E8F0] rounded-md px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-[#0F172A]"
                />
                <button
                  onClick={() => resolveFinding(f.id)}
                  disabled={resolvingId === f.id}
                  className="flex-shrink-0 text-xs px-3 py-1.5 bg-[#F1F5F9] text-[#334155] rounded-md hover:bg-[#E2E8F0] disabled:opacity-50"
                >
                  {resolvingId === f.id ? "Saving…" : "Mark Reviewed"}
                </button>
              </div>
            </div>
          ))}

          {resolvedFindings.length > 0 && (
            <details className="bg-white rounded-xl border border-[#F1F5F9] p-4">
              <summary className="text-xs text-[#64748B] cursor-pointer">
                {resolvedFindings.length} reviewed finding{resolvedFindings.length === 1 ? "" : "s"}
              </summary>
              <div className="mt-3 space-y-2">
                {resolvedFindings.map((f) => (
                  <div key={f.id} className="text-xs text-[#94A3B8] border-t border-[#F8FAFC] pt-2">
                    <span className={`px-1.5 py-0.5 rounded-full border mr-2 ${SEVERITY_STYLE[f.severity] ?? SEVERITY_STYLE.warning}`}>
                      {checkLabel(f.check_name)}
                    </span>
                    {f.summary}
                    {f.resolution_note && <div className="text-[#64748B] mt-0.5">Note: {f.resolution_note}</div>}
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}

      <p className="text-[10px] text-[#94A3B8] text-center">
        Report-only — nothing here is auto-corrected. A finding needs a deliberate fix (a correcting journal entry or
        ledger adjustment), reviewed and made by a CA, the same way any past finding would have been.
      </p>
    </div>
  );
}


// ── Financial Reports ──────────────────────────────────────────────────────

function YearEndClose({ financialYear }: { financialYear: string }) {
  const [locked, setLocked] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  // A failed lock-status check must never default to "open" (M17-class bug):
  // that would tell a CA it's safe to post into a FY that's actually locked,
  // or vice versa. Keep `locked` unknown (null) and surface the failure
  // instead of guessing.
  const [checkFailed, setCheckFailed] = useState(false);

  const check = useCallback(async () => {
    setLoading(true);
    try {
      const supabase = getSupabaseClient();
      const firmId = await getFirmId();
      const { data, error } = await supabase.from("firms").select("locked_financial_years").eq("id", firmId).maybeSingle();
      if (error) throw error;
      const years: string[] = (data as { locked_financial_years?: string[] } | null)?.locked_financial_years ?? [];
      setLocked(years.includes(financialYear));
      setCheckFailed(false);
    } catch {
      setLocked(null);
      setCheckFailed(true);
    } finally {
      setLoading(false);
    }
  }, [financialYear]);
  useEffect(() => { check(); }, [check]);

  async function toggleLock() {
    setSaving(true);
    try {
      const supabase = getSupabaseClient();
      const firmId = await getFirmId();
      const { data, error } = await supabase.from("firms").select("locked_financial_years").eq("id", firmId).maybeSingle();
      // A failed read here must abort, not proceed with years=[] — this is a
      // read-modify-write: writing back an empty/partial list would silently
      // wipe out every OTHER financial year this firm had locked.
      if (error) throw error;
      const years: string[] = (data as { locked_financial_years?: string[] } | null)?.locked_financial_years ?? [];
      const updated = locked
        ? years.filter((y) => y !== financialYear)
        : Array.from(new Set([...years, financialYear]));
      const { error: updErr } = await supabase.from("firms").update({ locked_financial_years: updated }).eq("id", firmId);
      if (updErr) throw updErr;
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
          <div className={`w-3 h-3 rounded-full ${loading ? "bg-[#E2E8F0]" : checkFailed ? "bg-amber-400" : locked ? "bg-red-400" : "bg-green-400"}`} />
          <span className="text-sm text-[#334155]">
            {loading ? "Checking…" : checkFailed ? `Couldn't verify FY ${financialYear}'s lock status` : locked ? `FY ${financialYear} is locked` : `FY ${financialYear} is open`}
          </span>
        </div>
        {checkFailed ? (
          <button onClick={check} className="text-xs px-4 py-2 rounded-lg font-medium border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#334155]">
            Retry
          </button>
        ) : (
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
        )}
      </div>
      {checkFailed && (
        <div className="mx-5 mb-4 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
          <p className="text-xs text-amber-800">
            Couldn&apos;t confirm whether FY {financialYear} is locked — the check failed or timed out.
            Lock/unlock is disabled until this is verified, to avoid overwriting the real status.
          </p>
        </div>
      )}
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

/**
 * Reports hub.
 *
 * Reports used to grow by adding a TAB — which is how Accounting reached 15 of
 * them, and how FX ended up a top-level sibling of the financial statements
 * despite being one more report. Here the unit of growth is a CARD inside a
 * group, so the tab bar stays fixed no matter how many reports land.
 *
 * Groups drill in rather than stacking: the index lists what is available, and
 * opening one replaces the index (with a way back). FX is the first such
 * drill-in; the next report follows the same shape.
 */
function FinancialReports({ clientId, financialYear, mcActive }: { clientId: string; financialYear: string; mcActive: boolean }) {
  // Which grouped report is open; null = the hub index.
  const [openReport, setOpenReport] = useState<null | "fx">(null);
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
      // Prefer the backend's own Schedule III caption (single source of
      // truth); plBucket() is only a fallback for the brief window where the
      // frontend has redeployed ahead of the backend.
      const captionOf = (l: PLApiLine, type: string) => l.schedule_iii_caption ?? plBucket(type, l.account_subtype ?? null);
      for (const l of d?.revenue.lines ?? [])
        rows.push({ "Schedule III Category": captionOf(l, "Revenue"), "Account Code": l.account_code ?? "", "Account Name": l.account_name, "Type": "Revenue", "Amount (₹)": money(l.amount_paise) });
      rows.push({ "Schedule III Category": "", "Account Code": "", "Account Name": "Total Revenue", "Type": "", "Amount (₹)": money(d?.revenue.total_paise ?? 0) });
      // Cost of Goods Sold — own section, separate from operating_expenses
      // (see PLApiData above); both bucket into "Cost of Materials Consumed"
      // via the shared caption, so must be exported alongside
      // operating_expenses or the XLSX undercounts Total Expenses the same
      // way the on-screen P&L did.
      for (const l of d?.cost_of_sales.lines ?? [])
        rows.push({ "Schedule III Category": captionOf(l, "Expense"), "Account Code": l.account_code ?? "", "Account Name": l.account_name, "Type": "Expense", "Amount (₹)": money(l.amount_paise) });
      for (const l of d?.operating_expenses.lines ?? [])
        rows.push({ "Schedule III Category": captionOf(l, "Expense"), "Account Code": l.account_code ?? "", "Account Name": l.account_name, "Type": "Expense", "Amount (₹)": money(l.amount_paise) });
      rows.push({ "Schedule III Category": "", "Account Code": "", "Account Name": "Total Expenses", "Type": "", "Amount (₹)": money((d?.cost_of_sales.total_paise ?? 0) + (d?.operating_expenses.total_paise ?? 0)) });
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

  if (openReport === "fx") {
    return (
      <div className="space-y-3">
        <button
          onClick={() => setOpenReport(null)}
          className="text-xs text-[#64748B] hover:text-[#334155] flex items-center gap-1"
        >
          ← All reports
        </button>
        <FXReports clientId={clientId} financialYear={financialYear} />
      </div>
    );
  }

  return (
    <div className="space-y-5 max-w-3xl mx-auto">
      {/* ── Financial statements ── */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <p className="text-xs font-semibold text-[#334155]">Financial Statements — FY {financialYear}</p>
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

      {/* ── Foreign currency ──
          Only when multi-currency is actually active for this client, so an
          INR-only client sees no added complexity (CLAUDE.md). Previously this
          gated a whole top-level tab; now it gates one card. */}
      {mcActive && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50">
            <p className="text-xs font-semibold text-[#334155]">Foreign Currency</p>
            <p className="text-[10px] text-[#94A3B8] mt-0.5">Exposure, realized and unrealized gain/loss, open items, and the rate audit trail.</p>
          </div>
          <button
            onClick={() => setOpenReport("fx")}
            className="w-full px-5 py-4 flex items-center gap-4 text-left hover:bg-[#F8FAFC] transition-colors"
          >
            <span className="text-2xl">🌐</span>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-[#1E293B]">FX Reports</p>
              <p className="text-[10px] text-[#94A3B8] mt-0.5">Five views across your foreign-currency documents</p>
            </div>
            <span className="text-xs text-[#94A3B8]">Open →</span>
          </button>
        </div>
      )}

      {/* ── Year-End ── */}
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
          <TableSkeleton cols={5} rows={2} bare />
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
