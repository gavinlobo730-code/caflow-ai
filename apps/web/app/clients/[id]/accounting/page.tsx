"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { Plus, RefreshCw, Upload, CheckCircle, X, Printer, FileText, Download, Share2 } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { writeTimelineEvent } from "@/lib/services/timeline";
import {
  parseCSV,
  importBankStatement,
  getBankStatements,
  getBankTransactions,
  postBankTransaction,
  type BankStatement,
  type BankTransaction,
} from "@/lib/data/bankStatements";

// ── Tab definitions ────────────────────────────────────────────────────────

type AccountingTab =
  | "dashboard"
  | "coa"
  | "journal"
  | "ledger"
  | "trial"
  | "pl"
  | "balance-sheet"
  | "banks"
  | "reconciliation"
  | "reports";

const TABS: { id: AccountingTab; label: string }[] = [
  { id: "dashboard",     label: "Dashboard" },
  { id: "coa",           label: "Accounts" },
  { id: "journal",       label: "Journal" },
  { id: "ledger",        label: "Ledger" },
  { id: "trial",         label: "Trial Balance" },
  { id: "pl",            label: "P & L" },
  { id: "balance-sheet", label: "Balance Sheet" },
  { id: "banks",         label: "Banks" },
  { id: "reconciliation",label: "Reconciliation" },
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
  lines: { account_id: string; debit_paise: number; credit_paise: number; narration: string | null }[];
}

interface LedgerLine {
  id: string;
  entry_date: string;
  narration: string;
  reference_no: string | null;
  debit_paise: number;
  credit_paise: number;
  running_balance_paise: number;
  is_debit: boolean;
}

interface TrialRow {
  account_id: string;
  account_code: string;
  account_name: string;
  account_type: string;
  total_debit_paise: number;
  total_credit_paise: number;
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

function fmt(paise: number): string {
  if (paise === 0) return "—";
  const rupees = Math.abs(paise) / 100;
  return "₹" + new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rupees);
}

function fyDateRange(fy: string): { start: string; end: string } {
  const [startYear] = fy.split("-");
  const y = parseInt(startYear, 10);
  return { start: `${y}-04-01`, end: `${y + 1}-03-31` };
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

  const loadAccounts = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setAccsLoading(true);
    const supabase = getSupabaseClient();
    const { data } = await supabase
      .from("chart_of_accounts")
      .select("id, account_code, account_name, account_type, account_subtype, is_active, client_id")
      .or(`client_id.eq.${clientId},client_id.is.null`)
      .eq("is_active", true)
      .order("account_code");
    setAccounts((data as Account[]) ?? []);
    setAccsLoading(false);
  }, [clientId]);

  useEffect(() => { loadAccounts(); }, [loadAccounts]);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Sub-tab bar */}
      <div className="flex-shrink-0 overflow-x-auto px-6 pt-5 pb-0">
        <div className="flex gap-0.5 bg-[#0e1017] rounded-lg p-1 w-fit">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap ${
                tab === t.id ? "bg-[#131620] text-white/85 shadow-sm" : "text-white/40 hover:text-white/65"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 pb-6 pt-4 min-h-0">
        {tab === "dashboard" && (
          <AccountingDashboard clientId={clientId} financialYear={financialYear} accounts={accounts} onNavigate={setTab} />
        )}
        {tab === "coa" && (
          <ChartOfAccounts accounts={accounts} loading={accsLoading} onRefresh={loadAccounts} />
        )}
        {tab === "journal" && (
          <JournalEntryForm accounts={accounts} clientId={clientId} financialYear={financialYear} onPosted={loadAccounts} />
        )}
        {tab === "ledger" && (
          <GeneralLedger accounts={accounts} clientId={clientId} financialYear={financialYear} />
        )}
        {tab === "trial" && (
          <TrialBalance clientId={clientId} financialYear={financialYear} />
        )}
        {tab === "pl" && (
          <ProfitAndLoss clientId={clientId} financialYear={financialYear} />
        )}
        {tab === "balance-sheet" && (
          <BalanceSheet clientId={clientId} financialYear={financialYear} />
        )}
        {tab === "banks" && (
          <BankAccounts clientId={clientId} financialYear={financialYear} />
        )}
        {tab === "reconciliation" && (
          <BankReconciliation accounts={accounts} clientId={clientId} financialYear={financialYear} />
        )}
        {tab === "reports" && (
          <FinancialReports clientId={clientId} financialYear={financialYear} />
        )}
      </div>
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

      // Fetch posted journal lines for FY
      const { data: lines } = await supabase
        .from("journal_lines")
        .select("debit_paise, credit_paise, chart_of_accounts!inner(account_type, account_subtype), journal_entries!inner(entry_date, is_posted, client_id, deleted_at)")
        .eq("journal_entries.client_id", clientId)
        .eq("journal_entries.is_posted", true)
        .is("journal_entries.deleted_at", null)
        .gte("journal_entries.entry_date", start)
        .lte("journal_entries.entry_date", end);

      let revenue = 0, expenses = 0, cash = 0;
      for (const row of (lines ?? []) as unknown as Array<{
        debit_paise: number; credit_paise: number;
        chart_of_accounts: { account_type: string; account_subtype: string | null };
      }>) {
        const { account_type, account_subtype } = row.chart_of_accounts;
        const net = row.credit_paise - row.debit_paise;
        if (account_type === "Revenue") revenue += net;
        if (account_type === "Expense") expenses += (row.debit_paise - row.credit_paise);
        const sub = (account_subtype ?? "").toLowerCase();
        if (account_type === "Asset" && (sub.includes("cash") || sub.includes("bank")))
          cash += row.debit_paise - row.credit_paise;
      }

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

  if (loading) return <div className="space-y-4 max-w-4xl">{[...Array(3)].map((_, i) => <div key={i} className="h-24 rounded-xl bg-[#0e1017] animate-pulse" />)}</div>;

  return (
    <div className="space-y-5 max-w-4xl">
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
        <div className="bg-[#131620] rounded-xl border border-white/[0.05] overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-50 flex items-center justify-between">
            <p className="text-xs font-semibold text-white/65">Recent Entries</p>
            <button onClick={() => onNavigate("journal")} className="text-xs text-blue-600 hover:underline">View all</button>
          </div>
          <table className="w-full text-xs">
            <tbody className="divide-y divide-white/[0.03]">
              {recentEntries.map((e) => (
                <tr key={e.id} className="hover:bg-[#0e1017]">
                  <td className="px-4 py-2.5 text-white/40 whitespace-nowrap w-24">{e.entry_date}</td>
                  <td className="px-3 py-2.5 text-white/65 truncate max-w-xs">{e.narration}</td>
                  <td className="px-3 py-2.5 text-white/30">{e.entry_type}</td>
                  <td className="px-4 py-2.5">
                    <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${e.is_posted ? "bg-green-100 text-green-700" : "bg-white/[0.06] text-white/40"}`}>
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
    gray: "bg-[#131620] border-white/[0.05]",
  };
  const textColors: Record<string, string> = {
    green: "text-green-800", red: "text-red-800", emerald: "text-emerald-800",
    orange: "text-orange-800", blue: "text-blue-800", amber: "text-amber-800", gray: "text-white/75",
  };
  return (
    <button
      onClick={action}
      className={`rounded-xl border p-4 text-left transition-shadow hover:shadow-sm ${colors[accent] ?? colors.gray}`}
    >
      <p className="text-[10px] font-medium text-white/40 mb-1">{label}</p>
      <p className={`text-lg font-bold tabular-nums ${textColors[accent] ?? "text-white/75"}`}>{value}</p>
    </button>
  );
}

// ── Chart of Accounts ──────────────────────────────────────────────────────

function ChartOfAccounts({ accounts, loading, onRefresh }: { accounts: Account[]; loading: boolean; onRefresh: () => void }) {
  const TYPE_ORDER = ["Asset", "Liability", "Equity", "Revenue", "Expense"];
  const grouped = TYPE_ORDER.reduce<Record<string, Account[]>>((acc, type) => {
    acc[type] = accounts.filter((a) => a.account_type === type);
    return acc;
  }, {});

  const TYPE_COLORS: Record<string, string> = {
    Asset: "text-blue-600 bg-blue-50", Liability: "text-orange-600 bg-orange-50",
    Equity: "text-purple-600 bg-purple-50", Revenue: "text-green-600 bg-green-50", Expense: "text-red-600 bg-red-50",
  };

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex items-center justify-between">
        <p className="text-xs text-white/40">{accounts.length} accounts</p>
        <button onClick={onRefresh} className="p-1.5 rounded border border-white/[0.07] hover:bg-[#0e1017] text-white/40">
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {loading ? (
        <div className="space-y-3">{[...Array(3)].map((_, i) => <div key={i} className="h-24 rounded-lg bg-[#0e1017] animate-pulse" />)}</div>
      ) : (
        TYPE_ORDER.map((type) =>
          grouped[type].length > 0 ? (
            <div key={type} className="bg-[#131620] rounded-xl border border-white/[0.05] overflow-hidden">
              <div className="px-4 py-2.5 border-b border-gray-50 flex items-center gap-2">
                <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${TYPE_COLORS[type]}`}>{type}</span>
                <span className="text-xs text-white/30">{grouped[type].length} accounts</span>
              </div>
              <table className="w-full text-xs">
                <tbody className="divide-y divide-white/[0.03]">
                  {grouped[type].map((a) => (
                    <tr key={a.id} className="hover:bg-[#0e1017]">
                      <td className="px-4 py-2 font-mono text-white/40 w-20">{a.account_code}</td>
                      <td className="px-3 py-2 font-medium text-white/75">{a.account_name}</td>
                      <td className="px-3 py-2 text-white/30">{a.account_subtype ?? ""}</td>
                      <td className="px-4 py-2 text-right">
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#0e1017] text-white/30">
                          {a.client_id ? "Client" : "Firm"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null
        )
      )}
      {!loading && accounts.length === 0 && (
        <div className="text-center py-12 text-white/30 text-sm">No accounts found. Accounts are seeded from the firm-level chart of accounts.</div>
      )}
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
  const [entryDate, setEntryDate] = useState(new Date().toISOString().split("T")[0]);
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
  const [recentEntries, setRecentEntries] = useState<JournalEntry[]>([]);

  const totalDebit = lines.reduce((s, l) => s + l.debit_paise, 0);
  const totalCredit = lines.reduce((s, l) => s + l.credit_paise, 0);
  const isBalanced = totalDebit > 0 && totalDebit === totalCredit;

  const loadRecent = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    const supabase = getSupabaseClient();
    const { data } = await supabase
      .from("journal_entries")
      .select("id, entry_date, reference_no, narration, entry_type, is_posted, journal_lines(account_id, debit_paise, credit_paise, narration)")
      .eq("client_id", clientId)
      .is("deleted_at", null)
      .order("entry_date", { ascending: false })
      .limit(5);
    setRecentEntries((data as unknown as JournalEntry[]) ?? []);
  }, [clientId]);

  useEffect(() => { loadRecent(); }, [loadRecent, success]);

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
      const supabase = getSupabaseClient();
      // Enforce FY lock — prevent posting to a locked financial year
      const firmId = await getFirmId();
      const { data: firmRow } = await supabase.from("firms").select("locked_financial_years").eq("id", firmId).maybeSingle();
      const lockedYears: string[] = (firmRow as { locked_financial_years?: string[] } | null)?.locked_financial_years ?? [];
      if (lockedYears.includes(financialYear)) {
        setSaving(false);
        setError(`FY ${financialYear} is locked. New entries cannot be posted. To make corrections, unlock the FY or use a reversal entry in the next period.`);
        return;
      }
      const { data: entry, error: entryErr } = await supabase
        .from("journal_entries")
        .insert({ firm_id: firmId, client_id: clientId, entry_date: entryDate, reference_no: referenceNo.trim() || null, narration: narration.trim(), entry_type: entryType, is_posted: post, posted_at: post ? new Date().toISOString() : null })
        .select("id").single();
      if (entryErr || !entry) throw new Error(entryErr?.message ?? "Failed to create entry");
      const { error: linesErr } = await supabase.from("journal_lines").insert(
        validLines.map((l) => ({ journal_entry_id: entry.id, account_id: l.account_id, debit_paise: l.debit_paise, credit_paise: l.credit_paise, narration: l.narration.trim() || null }))
      );
      if (linesErr) throw new Error(linesErr.message);
      try {
        await writeTimelineEvent({ client_id: clientId, firm_id: firmId, financial_year: financialYear, category: "accounting", event_type: post ? "journal_entry_posted" : "journal_entry_saved", severity: "info", title: post ? "Journal entry posted" : "Journal entry saved (draft)", description: narration.trim(), entity_type: "journal_entry", entity_id: entry.id, actor_type: "user" });
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
    <div className="space-y-5 max-w-3xl">
      {success && <div className="bg-green-50 border border-green-100 rounded-lg px-4 py-3 text-sm text-green-700 font-medium">Journal entry saved successfully.</div>}
      <div className="bg-[#131620] rounded-xl border border-white/[0.05] p-5 space-y-4">
        <h3 className="text-sm font-semibold text-white/85">New Journal Entry</h3>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-xs font-medium text-white/55 mb-1">Date *</label>
            <input type="date" value={entryDate} onChange={(e) => setEntryDate(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-white/[0.07] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-xs font-medium text-white/55 mb-1">Type</label>
            <select value={entryType} onChange={(e) => setEntryType(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-white/[0.07] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
              {ENTRY_TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-white/55 mb-1">Reference No.</label>
            <input value={referenceNo} onChange={(e) => setReferenceNo(e.target.value)} placeholder="INV-001" className="w-full px-3 py-1.5 text-sm border border-white/[0.07] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-white/55 mb-1">Narration *</label>
          <input value={narration} onChange={(e) => setNarration(e.target.value)} placeholder="Being goods sold to ABC Ltd..." className="w-full px-3 py-1.5 text-sm border border-white/[0.07] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-white/[0.05] text-white/30">
                <th className="pb-2 text-left font-semibold">Account</th>
                <th className="pb-2 text-right font-semibold w-28">Debit (₹)</th>
                <th className="pb-2 text-right font-semibold w-28">Credit (₹)</th>
                <th className="pb-2 text-left font-semibold pl-3">Narration</th>
                <th className="pb-2 w-6" />
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.03]">
              {lines.map((line, idx) => (
                <tr key={idx}>
                  <td className="py-1.5 pr-2">
                    <select value={line.account_id} onChange={(e) => setLine(idx, { account_id: e.target.value })} className="w-full px-2 py-1 border border-white/[0.07] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs">
                      <option value="">— Select account —</option>
                      {["Asset","Liability","Equity","Revenue","Expense"].map((type) => (
                        <optgroup key={type} label={type}>
                          {accounts.filter((a) => a.account_type === type).map((a) => (
                            <option key={a.id} value={a.id}>{a.account_code} — {a.account_name}</option>
                          ))}
                        </optgroup>
                      ))}
                    </select>
                  </td>
                  <td className="py-1.5 px-2">
                    <input type="number" min="0" step="0.01" value={line.debit_paise === 0 ? "" : (line.debit_paise / 100).toFixed(2)} onChange={(e) => { const v = Math.round(parseFloat(e.target.value || "0") * 100); setLine(idx, { debit_paise: v, credit_paise: v > 0 ? 0 : line.credit_paise }); }} placeholder="0.00" className="w-full px-2 py-1 border border-white/[0.07] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs" />
                  </td>
                  <td className="py-1.5 px-2">
                    <input type="number" min="0" step="0.01" value={line.credit_paise === 0 ? "" : (line.credit_paise / 100).toFixed(2)} onChange={(e) => { const v = Math.round(parseFloat(e.target.value || "0") * 100); setLine(idx, { credit_paise: v, debit_paise: v > 0 ? 0 : line.debit_paise }); }} placeholder="0.00" className="w-full px-2 py-1 border border-white/[0.07] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs" />
                  </td>
                  <td className="py-1.5 pl-3"><input value={line.narration} onChange={(e) => setLine(idx, { narration: e.target.value })} placeholder="optional" className="w-full px-2 py-1 border border-white/[0.07] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs" /></td>
                  <td className="py-1.5 pl-1">{lines.length > 2 && <button onClick={() => removeLine(idx)} className="text-white/20 hover:text-red-400 font-bold">×</button>}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-white/[0.05] text-xs font-semibold">
                <td className="pt-2 text-white/40">Total</td>
                <td className="pt-2 text-right text-white/65 px-2">{totalDebit > 0 ? `₹${(totalDebit/100).toFixed(2)}` : "—"}</td>
                <td className="pt-2 text-right text-white/65 px-2">{totalCredit > 0 ? `₹${(totalCredit/100).toFixed(2)}` : "—"}</td>
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
          <button onClick={() => handleSave(false)} disabled={saving || !isBalanced} className="text-xs px-4 py-2 border border-white/[0.07] rounded-lg hover:bg-[#0e1017] disabled:opacity-40">Save Draft</button>
          <button onClick={() => handleSave(true)} disabled={saving || !isBalanced} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">{saving ? "Saving…" : "Post Entry"}</button>
        </div>
      </div>

      {recentEntries.length > 0 && (
        <div className="bg-[#131620] rounded-xl border border-white/[0.05] overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-50"><p className="text-xs font-semibold text-white/65">Recent Entries</p></div>
          <table className="w-full text-xs">
            <thead><tr className="border-b border-gray-50 text-white/30"><th className="px-4 py-2 text-left font-semibold">Date</th><th className="px-3 py-2 text-left font-semibold">Narration</th><th className="px-3 py-2 text-left font-semibold">Type</th><th className="px-3 py-2 text-right font-semibold">Amount</th><th className="px-4 py-2 text-left font-semibold">Status</th></tr></thead>
            <tbody className="divide-y divide-white/[0.03]">
              {recentEntries.map((e) => {
                const totalDr = (e.lines ?? []).reduce((s, l) => s + l.debit_paise, 0);
                return (
                  <tr key={e.id} className="hover:bg-[#0e1017]">
                    <td className="px-4 py-2 text-white/40 whitespace-nowrap">{e.entry_date}</td>
                    <td className="px-3 py-2 text-white/65 truncate max-w-[200px]">{e.narration}</td>
                    <td className="px-3 py-2 text-white/30">{e.entry_type}</td>
                    <td className="px-3 py-2 text-right font-mono text-white/65">₹{(totalDr/100).toFixed(2)}</td>
                    <td className="px-4 py-2"><span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${e.is_posted ? "bg-green-100 text-green-700" : "bg-white/[0.06] text-white/40"}`}>{e.is_posted ? "Posted" : "Draft"}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── General Ledger ─────────────────────────────────────────────────────────

function GeneralLedger({ accounts, clientId, financialYear }: { accounts: Account[]; clientId: string; financialYear: string }) {
  const [selectedAccountId, setSelectedAccountId] = useState("");
  const [lines, setLines] = useState<LedgerLine[]>([]);
  const [loading, setLoading] = useState(false);

  async function loadLedger(accountId: string) {
    if (!accountId || !clientId || clientId === "_placeholder") return;
    setLoading(true);
    const { start, end } = fyDateRange(financialYear);
    const supabase = getSupabaseClient();
    const { data } = await supabase
      .from("journal_lines")
      .select("id, debit_paise, credit_paise, narration, journal_entries!inner(entry_date, reference_no, narration, is_posted, client_id, deleted_at)")
      .eq("account_id", accountId)
      .eq("journal_entries.client_id", clientId)
      .eq("journal_entries.is_posted", true)
      .is("journal_entries.deleted_at", null)
      .gte("journal_entries.entry_date", start)
      .lte("journal_entries.entry_date", end)
      .order("journal_entries(entry_date)", { ascending: true });

    if (data) {
      let running = 0;
      const mapped: LedgerLine[] = (data as unknown as Array<{
        id: string; debit_paise: number; credit_paise: number; narration: string | null;
        journal_entries: { entry_date: string; reference_no: string | null; narration: string };
      }>).map((row) => {
        running += row.debit_paise - row.credit_paise;
        return { id: row.id, entry_date: row.journal_entries.entry_date, narration: row.narration ?? row.journal_entries.narration, reference_no: row.journal_entries.reference_no, debit_paise: row.debit_paise, credit_paise: row.credit_paise, running_balance_paise: running, is_debit: running >= 0 };
      });
      setLines(mapped);
    }
    setLoading(false);
  }

  return (
    <div className="space-y-4 max-w-4xl">
      <div className="bg-[#131620] rounded-xl border border-white/[0.05] p-4">
        <label className="block text-xs font-medium text-white/55 mb-1.5">Select Account</label>
        <select value={selectedAccountId} onChange={(e) => { setSelectedAccountId(e.target.value); loadLedger(e.target.value); }} className="w-full max-w-xs px-3 py-2 text-sm border border-white/[0.07] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="">— Choose account —</option>
          {["Asset","Liability","Equity","Revenue","Expense"].map((type) => (
            <optgroup key={type} label={type}>
              {accounts.filter((a) => a.account_type === type).map((a) => <option key={a.id} value={a.id}>{a.account_code} — {a.account_name}</option>)}
            </optgroup>
          ))}
        </select>
      </div>

      {selectedAccountId && (
        <div className="bg-[#131620] rounded-xl border border-white/[0.05] overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-50 flex items-center justify-between">
            <p className="text-xs font-semibold text-white/65">Ledger — FY {financialYear} — {accounts.find((a) => a.id === selectedAccountId)?.account_name}</p>
            {loading && <RefreshCw size={13} className="animate-spin text-white/30" />}
          </div>
          {!loading && lines.length > 0 ? (
            <table className="w-full text-xs">
              <thead><tr className="border-b border-white/[0.05] text-white/30"><th className="px-4 py-2.5 text-left font-semibold">Date</th><th className="px-3 py-2.5 text-left font-semibold">Particulars</th><th className="px-3 py-2.5 text-left font-semibold">Ref</th><th className="px-3 py-2.5 text-right font-semibold">Debit</th><th className="px-3 py-2.5 text-right font-semibold">Credit</th><th className="px-4 py-2.5 text-right font-semibold">Balance</th></tr></thead>
              <tbody className="divide-y divide-white/[0.03]">
                {lines.map((l) => (
                  <tr key={l.id} className="hover:bg-[#0e1017]">
                    <td className="px-4 py-2 text-white/40 whitespace-nowrap">{l.entry_date}</td>
                    <td className="px-3 py-2 text-white/65">{l.narration}</td>
                    <td className="px-3 py-2 font-mono text-white/30">{l.reference_no ?? "—"}</td>
                    <td className="px-3 py-2 text-right font-mono text-white/65">{fmt(l.debit_paise)}</td>
                    <td className="px-3 py-2 text-right font-mono text-white/65">{fmt(l.credit_paise)}</td>
                    <td className={`px-4 py-2 text-right font-mono font-semibold ${l.is_debit ? "text-blue-700" : "text-orange-700"}`}>
                      {fmt(Math.abs(l.running_balance_paise))}<span className="text-[10px] font-normal ml-1 opacity-60">{l.is_debit ? "Dr" : "Cr"}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : !loading ? (
            <div className="text-center py-10 text-white/30 text-sm">No posted transactions for this account in FY {financialYear}.</div>
          ) : null}
        </div>
      )}
    </div>
  );
}

// ── Trial Balance ──────────────────────────────────────────────────────────

function TrialBalance({ clientId, financialYear }: { clientId: string; financialYear: string }) {
  const [rows, setRows] = useState<TrialRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    const { start, end } = fyDateRange(financialYear);
    const supabase = getSupabaseClient();
    const { data } = await supabase
      .from("journal_lines")
      .select("debit_paise, credit_paise, chart_of_accounts!inner(id, account_code, account_name, account_type), journal_entries!inner(entry_date, is_posted, client_id, deleted_at)")
      .eq("journal_entries.client_id", clientId)
      .eq("journal_entries.is_posted", true)
      .is("journal_entries.deleted_at", null)
      .gte("journal_entries.entry_date", start)
      .lte("journal_entries.entry_date", end);

    if (data) {
      const map: Record<string, TrialRow> = {};
      for (const row of data as unknown as Array<{
        debit_paise: number; credit_paise: number;
        chart_of_accounts: { id: string; account_code: string; account_name: string; account_type: string };
      }>) {
        const acc = row.chart_of_accounts;
        if (!map[acc.id]) map[acc.id] = { account_id: acc.id, account_code: acc.account_code, account_name: acc.account_name, account_type: acc.account_type, total_debit_paise: 0, total_credit_paise: 0 };
        map[acc.id].total_debit_paise += row.debit_paise;
        map[acc.id].total_credit_paise += row.credit_paise;
      }
      setRows(Object.values(map).sort((a, b) => a.account_code.localeCompare(b.account_code)));
    }
    setLoading(false); setLoaded(true);
  }, [clientId, financialYear]);

  useEffect(() => { load(); }, [load]);

  const grandDebit = rows.reduce((s, r) => s + r.total_debit_paise, 0);
  const grandCredit = rows.reduce((s, r) => s + r.total_credit_paise, 0);
  const isBalanced = grandDebit === grandCredit;

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-white/65">Trial Balance — FY {financialYear}</p>
        <button onClick={load} className="p-1.5 rounded border border-white/[0.07] hover:bg-[#0e1017] text-white/40"><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
      </div>
      {loading ? <div className="h-40 rounded-lg bg-[#0e1017] animate-pulse" /> : loaded && rows.length > 0 ? (
        <div className="bg-[#131620] rounded-xl border border-white/[0.05] overflow-hidden">
          <table className="w-full text-xs">
            <thead><tr className="border-b border-white/[0.05] text-white/30"><th className="px-4 py-3 text-left font-semibold">Code</th><th className="px-3 py-3 text-left font-semibold">Account</th><th className="px-3 py-3 text-left font-semibold">Type</th><th className="px-3 py-3 text-right font-semibold">Debit (₹)</th><th className="px-4 py-3 text-right font-semibold">Credit (₹)</th></tr></thead>
            <tbody className="divide-y divide-white/[0.03]">
              {rows.map((r) => (
                <tr key={r.account_id} className="hover:bg-[#0e1017]">
                  <td className="px-4 py-2 font-mono text-white/40">{r.account_code}</td>
                  <td className="px-3 py-2 font-medium text-white/75">{r.account_name}</td>
                  <td className="px-3 py-2 text-white/30">{r.account_type}</td>
                  <td className="px-3 py-2 text-right font-mono text-white/65">{r.total_debit_paise > 0 ? fmt(r.total_debit_paise) : "—"}</td>
                  <td className="px-4 py-2 text-right font-mono text-white/65">{r.total_credit_paise > 0 ? fmt(r.total_credit_paise) : "—"}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-white/[0.07] font-semibold">
                <td colSpan={3} className="px-4 py-3 text-white/65 text-sm">Total</td>
                <td className="px-3 py-3 text-right font-mono text-white/85 text-sm">₹{(grandDebit/100).toFixed(2)}</td>
                <td className="px-4 py-3 text-right font-mono text-white/85 text-sm">₹{(grandCredit/100).toFixed(2)}</td>
              </tr>
              <tr><td colSpan={5} className="px-4 pb-3">{isBalanced ? <span className="text-xs text-green-600 font-medium">✓ Trial Balance is balanced</span> : <span className="text-xs text-red-600 font-medium">✗ Out of balance by ₹{(Math.abs(grandDebit-grandCredit)/100).toFixed(2)}</span>}</td></tr>
            </tfoot>
          </table>
        </div>
      ) : loaded ? <div className="text-center py-12 text-white/30 text-sm">No posted journal entries for FY {financialYear}.</div> : null}
    </div>
  );
}

// ── Profit & Loss ──────────────────────────────────────────────────────────
// Computed from journal_lines for the FY. Accounts classified per
// Companies Act 2013, Schedule III, Part II.

function ProfitAndLoss({ clientId, financialYear }: { clientId: string; financialYear: string }) {
  const [balances, setBalances] = useState<AccountBalance[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    const { start, end } = fyDateRange(financialYear);
    const supabase = getSupabaseClient();
    const { data } = await supabase
      .from("journal_lines")
      .select("debit_paise, credit_paise, chart_of_accounts!inner(id, account_code, account_name, account_type, account_subtype), journal_entries!inner(entry_date, is_posted, client_id, deleted_at)")
      .eq("journal_entries.client_id", clientId)
      .eq("journal_entries.is_posted", true)
      .is("journal_entries.deleted_at", null)
      .gte("journal_entries.entry_date", start)
      .lte("journal_entries.entry_date", end)
      .in("chart_of_accounts.account_type", ["Revenue", "Expense"]);

    const map: Record<string, AccountBalance> = {};
    for (const row of (data ?? []) as unknown as Array<{
      debit_paise: number; credit_paise: number;
      chart_of_accounts: { id: string; account_code: string; account_name: string; account_type: string; account_subtype: string | null };
    }>) {
      const acc = row.chart_of_accounts;
      if (!map[acc.id]) map[acc.id] = { account_id: acc.id, account_code: acc.account_code, account_name: acc.account_name, account_type: acc.account_type, account_subtype: acc.account_subtype, net_paise: 0 };
      // Revenue: credit = positive, debit = negative
      // Expense: debit = positive, credit = negative
      if (acc.account_type === "Revenue") map[acc.id].net_paise += row.credit_paise - row.debit_paise;
      else map[acc.id].net_paise += row.debit_paise - row.credit_paise;
    }
    setBalances(Object.values(map).filter((b) => b.net_paise !== 0).sort((a, b) => a.account_code.localeCompare(b.account_code)));
    setLoading(false); setLoaded(true);
  }, [clientId, financialYear]);

  useEffect(() => { load(); }, [load]);

  const revenue = balances.filter((b) => b.account_type === "Revenue");
  const expenses = balances.filter((b) => b.account_type === "Expense");
  const totalRevenue = revenue.reduce((s, b) => s + b.net_paise, 0);
  const totalExpenses = expenses.reduce((s, b) => s + b.net_paise, 0);
  const netPL = totalRevenue - totalExpenses;

  // Group into Schedule III P&L buckets
  const revBuckets = groupBy(revenue, (b) => plBucket(b.account_type, b.account_subtype));
  const expBuckets = groupBy(expenses, (b) => plBucket(b.account_type, b.account_subtype));

  const PL_REV_ORDER = ["Revenue from Operations", "Other Income"];
  const PL_EXP_ORDER = ["Cost of Materials Consumed", "Employee Benefit Expense", "Finance Costs", "Depreciation & Amortisation", "Other Expenses"];

  return (
    <div className="space-y-4 max-w-2xl">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-white/65">Statement of Profit & Loss — FY {financialYear}</p>
        <div className="flex gap-2">
          <button onClick={load} className="p-1.5 rounded border border-white/[0.07] hover:bg-[#0e1017] text-white/40"><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
          <button onClick={() => window.print()} className="p-1.5 rounded border border-white/[0.07] hover:bg-[#0e1017] text-white/40" title="Print"><Printer size={13} /></button>
        </div>
      </div>

      {loading && <div className="h-48 rounded-lg bg-[#0e1017] animate-pulse" />}
      {!loading && loaded && (
        <div className="bg-[#131620] rounded-xl border border-white/[0.05] overflow-hidden print:border-0">
          <div className="px-5 py-4 bg-[#0e1017] border-b border-white/[0.05] print:bg-[#131620]">
            <p className="text-xs font-bold text-white/55 uppercase tracking-wide">Statement of Profit & Loss</p>
            <p className="text-[10px] text-white/30 mt-0.5">For the year ended 31 March {parseInt(financialYear.split("-")[0]) + 1}</p>
          </div>
          <table className="w-full text-xs">
            <thead><tr className="border-b border-white/[0.05] text-white/30 text-[10px]"><th className="px-5 py-2 text-left font-semibold">Particulars</th><th className="px-4 py-2 text-right font-semibold">Amount (₹)</th></tr></thead>
            <tbody>
              {/* Revenue */}
              <tr><td colSpan={2} className="px-5 py-2 font-semibold text-white/65 bg-[#0e1017] text-[10px] uppercase tracking-wide">I. Revenue</td></tr>
              {PL_REV_ORDER.map((bucket) => {
                const items = revBuckets[bucket] ?? [];
                if (items.length === 0) return null;
                const total = items.reduce((s, b) => s + b.net_paise, 0);
                return (
                  <PLSection key={bucket} label={bucket} items={items} total={total} />
                );
              })}
              <tr className="border-t border-white/[0.07] font-semibold">
                <td className="px-5 py-2.5 text-white/75">Total Revenue (I)</td>
                <td className="px-4 py-2.5 text-right font-mono text-white/85">{fmt(totalRevenue)}</td>
              </tr>

              {/* Expenses */}
              <tr><td colSpan={2} className="px-5 py-2 font-semibold text-white/65 bg-[#0e1017] text-[10px] uppercase tracking-wide">II. Expenses</td></tr>
              {PL_EXP_ORDER.map((bucket) => {
                const items = expBuckets[bucket] ?? [];
                if (items.length === 0) return null;
                const total = items.reduce((s, b) => s + b.net_paise, 0);
                return <PLSection key={bucket} label={bucket} items={items} total={total} />;
              })}
              <tr className="border-t border-white/[0.07] font-semibold">
                <td className="px-5 py-2.5 text-white/75">Total Expenses (II)</td>
                <td className="px-4 py-2.5 text-right font-mono text-white/85">{fmt(totalExpenses)}</td>
              </tr>

              {/* Net P&L */}
              <tr className={`border-t-2 border-gray-300 font-bold text-sm ${netPL >= 0 ? "bg-green-50" : "bg-red-50"}`}>
                <td className="px-5 py-3 text-white/85">
                  {netPL >= 0 ? "III. Profit for the Year (I − II)" : "III. Loss for the Year (II − I)"}
                </td>
                <td className={`px-4 py-3 text-right font-mono ${netPL >= 0 ? "text-green-700" : "text-red-700"}`}>
                  {fmt(Math.abs(netPL))}
                </td>
              </tr>
            </tbody>
          </table>
          {balances.length === 0 && <div className="text-center py-12 text-white/30 text-sm">No posted entries with Revenue or Expense accounts in FY {financialYear}.</div>}
        </div>
      )}
    </div>
  );
}

function PLSection({ label, items, total }: { label: string; items: AccountBalance[]; total: number }) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <tr className="cursor-pointer hover:bg-[#0e1017]" onClick={() => setOpen((o) => !o)}>
        <td className="px-5 py-2 text-white/65 font-medium pl-8">{label}</td>
        <td className="px-4 py-2 text-right font-mono text-white/65">{fmt(total)}</td>
      </tr>
      {open && items.map((item) => (
        <tr key={item.account_id} className="text-white/30">
          <td className="px-5 py-1.5 pl-14">{item.account_name}</td>
          <td className="px-4 py-1.5 text-right font-mono">{fmt(item.net_paise)}</td>
        </tr>
      ))}
    </>
  );
}

// ── Balance Sheet ──────────────────────────────────────────────────────────
// Cumulative balances up to FY end date.
// Companies Act 2013, Schedule III, Part I.

function BalanceSheet({ clientId, financialYear }: { clientId: string; financialYear: string }) {
  const [balances, setBalances] = useState<AccountBalance[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    const { end } = fyDateRange(financialYear);
    const supabase = getSupabaseClient();

    // Cumulative: all posted entries up to FY end date
    const { data } = await supabase
      .from("journal_lines")
      .select("debit_paise, credit_paise, chart_of_accounts!inner(id, account_code, account_name, account_type, account_subtype), journal_entries!inner(entry_date, is_posted, client_id, deleted_at)")
      .eq("journal_entries.client_id", clientId)
      .eq("journal_entries.is_posted", true)
      .is("journal_entries.deleted_at", null)
      .lte("journal_entries.entry_date", end);

    const map: Record<string, AccountBalance> = {};
    let revNet = 0, expNet = 0;

    for (const row of (data ?? []) as unknown as Array<{
      debit_paise: number; credit_paise: number;
      chart_of_accounts: { id: string; account_code: string; account_name: string; account_type: string; account_subtype: string | null };
    }>) {
      const acc = row.chart_of_accounts;
      if (acc.account_type === "Revenue") { revNet += row.credit_paise - row.debit_paise; continue; }
      if (acc.account_type === "Expense") { expNet += row.debit_paise - row.credit_paise; continue; }

      if (!map[acc.id]) map[acc.id] = { account_id: acc.id, account_code: acc.account_code, account_name: acc.account_name, account_type: acc.account_type, account_subtype: acc.account_subtype, net_paise: 0 };
      // Normal balance: Asset = Dr, Liability = Cr, Equity = Cr
      if (acc.account_type === "Asset") map[acc.id].net_paise += row.debit_paise - row.credit_paise;
      else map[acc.id].net_paise += row.credit_paise - row.debit_paise;
    }

    const bs = Object.values(map).filter((b) => b.net_paise !== 0).sort((a, b) => a.account_code.localeCompare(b.account_code));
    // Inject current year retained earnings
    if (revNet !== 0 || expNet !== 0) {
      bs.push({ account_id: "__retained__", account_code: "", account_name: `Current Year P&L (FY ${financialYear})`, account_type: "Equity", account_subtype: "Reserves & Surplus", net_paise: revNet - expNet });
    }
    setBalances(bs);
    setLoading(false); setLoaded(true);
  }, [clientId, financialYear]);

  useEffect(() => { load(); }, [load]);

  const assets = balances.filter((b) => b.account_type === "Asset" && b.net_paise > 0);
  const liabilities = balances.filter((b) => b.account_type === "Liability" && b.net_paise > 0);
  const equity = balances.filter((b) => b.account_type === "Equity");

  const totalAssets = assets.reduce((s, b) => s + b.net_paise, 0);
  const totalLiab = liabilities.reduce((s, b) => s + b.net_paise, 0);
  const totalEquity = equity.reduce((s, b) => s + b.net_paise, 0);
  const isBalanced = totalAssets === totalLiab + totalEquity;

  const assetBuckets = groupBy(assets, (b) => bsBucket(b.account_type, b.account_subtype));
  const liabBuckets = groupBy(liabilities, (b) => bsBucket(b.account_type, b.account_subtype));
  const equityBuckets = groupBy(equity, (b) => bsBucket(b.account_type, b.account_subtype));

  const BS_ASSET_ORDER = ["Tangible Assets", "Intangible Assets", "Non-Current Investments", "Inventories", "Trade Receivables", "Short-term Loans & Advances", "Cash & Cash Equivalents", "Other Current Assets"];
  const BS_LIAB_ORDER = ["Long-term Borrowings", "Short-term Borrowings", "Trade Payables", "Tax Liabilities", "Other Current Liabilities"];
  const BS_EQ_ORDER = ["Share Capital", "Reserves & Surplus"];

  return (
    <div className="space-y-4 max-w-2xl">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-white/65">Balance Sheet — as at 31 March {parseInt(financialYear.split("-")[0]) + 1}</p>
        <div className="flex gap-2">
          <button onClick={load} className="p-1.5 rounded border border-white/[0.07] hover:bg-[#0e1017] text-white/40"><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
          <button onClick={() => window.print()} className="p-1.5 rounded border border-white/[0.07] hover:bg-[#0e1017] text-white/40" title="Print"><Printer size={13} /></button>
        </div>
      </div>

      {loading && <div className="h-48 rounded-lg bg-[#0e1017] animate-pulse" />}
      {!loading && loaded && (
        <div className="space-y-4">
          {/* Equity & Liabilities side */}
          <div className="bg-[#131620] rounded-xl border border-white/[0.05] overflow-hidden">
            <div className="px-5 py-3 bg-[#0e1017] border-b border-white/[0.05]">
              <p className="text-xs font-bold text-white/55 uppercase tracking-wide">I. Equity & Liabilities</p>
            </div>
            <table className="w-full text-xs">
              <thead><tr className="border-b border-white/[0.05] text-white/30 text-[10px]"><th className="px-5 py-2 text-left font-semibold">Particulars</th><th className="px-4 py-2 text-right font-semibold">Amount (₹)</th></tr></thead>
              <tbody>
                <tr><td colSpan={2} className="px-5 py-2 font-semibold text-white/65 bg-[#0e1017] text-[10px] uppercase tracking-wide">(A) Equity</td></tr>
                {BS_EQ_ORDER.map((bucket) => { const items = equityBuckets[bucket] ?? []; if (!items.length) return null; return <BSSectionRows key={bucket} label={bucket} items={items} />; })}
                {equityBuckets["Capital Account"] && <BSSectionRows label="Capital Account" items={equityBuckets["Capital Account"]} />}
                <tr className="border-t border-white/[0.07] font-semibold"><td className="px-5 py-2.5 text-white/75">Total Equity</td><td className="px-4 py-2.5 text-right font-mono text-white/85">{fmt(totalEquity)}</td></tr>

                <tr><td colSpan={2} className="px-5 py-2 font-semibold text-white/65 bg-[#0e1017] text-[10px] uppercase tracking-wide">(B) Liabilities</td></tr>
                {BS_LIAB_ORDER.map((bucket) => { const items = liabBuckets[bucket] ?? []; if (!items.length) return null; return <BSSectionRows key={bucket} label={bucket} items={items} />; })}
                <tr className="border-t border-white/[0.07] font-semibold"><td className="px-5 py-2.5 text-white/75">Total Liabilities</td><td className="px-4 py-2.5 text-right font-mono text-white/85">{fmt(totalLiab)}</td></tr>

                <tr className="border-t-2 border-gray-300 font-bold bg-[#0e1017]"><td className="px-5 py-3 text-white/85 text-sm">Total Equity & Liabilities</td><td className="px-4 py-3 text-right font-mono text-white/85 text-sm">{fmt(totalLiab + totalEquity)}</td></tr>
              </tbody>
            </table>
          </div>

          {/* Assets side */}
          <div className="bg-[#131620] rounded-xl border border-white/[0.05] overflow-hidden">
            <div className="px-5 py-3 bg-[#0e1017] border-b border-white/[0.05]">
              <p className="text-xs font-bold text-white/55 uppercase tracking-wide">II. Assets</p>
            </div>
            <table className="w-full text-xs">
              <thead><tr className="border-b border-white/[0.05] text-white/30 text-[10px]"><th className="px-5 py-2 text-left font-semibold">Particulars</th><th className="px-4 py-2 text-right font-semibold">Amount (₹)</th></tr></thead>
              <tbody>
                {BS_ASSET_ORDER.map((bucket) => { const items = assetBuckets[bucket] ?? []; if (!items.length) return null; return <BSSectionRows key={bucket} label={bucket} items={items} />; })}
                <tr className="border-t-2 border-gray-300 font-bold bg-[#0e1017]"><td className="px-5 py-3 text-white/85 text-sm">Total Assets</td><td className="px-4 py-3 text-right font-mono text-white/85 text-sm">{fmt(totalAssets)}</td></tr>
              </tbody>
            </table>
          </div>

          {/* Balance check */}
          <div className={`rounded-lg px-4 py-3 text-xs font-medium ${isBalanced ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
            {isBalanced
              ? "✓ Balance Sheet balances — Assets = Equity + Liabilities"
              : `✗ Out of balance by ${fmt(Math.abs(totalAssets - totalLiab - totalEquity))} — check for unposted entries`}
          </div>
          {balances.length === 0 && <div className="text-center py-8 text-white/30 text-sm">No posted journal entries found for this client.</div>}
        </div>
      )}
    </div>
  );
}

function BSSectionRows({ label, items }: { label: string; items: AccountBalance[] }) {
  const [open, setOpen] = useState(true);
  const total = items.reduce((s, b) => s + b.net_paise, 0);
  return (
    <>
      <tr className="cursor-pointer hover:bg-[#0e1017]" onClick={() => setOpen((o) => !o)}>
        <td className="px-5 py-2 text-white/65 font-medium pl-8">{label}</td>
        <td className="px-4 py-2 text-right font-mono text-white/65">{fmt(total)}</td>
      </tr>
      {open && items.map((item) => (
        <tr key={item.account_id} className="text-white/30">
          <td className="px-5 py-1.5 pl-14">{item.account_name}</td>
          <td className="px-4 py-1.5 text-right font-mono">{fmt(item.net_paise)}</td>
        </tr>
      ))}
    </>
  );
}

// ── Bank Accounts & Statement Import ──────────────────────────────────────

function BankAccounts({ clientId, financialYear }: { clientId: string; financialYear: string }) {
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
    <div className="space-y-4 max-w-4xl">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-white/65">{statements.length} bank statement{statements.length !== 1 ? "s" : ""} imported</p>
        <div className="flex gap-2">
          <button onClick={loadStatements} className="p-1.5 rounded border border-white/[0.07] hover:bg-[#0e1017] text-white/40"><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
          <button onClick={() => setShowImport(true)} className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
            <Upload size={12} /> Import Statement
          </button>
        </div>
      </div>

      {loading ? (
        <div className="space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-14 rounded-lg bg-[#0e1017] animate-pulse" />)}</div>
      ) : statements.length === 0 ? (
        <div className="bg-[#131620] rounded-xl border border-white/[0.05] text-center py-16 space-y-3">
          <FileText size={32} className="text-gray-200 mx-auto" />
          <p className="text-sm text-white/40">No bank statements imported yet</p>
          <button onClick={() => setShowImport(true)} className="text-xs text-blue-600 hover:underline">Import your first statement</button>
        </div>
      ) : (
        <div className="bg-[#131620] rounded-xl border border-white/[0.05] overflow-hidden">
          <table className="w-full text-xs">
            <thead><tr className="border-b border-white/[0.05] text-white/30"><th className="px-4 py-3 text-left font-semibold">Bank</th><th className="px-3 py-3 text-left font-semibold">Account No.</th><th className="px-3 py-3 text-left font-semibold">Period</th><th className="px-3 py-3 text-right font-semibold">Credits</th><th className="px-3 py-3 text-right font-semibold">Debits</th><th className="px-3 py-3 text-left font-semibold">Status</th><th className="px-4 py-3 text-left font-semibold">Action</th></tr></thead>
            <tbody className="divide-y divide-white/[0.03]">
              {statements.map((s) => (
                <tr key={s.id} className="hover:bg-[#0e1017]">
                  <td className="px-4 py-2.5 font-medium text-white/75">{s.bank_name}</td>
                  <td className="px-3 py-2.5 font-mono text-white/40 text-[10px]">{s.account_number ?? "—"}</td>
                  <td className="px-3 py-2.5 text-white/40">{s.statement_from} → {s.statement_to}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-green-700">{fmt(s.total_credits_paise)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-red-700">{fmt(s.total_debits_paise)}</td>
                  <td className="px-3 py-2.5">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${STATUS_COLORS[s.import_status] ?? "bg-white/[0.06] text-white/40"}`}>{s.import_status}</span>
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
        <div className="bg-[#131620] rounded-xl border border-white/[0.05] overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-50 flex items-center justify-between">
            <p className="text-xs font-semibold text-white/65">Transactions</p>
            {txnsLoading && <RefreshCw size={13} className="animate-spin text-white/30" />}
          </div>
          {!txnsLoading && stmtTxns.length > 0 && (
            <div className="overflow-x-auto max-h-72 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-[#131620]"><tr className="border-b border-white/[0.05] text-white/30"><th className="px-4 py-2 text-left font-semibold">Date</th><th className="px-3 py-2 text-left font-semibold">Description</th><th className="px-3 py-2 text-right font-semibold">Debit</th><th className="px-3 py-2 text-right font-semibold">Credit</th><th className="px-3 py-2 text-left font-semibold">Status</th></tr></thead>
                <tbody className="divide-y divide-white/[0.03]">
                  {stmtTxns.map((t) => (
                    <tr key={t.id} className="hover:bg-[#0e1017]">
                      <td className="px-4 py-2 text-white/40 whitespace-nowrap">{t.transaction_date}</td>
                      <td className="px-3 py-2 text-white/65 max-w-xs truncate">{t.description}</td>
                      <td className="px-3 py-2 text-right font-mono text-red-700">{t.debit_paise > 0 ? fmt(t.debit_paise) : "—"}</td>
                      <td className="px-3 py-2 text-right font-mono text-green-700">{t.credit_paise > 0 ? fmt(t.credit_paise) : "—"}</td>
                      <td className="px-3 py-2">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${t.match_status === "posted" ? "bg-green-100 text-green-700" : t.match_status === "matched" ? "bg-blue-100 text-blue-700" : t.match_status === "ignored" ? "bg-white/[0.06] text-white/30" : "bg-amber-100 text-amber-700"}`}>{t.match_status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!txnsLoading && stmtTxns.length === 0 && <div className="text-center py-8 text-white/30 text-sm">No transactions found.</div>}
        </div>
      )}

      {showImport && (
        <BankImportModal clientId={clientId} financialYear={financialYear} onClose={() => setShowImport(false)} onImported={() => { setShowImport(false); loadStatements(); }} />
      )}
    </div>
  );
}

// ── Bank Import Modal ──────────────────────────────────────────────────────

function BankImportModal({ clientId, financialYear, onClose, onImported }: { clientId: string; financialYear: string; onClose: () => void; onImported: () => void }) {
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
      const stmt = await importBankStatement(clientId, bankName.trim(), accountNumber.trim(), parsed);
      try {
        const firmId = await getFirmId();
        await writeTimelineEvent({ client_id: clientId, firm_id: firmId, financial_year: financialYear, category: "accounting", event_type: "bank_statement_imported", severity: "info", title: `Bank statement imported — ${bankName}`, description: `${parsed.length} transactions from ${stmt.statement_from} to ${stmt.statement_to}`, entity_type: "bank_statement", entity_id: stmt.id, actor_type: "user" });
      } catch { /* non-blocking */ }
      onImported();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-[#131620] rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white/85">Import Bank Statement</h3>
          <button onClick={onClose} className="text-white/30 hover:text-white/55"><X size={16} /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-white/55 mb-1">Bank Name *</label>
            <select value={bankName} onChange={(e) => setBankName(e.target.value)} className="w-full px-3 py-2 text-sm border border-white/[0.07] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
              {["HDFC Bank","SBI","ICICI Bank","Axis Bank","Kotak Mahindra Bank","IndusInd Bank","Yes Bank","IDFC First Bank","Other"].map((b) => <option key={b}>{b}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-white/55 mb-1">Account Number</label>
            <input value={accountNumber} onChange={(e) => setAccountNumber(e.target.value)} placeholder="XXXX XXXX XXXX" className="w-full px-3 py-2 text-sm border border-white/[0.07] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-xs font-medium text-white/55 mb-1">CSV File *</label>
            <input ref={fileRef} type="file" accept=".csv,.txt" onChange={handleFile} className="hidden" />
            <button onClick={() => fileRef.current?.click()} className="w-full border-2 border-dashed border-white/[0.07] rounded-lg py-4 text-sm text-white/40 hover:border-blue-300 hover:text-blue-600 transition-colors flex items-center justify-center gap-2">
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
          <button onClick={onClose} className="text-xs px-4 py-2 border border-white/[0.07] rounded-lg hover:bg-[#0e1017]">Cancel</button>
          <button onClick={handleImport} disabled={importing || !parsed} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
            {importing ? "Importing…" : "Import"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Bank Reconciliation ────────────────────────────────────────────────────

function BankReconciliation({ accounts, clientId, financialYear }: { accounts: Account[]; clientId: string; financialYear: string }) {
  const [statements, setStatements] = useState<BankStatement[]>([]);
  const [selectedStmtId, setSelectedStmtId] = useState<string>("");
  const [txns, setTxns] = useState<BankTransaction[]>([]);
  const [loadingStmts, setLoadingStmts] = useState(true);
  const [loadingTxns, setLoadingTxns] = useState(false);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [posting, setPosting] = useState<Record<string, boolean>>({});
  const [posted, setPosted] = useState<Record<string, boolean>>({});
  const [ignored, setIgnored] = useState<Record<string, boolean>>({});

  // Bank accounts only for the contra-account side
  const bankAccounts = accounts.filter((a) => {
    const s = (a.account_subtype ?? "").toLowerCase();
    return a.account_type === "Asset" && (s.includes("bank") || s.includes("cash"));
  });

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    getBankStatements(clientId).then(setStatements).catch(() => setStatements([])).finally(() => setLoadingStmts(false));
  }, [clientId]);

  async function loadTxns(stmtId: string) {
    setSelectedStmtId(stmtId); setLoadingTxns(true);
    try {
      const all = await getBankTransactions(stmtId);
      setTxns(all.filter((t) => t.match_status === "unmatched"));
      setPosted({}); setIgnored({}); setMapping({});
    } catch { setTxns([]); }
    setLoadingTxns(false);
  }

  async function postTxn(txn: BankTransaction) {
    const accountId = mapping[txn.id];
    const bankAccId = bankAccounts[0]?.id;
    if (!accountId) return;
    if (!bankAccId) { alert("No cash/bank account found in Chart of Accounts. Add one first."); return; }
    setPosting((p) => ({ ...p, [txn.id]: true }));
    try {
      await postBankTransaction(txn.id, accountId, bankAccId, clientId);
      try {
        const firmId = await getFirmId();
        await writeTimelineEvent({ client_id: clientId, firm_id: firmId, financial_year: financialYear, category: "accounting", event_type: "bank_transaction_posted", severity: "info", title: "Bank transaction posted to ledger", description: txn.description, actor_type: "user" });
      } catch { /* non-blocking */ }
      setPosted((p) => ({ ...p, [txn.id]: true }));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to post");
    } finally {
      setPosting((p) => ({ ...p, [txn.id]: false }));
    }
  }

  async function ignoreTxn(txnId: string) {
    const supabase = getSupabaseClient();
    await supabase.from("bank_transactions").update({ match_status: "ignored" }).eq("id", txnId);
    setIgnored((p) => ({ ...p, [txnId]: true }));
  }

  const unprocessed = txns.filter((t) => !posted[t.id] && !ignored[t.id]);
  const processedCount = Object.keys(posted).length + Object.keys(ignored).length;
  const total = txns.length;

  return (
    <div className="space-y-4 max-w-4xl">
      {/* Statement selector */}
      <div className="bg-[#131620] rounded-xl border border-white/[0.05] p-4">
        <label className="block text-xs font-medium text-white/55 mb-1.5">Select Bank Statement to Reconcile</label>
        {loadingStmts ? <div className="h-8 bg-[#0e1017] rounded animate-pulse" /> : (
          <select value={selectedStmtId} onChange={(e) => e.target.value && loadTxns(e.target.value)} className="w-full max-w-sm px-3 py-2 text-sm border border-white/[0.07] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">— Choose statement —</option>
            {statements.map((s) => <option key={s.id} value={s.id}>{s.bank_name} {s.account_number ? `(${s.account_number})` : ""} · {s.statement_from} → {s.statement_to} · {s.row_count} txns</option>)}
          </select>
        )}
      </div>

      {selectedStmtId && (
        <>
          {/* Progress bar */}
          {total > 0 && (
            <div className="bg-[#131620] rounded-xl border border-white/[0.05] p-4 space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-white/65">Reconciliation Progress</span>
                <span className="text-white/40">{processedCount}/{total} processed</span>
              </div>
              <div className="h-2 rounded-full bg-white/[0.06] overflow-hidden">
                <div className="h-full rounded-full bg-blue-500 transition-all" style={{ width: `${total > 0 ? (processedCount/total)*100 : 0}%` }} />
              </div>
              {processedCount === total && total > 0 && (
                <div className="flex items-center gap-1.5 text-xs text-green-700 font-medium">
                  <CheckCircle size={12} /> All transactions processed
                </div>
              )}
            </div>
          )}

          {loadingTxns ? <div className="h-40 bg-[#0e1017] rounded-lg animate-pulse" /> : unprocessed.length > 0 ? (
            <div className="bg-[#131620] rounded-xl border border-white/[0.05] overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-50">
                <p className="text-xs font-semibold text-white/65">{unprocessed.length} unmatched transaction{unprocessed.length !== 1 ? "s" : ""}</p>
              </div>
              <div className="divide-y divide-white/[0.03]">
                {unprocessed.map((txn) => (
                  <div key={txn.id} className="px-4 py-3 space-y-2">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-white/75 truncate">{txn.description}</p>
                        <p className="text-[10px] text-white/30 mt-0.5">{txn.transaction_date} · {txn.reference_no ?? ""}</p>
                      </div>
                      <div className="shrink-0 text-right">
                        {txn.debit_paise > 0 && <p className="text-xs font-mono text-red-700">{fmt(txn.debit_paise)} Dr</p>}
                        {txn.credit_paise > 0 && <p className="text-xs font-mono text-green-700">{fmt(txn.credit_paise)} Cr</p>}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <select value={mapping[txn.id] ?? ""} onChange={(e) => setMapping((m) => ({ ...m, [txn.id]: e.target.value }))} className="flex-1 px-2 py-1 text-xs border border-white/[0.07] rounded focus:outline-none focus:ring-1 focus:ring-blue-500">
                        <option value="">— Map to account —</option>
                        {["Asset","Liability","Equity","Revenue","Expense"].map((type) => (
                          <optgroup key={type} label={type}>
                            {accounts.filter((a) => a.account_type === type).map((a) => <option key={a.id} value={a.id}>{a.account_code} — {a.account_name}</option>)}
                          </optgroup>
                        ))}
                      </select>
                      <button onClick={() => postTxn(txn)} disabled={!mapping[txn.id] || posting[txn.id]} className="text-xs px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-40 whitespace-nowrap">
                        {posting[txn.id] ? "Posting…" : "Post"}
                      </button>
                      <button onClick={() => ignoreTxn(txn.id)} className="text-xs px-3 py-1 border border-white/[0.07] rounded hover:bg-[#0e1017] text-white/40 whitespace-nowrap">Ignore</button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : !loadingTxns && selectedStmtId ? (
            <div className="bg-green-50 border border-green-100 rounded-xl px-4 py-6 text-center">
              <CheckCircle size={24} className="text-green-500 mx-auto mb-2" />
              <p className="text-sm text-green-700 font-medium">All transactions reconciled</p>
              <p className="text-xs text-green-600 mt-0.5">No unmatched transactions remain for this statement.</p>
            </div>
          ) : null}
        </>
      )}

      {!selectedStmtId && !loadingStmts && statements.length === 0 && (
        <div className="text-center py-12 text-white/30 text-sm">No bank statements imported. Import a statement first from the Banks tab.</div>
      )}
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
    <div className="bg-[#131620] rounded-xl border border-white/[0.05] overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-50">
        <p className="text-xs font-semibold text-white/65">Year-End Close — FY {financialYear}</p>
        <p className="text-[10px] text-white/30 mt-0.5">
          Lock the financial year to prevent new journal entries. Locked years remain viewable.
        </p>
      </div>
      <div className="px-5 py-4 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className={`w-3 h-3 rounded-full ${loading ? "bg-white/[0.08]" : locked ? "bg-red-400" : "bg-green-400"}`} />
          <span className="text-sm text-white/65">
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

  async function exportXLSX(reportType: "pl" | "bs" | "trial") {
    setExporting(reportType);
    try {
      const XLSX = (await import("xlsx")).default;
      const supabase = getSupabaseClient();
      const { start, end } = fyDateRange(financialYear);

      if (reportType === "trial") {
        const { data: lines } = await supabase
          .from("journal_lines")
          .select("debit_paise, credit_paise, chart_of_accounts!inner(account_code, account_name, account_type), journal_entries!inner(entry_date, is_posted, client_id, deleted_at)")
          .eq("journal_entries.client_id", clientId)
          .eq("journal_entries.is_posted", true)
          .is("journal_entries.deleted_at", null)
          .gte("journal_entries.entry_date", start)
          .lte("journal_entries.entry_date", end);

        const map: Record<string, { code: string; name: string; type: string; debit: number; credit: number }> = {};
        for (const row of (lines ?? []) as unknown as Array<{
          debit_paise: number; credit_paise: number;
          chart_of_accounts: { account_code: string; account_name: string; account_type: string };
        }>) {
          const acc = row.chart_of_accounts;
          const key = acc.account_code;
          if (!map[key]) map[key] = { code: acc.account_code, name: acc.account_name, type: acc.account_type, debit: 0, credit: 0 };
          map[key].debit += row.debit_paise;
          map[key].credit += row.credit_paise;
        }
        const rows = Object.values(map).sort((a, b) => a.code.localeCompare(b.code));
        const ws = XLSX.utils.json_to_sheet([
          { "Account Code": "", "Account Name": "", "Type": "", "Debit (₹)": "", "Credit (₹)": "" },
          ...rows.map((r) => ({
            "Account Code": r.code,
            "Account Name": r.name,
            "Type": r.type,
            "Debit (₹)": (r.debit / 100).toFixed(2),
            "Credit (₹)": (r.credit / 100).toFixed(2),
          })),
          {
            "Account Code": "TOTAL",
            "Account Name": "",
            "Type": "",
            "Debit (₹)": (rows.reduce((s, r) => s + r.debit, 0) / 100).toFixed(2),
            "Credit (₹)": (rows.reduce((s, r) => s + r.credit, 0) / 100).toFixed(2),
          },
        ], { skipHeader: true });
        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, `Trial Balance FY${financialYear}`);
        XLSX.writeFile(wb, `Trial-Balance-FY${financialYear}.xlsx`);

      } else {
        // P&L or Balance Sheet
        const accountTypes = reportType === "pl" ? ["Revenue", "Expense"] : ["Asset", "Liability", "Equity"];
        const { data: lines } = await supabase
          .from("journal_lines")
          .select("debit_paise, credit_paise, chart_of_accounts!inner(id, account_code, account_name, account_type, account_subtype), journal_entries!inner(entry_date, is_posted, client_id, deleted_at)")
          .eq("journal_entries.client_id", clientId)
          .eq("journal_entries.is_posted", true)
          .is("journal_entries.deleted_at", null)
          .gte("journal_entries.entry_date", start)
          .lte("journal_entries.entry_date", end)
          .in("chart_of_accounts.account_type", accountTypes);

        const map: Record<string, { code: string; name: string; type: string; subtype: string | null; net: number }> = {};
        for (const row of (lines ?? []) as unknown as Array<{
          debit_paise: number; credit_paise: number;
          chart_of_accounts: { id: string; account_code: string; account_name: string; account_type: string; account_subtype: string | null };
        }>) {
          const acc = row.chart_of_accounts;
          if (!map[acc.id]) map[acc.id] = { code: acc.account_code, name: acc.account_name, type: acc.account_type, subtype: acc.account_subtype, net: 0 };
          if (acc.account_type === "Revenue" || acc.account_type === "Asset")
            map[acc.id].net += row.credit_paise - row.debit_paise;
          else
            map[acc.id].net += row.debit_paise - row.credit_paise;
        }
        const rows = Object.values(map).filter((r) => r.net !== 0).sort((a, b) => a.code.localeCompare(b.code));
        const bucketFn = reportType === "pl" ? plBucket : bsBucket;
        const sheetRows = rows.map((r) => ({
          "Schedule III Category": bucketFn(r.type, r.subtype),
          "Account Code": r.code,
          "Account Name": r.name,
          "Type": r.type,
          "Amount (₹)": (r.net / 100).toFixed(2),
        }));
        const ws = XLSX.utils.json_to_sheet(sheetRows);
        const wb = XLSX.utils.book_new();
        const sheetName = reportType === "pl" ? `P&L FY${financialYear}` : `Balance Sheet FY${financialYear}`;
        XLSX.utils.book_append_sheet(wb, ws, sheetName);
        const fileName = reportType === "pl" ? `PL-FY${financialYear}.xlsx` : `BalanceSheet-FY${financialYear}.xlsx`;
        XLSX.writeFile(wb, fileName);
      }
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
      const { start, end } = fyDateRange(financialYear);
      const labelMap = { pl: "Profit & Loss", bs: "Balance Sheet", trial: "Trial Balance" };
      const label = `${labelMap[reportType]} — FY ${financialYear}`;
      const fileName = `${reportType}-FY${financialYear}-${Date.now()}.xlsx`;

      // Generate XLSX in memory and upload to Supabase Storage
      const accountTypes =
        reportType === "pl" ? ["Revenue", "Expense"] :
        reportType === "bs" ? ["Asset", "Liability", "Equity"] :
        ["Revenue", "Expense", "Asset", "Liability", "Equity"];

      const { data: lines } = await supabase
        .from("journal_lines")
        .select("debit_paise, credit_paise, chart_of_accounts!inner(id, account_code, account_name, account_type, account_subtype), journal_entries!inner(entry_date, is_posted, client_id, deleted_at)")
        .eq("journal_entries.client_id", clientId)
        .eq("journal_entries.is_posted", true)
        .is("journal_entries.deleted_at", null)
        .gte("journal_entries.entry_date", start)
        .lte("journal_entries.entry_date", end)
        .in("chart_of_accounts.account_type", accountTypes);

      const map: Record<string, { code: string; name: string; type: string; subtype: string | null; debit: number; credit: number }> = {};
      for (const row of (lines ?? []) as unknown as Array<{
        debit_paise: number; credit_paise: number;
        chart_of_accounts: { id: string; account_code: string; account_name: string; account_type: string; account_subtype: string | null };
      }>) {
        const acc = row.chart_of_accounts;
        if (!map[acc.id]) map[acc.id] = { code: acc.account_code, name: acc.account_name, type: acc.account_type, subtype: acc.account_subtype, debit: 0, credit: 0 };
        map[acc.id].debit += row.debit_paise;
        map[acc.id].credit += row.credit_paise;
      }

      const rows = Object.values(map).sort((a, b) => a.code.localeCompare(b.code));
      const sheetRows = rows.map((r) => ({
        "Account Code": r.code,
        "Account Name": r.name,
        "Type": r.type,
        "Debit (₹)": (r.debit / 100).toFixed(2),
        "Credit (₹)": (r.credit / 100).toFixed(2),
      }));

      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(sheetRows), label.slice(0, 31));
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
    <div className="space-y-5 max-w-3xl">
      {/* Generate / export reports */}
      <div className="bg-[#131620] rounded-xl border border-white/[0.05] overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <p className="text-xs font-semibold text-white/65">Generate Reports — FY {financialYear}</p>
          <p className="text-[10px] text-white/30 mt-0.5">Export to XLSX or share directly to the client portal.</p>
        </div>
        <div className="divide-y divide-white/[0.03]">
          {REPORT_LINKS.map((r) => (
            <div key={r.id} className="px-5 py-4 flex items-center gap-4">
              <span className="text-2xl">{r.icon}</span>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white/75">{r.label}</p>
                <p className="text-[10px] text-white/30 mt-0.5">{r.description}</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => window.print()}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 border border-white/[0.07] rounded-lg hover:bg-[#0e1017] text-white/55"
                  title="Print as PDF"
                >
                  <Printer size={12} />
                </button>
                <button
                  onClick={() => exportXLSX(r.id)}
                  disabled={exporting === r.id}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 border border-white/[0.07] rounded-lg hover:bg-[#0e1017] text-white/55 disabled:opacity-50"
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
      <div className="bg-[#131620] rounded-xl border border-white/[0.05] overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <p className="text-xs font-semibold text-white/65">Shared Reports</p>
          <p className="text-[10px] text-white/30 mt-0.5">Reports previously shared with this client via portal.</p>
        </div>
        {loadingShared ? (
          <div className="px-5 py-6"><div className="h-12 bg-[#0e1017] rounded animate-pulse" /></div>
        ) : sharedReports.length === 0 ? (
          <div className="text-center py-8 text-white/30 text-sm">No reports shared yet.</div>
        ) : (
          <table className="w-full text-xs">
            <thead><tr className="border-b border-white/[0.05] text-white/30"><th className="px-5 py-2 text-left font-semibold">Report</th><th className="px-3 py-2 text-left font-semibold">FY</th><th className="px-3 py-2 text-left font-semibold">File</th><th className="px-4 py-2 text-left font-semibold">Shared On</th><th className="px-3 py-2"></th></tr></thead>
            <tbody className="divide-y divide-white/[0.03]">
              {sharedReports.map((r) => (
                <tr key={r.id} className="hover:bg-[#0e1017]">
                  <td className="px-5 py-2.5 font-medium text-white/75">{r.report_label}</td>
                  <td className="px-3 py-2.5 text-white/40">FY {r.financial_year}</td>
                  <td className="px-3 py-2.5 text-white/40 font-mono text-[10px] truncate max-w-[130px]">{r.file_name}</td>
                  <td className="px-4 py-2.5 text-white/30">{new Date(r.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</td>
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
