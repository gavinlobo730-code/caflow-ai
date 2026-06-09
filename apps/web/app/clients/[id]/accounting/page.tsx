"use client";

import { useEffect, useState, useCallback } from "react";
import { Plus, RefreshCw } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { writeTimelineEvent } from "@/lib/services/timeline";

type AccountingTab = "coa" | "journal" | "ledger" | "trial";

// ── Types ──────────────────────────────────────────────────────────────────

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

// ── Helpers ────────────────────────────────────────────────────────────────

function paiseToCurrency(paise: number): string {
  if (paise === 0) return "—";
  const rupees = Math.abs(paise) / 100;
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rupees);
}

function fyDateRange(fy: string): { start: string; end: string } {
  const [startYear] = fy.split("-");
  const y = parseInt(startYear, 10);
  return { start: `${y}-04-01`, end: `${y + 1}-03-31` };
}

// ── Tabs ───────────────────────────────────────────────────────────────────

const TABS: { id: AccountingTab; label: string }[] = [
  { id: "coa", label: "Chart of Accounts" },
  { id: "journal", label: "Journal Entry" },
  { id: "ledger", label: "General Ledger" },
  { id: "trial", label: "Trial Balance" },
];

// ── Main Page ──────────────────────────────────────────────────────────────

export default function AccountingPage() {
  const { clientId, financialYear } = useClientNav();
  const [tab, setTab] = useState<AccountingTab>("coa");
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
      <div className="flex gap-0.5 bg-gray-50 rounded-lg p-1 w-fit mx-6 mt-5 shrink-0">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              tab === t.id ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto px-6 pb-6 pt-4 min-h-0">
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
      </div>
    </div>
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
    Asset: "text-blue-600 bg-blue-50",
    Liability: "text-orange-600 bg-orange-50",
    Equity: "text-purple-600 bg-purple-50",
    Revenue: "text-green-600 bg-green-50",
    Expense: "text-red-600 bg-red-50",
  };

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500">{accounts.length} accounts</p>
        <button onClick={onRefresh} className="p-1.5 rounded border border-gray-200 hover:bg-gray-50 text-gray-500">
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {loading ? (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => <div key={i} className="h-24 rounded-lg bg-gray-50 animate-pulse" />)}
        </div>
      ) : (
        TYPE_ORDER.map((type) =>
          grouped[type].length > 0 ? (
            <div key={type} className="bg-white rounded-xl border border-gray-100 overflow-hidden">
              <div className="px-4 py-2.5 border-b border-gray-50 flex items-center gap-2">
                <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${TYPE_COLORS[type]}`}>{type}</span>
                <span className="text-xs text-gray-400">{grouped[type].length} accounts</span>
              </div>
              <table className="w-full text-xs">
                <tbody className="divide-y divide-gray-50">
                  {grouped[type].map((a) => (
                    <tr key={a.id} className="hover:bg-gray-50">
                      <td className="px-4 py-2 font-mono text-gray-500 w-20">{a.account_code}</td>
                      <td className="px-3 py-2 font-medium text-gray-800">{a.account_name}</td>
                      <td className="px-3 py-2 text-gray-400">{a.account_subtype ?? ""}</td>
                      <td className="px-4 py-2 text-right">
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-50 text-gray-400">
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
        <div className="text-center py-12 text-gray-400 text-sm">
          No accounts found for this client. Accounts are seeded from the firm-level chart of accounts.
        </div>
      )}
    </div>
  );
}

// ── Journal Entry Form ─────────────────────────────────────────────────────

const ENTRY_TYPES = ["Journal", "Sales", "Purchase", "Payment", "Receipt", "Contra", "Opening"] as const;

function JournalEntryForm({
  accounts, clientId, financialYear, onPosted,
}: {
  accounts: Account[];
  clientId: string;
  financialYear: string;
  onPosted: () => void;
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

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    const supabase = getSupabaseClient();
    supabase
      .from("journal_entries")
      .select("id, entry_date, reference_no, narration, entry_type, is_posted, journal_lines(account_id, debit_paise, credit_paise, narration)")
      .eq("client_id", clientId)
      .is("deleted_at", null)
      .order("entry_date", { ascending: false })
      .limit(5)
      .then(({ data }) => setRecentEntries((data as unknown as JournalEntry[]) ?? []));
  }, [clientId, success]);

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
    if (validLines.length < 2) { setError("At least 2 lines required."); return; }

    setSaving(true);
    setError(null);
    try {
      const supabase = getSupabaseClient();
      const firmId = await getFirmId();
      const { data: entry, error: entryErr } = await supabase
        .from("journal_entries")
        .insert({
          firm_id: firmId,
          client_id: clientId,
          entry_date: entryDate,
          reference_no: referenceNo.trim() || null,
          narration: narration.trim(),
          entry_type: entryType,
          is_posted: post,
          posted_at: post ? new Date().toISOString() : null,
        })
        .select("id")
        .single();
      if (entryErr || !entry) throw new Error(entryErr?.message ?? "Failed to create entry");

      const { error: linesErr } = await supabase.from("journal_lines").insert(
        validLines.map((l) => ({
          journal_entry_id: entry.id,
          account_id: l.account_id,
          debit_paise: l.debit_paise,
          credit_paise: l.credit_paise,
          narration: l.narration.trim() || null,
        }))
      );
      if (linesErr) throw new Error(linesErr.message);

      // Emit timeline event
      try {
        await writeTimelineEvent({
          client_id: clientId,
          firm_id: firmId,
          financial_year: financialYear,
          category: "accounting",
          event_type: post ? "journal_entry_posted" : "journal_entry_saved",
          severity: "info",
          title: post ? "Journal entry posted" : "Journal entry saved (draft)",
          description: narration.trim(),
          entity_type: "journal_entry",
          entity_id: entry.id,
          actor_type: "user",
        });
      } catch { /* non-blocking */ }

      setSuccess(true);
      setNarration("");
      setReferenceNo("");
      setLines([
        { account_id: "", debit_paise: 0, credit_paise: 0, narration: "" },
        { account_id: "", debit_paise: 0, credit_paise: 0, narration: "" },
      ]);
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
      {success && (
        <div className="bg-green-50 border border-green-100 rounded-lg px-4 py-3 text-sm text-green-700 font-medium">
          Journal entry saved successfully.
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-100 p-5 space-y-4">
        <h3 className="text-sm font-semibold text-gray-900">New Journal Entry</h3>

        {/* Header fields */}
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Date *</label>
            <input
              type="date"
              value={entryDate}
              onChange={(e) => setEntryDate(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
            <select
              value={entryType}
              onChange={(e) => setEntryType(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {ENTRY_TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Reference No.</label>
            <input
              value={referenceNo}
              onChange={(e) => setReferenceNo(e.target.value)}
              placeholder="INV-001"
              className="w-full px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Narration *</label>
          <input
            value={narration}
            onChange={(e) => setNarration(e.target.value)}
            placeholder="Being goods sold to ABC Ltd..."
            className="w-full px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {/* Journal lines */}
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-100 text-gray-400">
                <th className="pb-2 text-left font-semibold">Account</th>
                <th className="pb-2 text-right font-semibold w-28">Debit (₹)</th>
                <th className="pb-2 text-right font-semibold w-28">Credit (₹)</th>
                <th className="pb-2 text-left font-semibold pl-3">Narration</th>
                <th className="pb-2 w-6" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {lines.map((line, idx) => (
                <tr key={idx}>
                  <td className="py-1.5 pr-2">
                    <select
                      value={line.account_id}
                      onChange={(e) => setLine(idx, { account_id: e.target.value })}
                      className="w-full px-2 py-1 border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs"
                    >
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
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={line.debit_paise === 0 ? "" : (line.debit_paise / 100).toFixed(2)}
                      onChange={(e) => {
                        const v = Math.round(parseFloat(e.target.value || "0") * 100);
                        setLine(idx, { debit_paise: v, credit_paise: v > 0 ? 0 : line.credit_paise });
                      }}
                      placeholder="0.00"
                      className="w-full px-2 py-1 border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs"
                    />
                  </td>
                  <td className="py-1.5 px-2">
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={line.credit_paise === 0 ? "" : (line.credit_paise / 100).toFixed(2)}
                      onChange={(e) => {
                        const v = Math.round(parseFloat(e.target.value || "0") * 100);
                        setLine(idx, { credit_paise: v, debit_paise: v > 0 ? 0 : line.debit_paise });
                      }}
                      placeholder="0.00"
                      className="w-full px-2 py-1 border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs"
                    />
                  </td>
                  <td className="py-1.5 pl-3">
                    <input
                      value={line.narration}
                      onChange={(e) => setLine(idx, { narration: e.target.value })}
                      placeholder="optional"
                      className="w-full px-2 py-1 border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs"
                    />
                  </td>
                  <td className="py-1.5 pl-1">
                    {lines.length > 2 && (
                      <button onClick={() => removeLine(idx)} className="text-gray-300 hover:text-red-400 text-xs font-bold">×</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-gray-100 text-xs font-semibold">
                <td className="pt-2 text-gray-500">Total</td>
                <td className="pt-2 text-right text-gray-700 px-2">
                  {totalDebit > 0 ? `₹${(totalDebit / 100).toFixed(2)}` : "—"}
                </td>
                <td className="pt-2 text-right text-gray-700 px-2">
                  {totalCredit > 0 ? `₹${(totalCredit / 100).toFixed(2)}` : "—"}
                </td>
                <td colSpan={2} className="pt-2 pl-3">
                  {totalDebit > 0 && totalDebit !== totalCredit && (
                    <span className="text-red-500 text-[10px]">
                      Difference: ₹{(Math.abs(totalDebit - totalCredit) / 100).toFixed(2)}
                    </span>
                  )}
                  {isBalanced && <span className="text-green-600 text-[10px]">✓ Balanced</span>}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>

        <button onClick={addLine} className="text-xs text-blue-600 hover:underline flex items-center gap-1">
          <Plus size={12} /> Add line
        </button>

        {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}

        <div className="flex gap-3 justify-end pt-1">
          <button
            onClick={() => handleSave(false)}
            disabled={saving || !isBalanced}
            className="text-xs px-4 py-2 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40"
          >
            Save Draft
          </button>
          <button
            onClick={() => handleSave(true)}
            disabled={saving || !isBalanced}
            className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40"
          >
            {saving ? "Saving…" : "Post Entry"}
          </button>
        </div>
      </div>

      {/* Recent entries */}
      {recentEntries.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-50">
            <p className="text-xs font-semibold text-gray-700">Recent Entries</p>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-50 text-gray-400">
                <th className="px-4 py-2 text-left font-semibold">Date</th>
                <th className="px-3 py-2 text-left font-semibold">Narration</th>
                <th className="px-3 py-2 text-left font-semibold">Type</th>
                <th className="px-3 py-2 text-right font-semibold">Amount</th>
                <th className="px-4 py-2 text-left font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {recentEntries.map((e) => {
                const totalDr = (e.lines ?? []).reduce((s, l) => s + l.debit_paise, 0);
                return (
                  <tr key={e.id} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-gray-500 whitespace-nowrap">{e.entry_date}</td>
                    <td className="px-3 py-2 text-gray-700 truncate max-w-[200px]">{e.narration}</td>
                    <td className="px-3 py-2 text-gray-400">{e.entry_type}</td>
                    <td className="px-3 py-2 text-right font-mono text-gray-700">
                      ₹{(totalDr / 100).toFixed(2)}
                    </td>
                    <td className="px-4 py-2">
                      <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${e.is_posted ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                        {e.is_posted ? "Posted" : "Draft"}
                      </span>
                    </td>
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
      .select("id, debit_paise, credit_paise, narration, journal_entries!inner(entry_date, reference_no, narration, is_posted, client_id)")
      .eq("account_id", accountId)
      .eq("journal_entries.client_id", clientId)
      .eq("journal_entries.is_posted", true)
      .gte("journal_entries.entry_date", start)
      .lte("journal_entries.entry_date", end)
      .order("journal_entries(entry_date)", { ascending: true });

    if (data) {
      let running = 0;
      const mapped: LedgerLine[] = (data as unknown as Array<{
        id: string;
        debit_paise: number;
        credit_paise: number;
        narration: string | null;
        journal_entries: { entry_date: string; reference_no: string | null; narration: string; is_posted: boolean };
      }>).map((row) => {
        running += row.debit_paise - row.credit_paise;
        return {
          id: row.id,
          entry_date: row.journal_entries.entry_date,
          narration: row.narration ?? row.journal_entries.narration,
          reference_no: row.journal_entries.reference_no,
          debit_paise: row.debit_paise,
          credit_paise: row.credit_paise,
          running_balance_paise: running,
          is_debit: running >= 0,
        };
      });
      setLines(mapped);
    }
    setLoading(false);
  }

  return (
    <div className="space-y-4 max-w-4xl">
      <div className="bg-white rounded-xl border border-gray-100 p-4">
        <label className="block text-xs font-medium text-gray-600 mb-1.5">Select Account</label>
        <select
          value={selectedAccountId}
          onChange={(e) => { setSelectedAccountId(e.target.value); loadLedger(e.target.value); }}
          className="w-full max-w-xs px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">— Choose account —</option>
          {["Asset","Liability","Equity","Revenue","Expense"].map((type) => (
            <optgroup key={type} label={type}>
              {accounts.filter((a) => a.account_type === type).map((a) => (
                <option key={a.id} value={a.id}>{a.account_code} — {a.account_name}</option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>

      {selectedAccountId && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-50 flex items-center justify-between">
            <p className="text-xs font-semibold text-gray-700">
              Ledger — FY {financialYear} — {accounts.find((a) => a.id === selectedAccountId)?.account_name}
            </p>
            {loading && <RefreshCw size={13} className="animate-spin text-gray-400" />}
          </div>
          {!loading && lines.length > 0 ? (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100 text-gray-400">
                  <th className="px-4 py-2.5 text-left font-semibold">Date</th>
                  <th className="px-3 py-2.5 text-left font-semibold">Particulars</th>
                  <th className="px-3 py-2.5 text-left font-semibold">Ref</th>
                  <th className="px-3 py-2.5 text-right font-semibold">Debit</th>
                  <th className="px-3 py-2.5 text-right font-semibold">Credit</th>
                  <th className="px-4 py-2.5 text-right font-semibold">Balance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {lines.map((l) => (
                  <tr key={l.id} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-gray-500 whitespace-nowrap">{l.entry_date}</td>
                    <td className="px-3 py-2 text-gray-700">{l.narration}</td>
                    <td className="px-3 py-2 font-mono text-gray-400">{l.reference_no ?? "—"}</td>
                    <td className="px-3 py-2 text-right font-mono text-gray-700">{paiseToCurrency(l.debit_paise)}</td>
                    <td className="px-3 py-2 text-right font-mono text-gray-700">{paiseToCurrency(l.credit_paise)}</td>
                    <td className={`px-4 py-2 text-right font-mono font-semibold ${l.is_debit ? "text-blue-700" : "text-orange-700"}`}>
                      {paiseToCurrency(Math.abs(l.running_balance_paise))}
                      <span className="text-[10px] font-normal ml-1 opacity-60">{l.is_debit ? "Dr" : "Cr"}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : !loading ? (
            <div className="text-center py-10 text-gray-400 text-sm">No posted transactions for this account in FY {financialYear}.</div>
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

  async function load() {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    const { start, end } = fyDateRange(financialYear);
    const supabase = getSupabaseClient();

    // Fetch all posted journal lines for this client in the FY
    const { data } = await supabase
      .from("journal_lines")
      .select(`
        debit_paise, credit_paise,
        chart_of_accounts!inner(id, account_code, account_name, account_type),
        journal_entries!inner(entry_date, is_posted, client_id)
      `)
      .eq("journal_entries.client_id", clientId)
      .eq("journal_entries.is_posted", true)
      .gte("journal_entries.entry_date", start)
      .lte("journal_entries.entry_date", end);

    if (data) {
      const map: Record<string, TrialRow> = {};
      for (const row of data as unknown as Array<{
        debit_paise: number;
        credit_paise: number;
        chart_of_accounts: { id: string; account_code: string; account_name: string; account_type: string };
        journal_entries: { entry_date: string; is_posted: boolean; client_id: string };
      }>) {
        const acc = row.chart_of_accounts;
        if (!map[acc.id]) {
          map[acc.id] = { account_id: acc.id, account_code: acc.account_code, account_name: acc.account_name, account_type: acc.account_type, total_debit_paise: 0, total_credit_paise: 0 };
        }
        map[acc.id].total_debit_paise += row.debit_paise;
        map[acc.id].total_credit_paise += row.credit_paise;
      }
      setRows(Object.values(map).sort((a, b) => a.account_code.localeCompare(b.account_code)));
    }
    setLoading(false);
    setLoaded(true);
  }

  useEffect(() => { load(); }, [clientId, financialYear]);

  const grandDebit = rows.reduce((s, r) => s + r.total_debit_paise, 0);
  const grandCredit = rows.reduce((s, r) => s + r.total_credit_paise, 0);
  const isBalanced = grandDebit === grandCredit;

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-gray-700">Trial Balance — FY {financialYear}</p>
        <button onClick={load} className="p-1.5 rounded border border-gray-200 hover:bg-gray-50 text-gray-500">
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {loading ? (
        <div className="h-40 rounded-lg bg-gray-50 animate-pulse" />
      ) : loaded && rows.length > 0 ? (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-100 text-gray-400">
                <th className="px-4 py-3 text-left font-semibold">Code</th>
                <th className="px-3 py-3 text-left font-semibold">Account</th>
                <th className="px-3 py-3 text-left font-semibold">Type</th>
                <th className="px-3 py-3 text-right font-semibold">Debit (₹)</th>
                <th className="px-4 py-3 text-right font-semibold">Credit (₹)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {rows.map((r) => (
                <tr key={r.account_id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-mono text-gray-500">{r.account_code}</td>
                  <td className="px-3 py-2 font-medium text-gray-800">{r.account_name}</td>
                  <td className="px-3 py-2 text-gray-400">{r.account_type}</td>
                  <td className="px-3 py-2 text-right font-mono text-gray-700">{paiseToCurrency(r.total_debit_paise)}</td>
                  <td className="px-4 py-2 text-right font-mono text-gray-700">{paiseToCurrency(r.total_credit_paise)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-gray-200 font-semibold text-sm">
                <td colSpan={3} className="px-4 py-3 text-gray-700">Total</td>
                <td className="px-3 py-3 text-right font-mono text-gray-900">
                  ₹{(grandDebit / 100).toFixed(2)}
                </td>
                <td className="px-4 py-3 text-right font-mono text-gray-900">
                  ₹{(grandCredit / 100).toFixed(2)}
                </td>
              </tr>
              <tr>
                <td colSpan={5} className="px-4 pb-3">
                  {isBalanced ? (
                    <span className="text-xs text-green-600 font-medium">✓ Trial Balance is balanced</span>
                  ) : (
                    <span className="text-xs text-red-600 font-medium">
                      ✗ Out of balance by ₹{(Math.abs(grandDebit - grandCredit) / 100).toFixed(2)}
                    </span>
                  )}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      ) : loaded ? (
        <div className="text-center py-12 text-gray-400 text-sm">
          No posted journal entries for FY {financialYear}.
        </div>
      ) : null}
    </div>
  );
}
