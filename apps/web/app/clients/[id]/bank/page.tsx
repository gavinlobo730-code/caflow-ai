"use client";

/**
 * Bank workspace — the statement-to-books pipeline, extracted from the
 * Accounting page.
 *
 * WHY IT IS ITS OWN SECTION
 *   Banking is a SEQUENTIAL workflow: import a statement, categorise what came
 *   in, post it to the books, then reconcile against the statement balance.
 *   You do those in order, repeatedly. The financial statements next door are
 *   the opposite — you jump straight to the one you want. Mixing a pipeline in
 *   among them buried the order and pushed the Accounting tab bar to 15 items.
 *   Here the tab order IS the process.
 *
 * SCOPE OF THE MOVE
 *   Behaviour-preserving. The four components below are the same ones the
 *   Accounting page rendered for its Banks / Categorize / Post / Reconciliation
 *   tabs, moved verbatim. Only the labels changed: "Post" -> "Post to Books"
 *   (easy to confuse with the Accounting page's own journal posting and
 *   Approvals queue) and "Reconciliation" -> "Reconcile" (Accounting keeps
 *   "Verify Books", the integrity engine — a different thing that read as a
 *   synonym while the two sat side by side).
 *
 *   Approvals deliberately did NOT move: it is a general journal approval queue
 *   (api.accounting.journalsQueue / postDraftJournal), not a banking step.
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { Plus, RefreshCw, Upload, CheckCircle, X, FileText, Download, Pencil, Landmark } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { formatPaise } from "@/lib/services/formatting";
import { AccountLookup } from "@/components/lookups/AccountLookup";
import { CustomerLookup } from "@/components/lookups/CustomerLookup";
import { VendorLookup } from "@/components/lookups/VendorLookup";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { api } from "@/lib/api";
import { TableSkeleton, StatementSkeleton, TransactionListSkeleton } from "@/components/ui/skeleton";
import {
  getBankStatements,
  getBankTransactions,
  type BankStatement,
  type BankTransaction,
} from "@/lib/data/bankStatements";

// ── Tabs, in pipeline order ────────────────────────────────────────────────

type BankTab = "accounts" | "categorize" | "post" | "reconcile";

const TABS: { id: BankTab; label: string }[] = [
  { id: "accounts",   label: "Accounts" },
  { id: "categorize", label: "Categorize" },
  { id: "post",       label: "Post to Books" },
  { id: "reconcile",  label: "Reconcile" },
];

// ── Shared types & helpers ─────────────────────────────────────────────────
// Kept local rather than imported from the Accounting page: this route must not
// depend on that module, or the extraction buys nothing.

interface Account {
  id: string;
  account_code: string;
  account_name: string;
  account_type: "Asset" | "Liability" | "Equity" | "Revenue" | "Expense";
  account_subtype: string | null;
  is_active: boolean;
  client_id: string | null;
}

function fmt(paise: number): string {
  return paise === 0 ? "\u2014" : formatPaise(paise);
}

function rsToP(rs: number): number {
  return Math.round(rs * 100);
}

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
  // Distinguishes "fetch failed" from "queue genuinely empty" (a masked
  // failure here reads as a fully-reconciled bank, which it may not be).
  const [loadError, setLoadError] = useState<string | null>(null);
  // Multi-invoice bank allocation — split ONE transaction across several
  // invoices/bills for one party, in a single settlement.
  const [splitTxn, setSplitTxn] = useState<QueueTxn | null>(null);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    try {
      const res = (await api.banking.queue({ client_id: clientId, status })) as { success: boolean; data: QueueTxn[] };
      if (!res.success) throw new Error("Couldn't load the bank match queue.");
      setRows(res.data ?? []);
      setLoadError(null);
    } catch (e) {
      setRows([]);
      setLoadError(e instanceof Error ? e.message : "Couldn't load the bank match queue.");
    } finally {
      setLoading(false);
    }
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
    // The action has completed — clear the selection regardless of partial
    // failures (the error banner reports what didn't go through). Leaving the
    // successfully-categorized rows selected is confusing: they've already left
    // the match queue, so the count would just be counting ghosts. Mirrors the
    // shared DataTable's bulk-action behavior (components/ui/data-table.tsx).
    if (failCount > 0) {
      setBulkError(`Failed to categorize ${failCount} of ${ids.length} transaction${ids.length === 1 ? "" : "s"}.`);
    }
    clearSelection();
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

      {loading ? <TransactionListSkeleton rows={4} /> : loadError ? (
        <div className="bg-white rounded-xl border border-red-200 p-10 text-center">
          <p className="text-sm text-red-600 font-medium mb-2">{loadError}</p>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      ) : rows.length === 0 ? (
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
                  <>
                    <button onClick={() => loadSugg(t.id)} disabled={busy[t.id]} className="text-xs px-2.5 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569]">
                      Suggest matches
                    </button>
                    <button onClick={() => setSplitTxn(t)} disabled={busy[t.id]} className="text-xs px-2.5 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569]">
                      Split across multiple {t.credit_paise > 0 ? "invoices" : "bills"}
                    </button>
                  </>
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
      {splitTxn && (
        <MultiInvoiceMatchModal
          txn={splitTxn}
          clientId={clientId}
          onClose={() => setSplitTxn(null)}
          onDone={() => { setSplitTxn(null); load(); }}
        />
      )}
    </div>
  );
}

// ── Multi-invoice bank allocation modal ─────────────────────────────────────
// Splits ONE bank transaction across SEVERAL sales invoices (a credit
// transaction) or purchase bills (a debit transaction) for one customer/
// vendor, in a single settlement — reached from "Split across multiple
// invoices/bills" in the Bank Match Queue.

interface SplitDoc {
  id: string; no: string; date: string; outstanding_paise: number; currency: string;
}
interface SplitParty { id: string; name: string; gstin?: string | null }

function MultiInvoiceMatchModal({ txn, clientId, onClose, onDone }: {
  txn: QueueTxn; clientId: string; onClose: () => void; onDone: () => void;
}) {
  const isCredit = txn.credit_paise > 0;
  const txnAmount = isCredit ? txn.credit_paise : txn.debit_paise;
  const entityType: "sales_invoice" | "purchase_bill" = isCredit ? "sales_invoice" : "purchase_bill";
  const docLabel = isCredit ? "invoice" : "bill";

  const [parties, setParties] = useState<SplitParty[]>([]);
  const [partyId, setPartyId] = useState("");
  const [docs, setDocs] = useState<SplitDoc[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [amounts, setAmounts] = useState<Record<string, string>>({});   // rupees, per doc id
  const [exchangeRate, setExchangeRate] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const supabase = getSupabaseClient();
      if (isCredit) {
        const { data } = await selectAll<SplitParty>(() =>
          supabase.from("customers").select("id, name, gstin").eq("client_id", clientId).eq("is_active", true).order("name"));
        setParties(data ?? []);
      } else {
        const { data } = await selectAll<SplitParty>(() =>
          supabase.from("vendors").select("id, name, gstin").eq("client_id", clientId).eq("is_active", true).order("name"));
        setParties(data ?? []);
      }
    })();
  }, [clientId, isCredit]);

  useEffect(() => {
    setChecked(new Set()); setAmounts({}); setDocs([]); setError(null);
    if (!partyId) return;
    (async () => {
      setLoadingDocs(true);
      const supabase = getSupabaseClient();
      if (isCredit) {
        const { data } = await selectAll<{
          id: string; invoice_no: string; invoice_date: string; total_paise: number;
          paid_paise: number; credited_paise: number | null; debit_note_paise: number | null;
          status: string; txn_currency: string | null;
        }>(() =>
          supabase.from("client_sales_invoices")
            .select("id, invoice_no, invoice_date, total_paise, paid_paise, credited_paise, debit_note_paise, status, txn_currency")
            .eq("client_id", clientId).eq("customer_id", partyId).is("deleted_at", null)
            .neq("status", "cancelled").neq("status", "draft").order("invoice_date"));
        setDocs((data ?? []).map((r) => ({
          id: r.id, no: r.invoice_no, date: r.invoice_date, currency: r.txn_currency || "INR",
          // Mirrors bank_posting_service._invoice_outstanding (CGST Act §34).
          outstanding_paise: Math.max(
            r.total_paise + (r.debit_note_paise || 0) - r.paid_paise - (r.credited_paise || 0), 0),
        })).filter((d) => d.outstanding_paise > 0));
      } else {
        const { data } = await selectAll<{
          id: string; bill_no: string; bill_date: string; net_payable_paise: number; total_paise: number;
          paid_paise: number; debited_paise: number | null; credit_note_paise: number | null;
          status: string; txn_currency: string | null;
        }>(() =>
          supabase.from("purchase_bills")
            .select("id, bill_no, bill_date, net_payable_paise, total_paise, paid_paise, debited_paise, credit_note_paise, status, txn_currency")
            .eq("client_id", clientId).eq("vendor_id", partyId).is("deleted_at", null)
            .not("status", "in", "(cancelled,draft)").order("bill_date"));
        setDocs((data ?? []).map((r) => ({
          id: r.id, no: r.bill_no, date: r.bill_date, currency: r.txn_currency || "INR",
          // Mirrors bank_posting_service._bill_outstanding.
          outstanding_paise: Math.max(
            (r.net_payable_paise || r.total_paise) + (r.credit_note_paise || 0) - r.paid_paise - (r.debited_paise || 0), 0),
        })).filter((d) => d.outstanding_paise > 0));
      }
      setLoadingDocs(false);
    })();
  }, [partyId, clientId, isCredit]);

  const totalAllocatedPaise = Array.from(checked).reduce((sum, id) => sum + rsToP(parseFloat(amounts[id] || "0") || 0), 0);
  const remaining = txnAmount - totalAllocatedPaise;
  const checkedCurrencies = new Set(Array.from(checked).map((id) => docs.find((d) => d.id === id)?.currency ?? "INR"));
  const currency = checkedCurrencies.size === 1 ? Array.from(checkedCurrencies)[0] : null;
  const isForeign = currency != null && currency !== "INR";

  function toggle(doc: SplitDoc) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(doc.id)) {
        next.delete(doc.id);
        setAmounts((a) => { const na = { ...a }; delete na[doc.id]; return na; });
      } else {
        next.add(doc.id);
        const alreadyAllocated = Array.from(next).filter((id) => id !== doc.id)
          .reduce((sum, id) => sum + rsToP(parseFloat(amounts[id] || "0") || 0), 0);
        const remainingBefore = Math.max(txnAmount - alreadyAllocated, 0);
        const fill = Math.min(doc.outstanding_paise, remainingBefore);
        setAmounts((a) => ({ ...a, [doc.id]: (fill / 100).toFixed(2) }));
      }
      return next;
    });
  }

  async function save() {
    if (checked.size === 0) { setError(`Select at least one ${docLabel}.`); return; }
    if (checkedCurrencies.size > 1) { setError(`Select ${docLabel}s in a single currency.`); return; }
    if (isForeign && !exchangeRate) { setError("Enter the exchange rate for this foreign-currency settlement."); return; }
    if (totalAllocatedPaise > txnAmount) { setError("Total allocated exceeds the transaction amount."); return; }
    setSaving(true); setError(null);
    try {
      const res = await api.banking.matchMulti(txn.id, {
        entity_type: entityType,
        allocations: Array.from(checked).map((id) => ({ entity_id: id, allocated_paise: rsToP(parseFloat(amounts[id] || "0") || 0) })),
        currency: isForeign ? currency! : undefined,
        exchange_rate: isForeign ? exchangeRate : undefined,
      }) as { success: boolean; error?: string | null };
      if (!res.success) { setError(res.error ?? `Could not settle these ${docLabel}s.`); setSaving(false); return; }
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : `Could not settle these ${docLabel}s.`);
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#F1F5F9]">
          <div>
            <h3 className="text-sm font-semibold text-[#0F172A]">Split across multiple {docLabel}s</h3>
            <p className="text-xs text-[#64748B] mt-0.5">{txn.description} · {fmt(txnAmount)} {isCredit ? "credit" : "debit"}</p>
          </div>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>
        <div className="px-5 py-4 space-y-3 overflow-y-auto flex-1">
          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">{isCredit ? "Customer" : "Vendor"} *</label>
            {isCredit ? (
              <CustomerLookup customers={parties} value={partyId} onChange={setPartyId} ariaLabel="Customer" placeholder={`Select customer…`} />
            ) : (
              <VendorLookup vendors={parties} value={partyId} onChange={setPartyId} ariaLabel="Vendor" placeholder={`Select vendor…`} />
            )}
            <p className="text-[10px] text-[#94A3B8] mt-1">All selected {docLabel}s must belong to this one {isCredit ? "customer" : "vendor"}.</p>
          </div>

          {partyId && (
            loadingDocs ? (
              <TransactionListSkeleton rows={3} />
            ) : docs.length === 0 ? (
              <p className="text-xs text-[#94A3B8] text-center py-6">No open {docLabel}s for this {isCredit ? "customer" : "vendor"}.</p>
            ) : (
              <div className="border border-[#F1F5F9] rounded-lg divide-y divide-[#F8FAFC]">
                {docs.map((d) => (
                  <div key={d.id} className="flex items-center gap-2 px-3 py-2">
                    <input type="checkbox" checked={checked.has(d.id)} onChange={() => toggle(d)} className="h-3.5 w-3.5 rounded border-[#CBD5E1] shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium text-[#1E293B] truncate">{d.no}</p>
                      <p className="text-[10px] text-[#94A3B8]">{d.date} · Outstanding {fmt(d.outstanding_paise)} {d.currency !== "INR" ? d.currency : ""}</p>
                    </div>
                    {checked.has(d.id) && (
                      <input
                        type="number" min="0" step="0.01" value={amounts[d.id] ?? ""}
                        onChange={(e) => setAmounts((a) => ({ ...a, [d.id]: e.target.value }))}
                        className="w-24 border rounded px-2 py-1 text-xs text-right font-mono"
                      />
                    )}
                  </div>
                ))}
              </div>
            )
          )}

          {isForeign && (
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Exchange rate ({currency} → INR) *</label>
              <input type="number" step="0.0001" value={exchangeRate} onChange={(e) => setExchangeRate(e.target.value)}
                className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="e.g. 83.25" />
            </div>
          )}

          {checked.size > 0 && (
            <div className={`rounded-lg px-3 py-2 text-xs ${remaining < 0 ? "bg-red-50 text-red-700" : "bg-[#F8FAFC] text-[#475569]"}`}>
              Allocated {fmt(totalAllocatedPaise)} of {fmt(txnAmount)}
              {remaining > 0 && ` — ${fmt(remaining)} will remain unallocated on the ${isCredit ? "receipt" : "payment"}.`}
              {remaining < 0 && " — exceeds the transaction amount."}
            </div>
          )}
          {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
        </div>
        <div className="flex gap-3 justify-end px-5 py-4 border-t border-[#F1F5F9]">
          <button onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
          <button onClick={save} disabled={saving || checked.size === 0 || remaining < 0} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
            {saving ? "Settling…" : `Confirm allocation`}
          </button>
        </div>
      </div>
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
  credited_to_party_paise?: number;
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
  // Distinguishes "fetch failed" from "nothing ready/pending/posted" — a masked
  // failure here reads as a fully-caught-up posting queue, which it may not be.
  const [loadError, setLoadError] = useState<string | null>(null);
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
      if (!r.success || !pen.success || !p.success) throw new Error("Couldn't load the bank posting queue.");
      setReady(r.data ?? []);
      setPending(pen.data ?? []);
      setPosted(p.data ?? []);
      setLoadError(null);
    } catch (e) {
      setReady([]); setPending([]); setPosted([]);
      setLoadError(e instanceof Error ? e.message : "Couldn't load the bank posting queue.");
    } finally {
      setLoading(false);
    }
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

      {loading ? <TableSkeleton cols={6} rows={5} /> : loadError ? (
        <div className="bg-white rounded-xl border border-red-200 p-10 text-center">
          <p className="text-sm text-red-600 font-medium mb-2">{loadError}</p>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      ) : view === "pending" ? (
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
              <TableSkeleton cols={3} rows={2} bare className="rounded-lg border border-[#F1F5F9]" />
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
              {!!preview.settlement.credited_to_party_paise && (
                <p className="mt-1 pt-1 border-t border-amber-200">
                  This payment exceeds what&apos;s outstanding — the extra{" "}
                  <span className="font-mono">{fmt(preview.settlement.credited_to_party_paise)}</span>{" "}
                  will be credited to the {preview.settlement.entity === "purchase_bill" ? "vendor's" : "customer's"}{" "}
                  account, applyable to a future {preview.settlement.entity === "purchase_bill" ? "bill" : "invoice"}.
                </p>
              )}
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

interface BankAccount {
  id: string;
  bank_name: string;
  account_no: string;
  ifsc: string | null;
  account_type: string;
  opening_balance_paise: number;
  opening_balance_date: string | null;
  coa_account_id: string | null;
  currency: string;
  is_active: boolean;
}

function BankAccounts({ clientId }: { clientId: string }) {
  const [statements, setStatements] = useState<BankStatement[]>([]);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [showImport, setShowImport] = useState(false);
  // null = closed, "new" = create form, BankAccount = edit that account.
  const [accountModal, setAccountModal] = useState<BankAccount | "new" | null>(null);
  const [selectedStmt, setSelectedStmt] = useState<string | null>(null);
  const [stmtTxns, setStmtTxns] = useState<BankTransaction[]>([]);
  const [txnsLoading, setTxnsLoading] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  // Loads BOTH the imported statements and the client's bank accounts — the
  // account list drives the import + reconciliation account pickers.
  const loadStatements = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    try {
      const [stmts, accRes] = await Promise.all([
        getBankStatements(clientId),
        api.banking.listBankAccounts({ client_id: clientId }) as Promise<{ success: boolean; data: BankAccount[] }>,
      ]);
      setStatements(stmts);
      setAccounts(accRes.success ? (accRes.data ?? []) : []);
    } catch { /* skip */ }
    setLoading(false);
  }, [clientId]);

  useEffect(() => { loadStatements(); }, [loadStatements]);

  async function deactivateAccount(a: BankAccount) {
    if (!confirm(`Deactivate ${a.bank_name} (····${a.account_no.slice(-4)})? Existing statements and reconciliations keep it — it just won't be selectable for new imports. You can reactivate it later by editing it.`)) return;
    try {
      const res = await api.banking.updateBankAccount(a.id, { is_active: false }) as { success: boolean; error: string | null };
      if (!res.success) { setMsg({ type: "err", text: res.error ?? "Could not deactivate the account." }); return; }
      setMsg({ type: "ok", text: "Bank account deactivated." });
      loadStatements();
    } catch (e) { setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not deactivate the account." }); }
  }

  const activeAccounts = accounts.filter((a) => a.is_active);

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
      {msg && (
        <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm ${msg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
          {msg.type === "ok" ? <CheckCircle size={14} /> : <X size={14} />}
          {msg.text}
          <button onClick={() => setMsg(null)} className="ml-auto"><X size={13} /></button>
        </div>
      )}

      {/* ── Bank accounts ─────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="px-4 py-3 border-b border-[#F1F5F9] flex items-center justify-between">
          <p className="text-xs font-semibold text-[#334155] flex items-center gap-1.5"><Landmark size={13} /> Bank Accounts</p>
          <button onClick={() => setAccountModal("new")} className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
            <Plus size={12} /> Add Account
          </button>
        </div>
        {loading ? (
          <TableSkeleton cols={6} rows={2} />
        ) : accounts.length === 0 ? (
          <div className="text-center py-8 px-4 space-y-1">
            <p className="text-sm text-[#64748B]">No bank accounts yet.</p>
            <p className="text-xs text-[#94A3B8]">Add a bank account to import its statements and run reconciliations.</p>
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]"><th className="px-4 py-2.5 text-left font-semibold">Bank</th><th className="px-3 py-2.5 text-left font-semibold">Account No.</th><th className="px-3 py-2.5 text-left font-semibold">Type</th><th className="px-3 py-2.5 text-left font-semibold">Ledger Account</th><th className="px-3 py-2.5 text-right font-semibold">Opening Bal.</th><th className="px-4 py-2.5 text-right font-semibold">Actions</th></tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {accounts.map((a) => (
                <tr key={a.id} className={`hover:bg-[#F8FAFC] ${a.is_active ? "" : "opacity-50"}`}>
                  <td className="px-4 py-2.5 font-medium text-[#1E293B]">
                    {a.bank_name}
                    {!a.is_active && <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full bg-[#F1F5F9] text-[#94A3B8]">inactive</span>}
                    {a.ifsc && <div className="text-[10px] text-[#94A3B8] font-mono">{a.ifsc}</div>}
                  </td>
                  <td className="px-3 py-2.5 font-mono text-[#64748B] text-[10px]">{a.account_no}</td>
                  <td className="px-3 py-2.5 text-[#64748B]">{a.account_type}</td>
                  <td className="px-3 py-2.5 text-[#64748B]">{a.coa_account_id ? "Linked" : <span className="text-amber-600">Not linked</span>}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-[#334155]">{fmt(a.opening_balance_paise)}</td>
                  <td className="px-4 py-2.5 text-right whitespace-nowrap">
                    <button onClick={() => setAccountModal(a)} className="text-[#4338CA] hover:text-[#3730A3] inline-flex items-center gap-1"><Pencil size={11} /> Edit</button>
                    {a.is_active && <button onClick={() => deactivateAccount(a)} className="ml-3 text-red-600 hover:text-red-800">Deactivate</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">{statements.length} bank statement{statements.length !== 1 ? "s" : ""} imported</p>
        <div className="flex gap-2">
          <button onClick={loadStatements} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>
          <button
            onClick={() => activeAccounts.length === 0 ? setAccountModal("new") : setShowImport(true)}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
            title={activeAccounts.length === 0 ? "Add a bank account first" : "Import a statement for one of your bank accounts"}
          >
            <Upload size={12} /> Import Statement
          </button>
        </div>
      </div>

      {loading ? (
        <TableSkeleton cols={7} rows={3} />
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
        <BankImportModal
          clientId={clientId}
          accounts={activeAccounts}
          onClose={() => setShowImport(false)}
          onImported={() => { setShowImport(false); loadStatements(); }}
          onManageAccounts={() => { setShowImport(false); setAccountModal("new"); }}
        />
      )}
      {accountModal && (
        <BankAccountModal
          clientId={clientId}
          account={accountModal === "new" ? null : accountModal}
          onClose={() => setAccountModal(null)}
          onSaved={() => { setAccountModal(null); setMsg({ type: "ok", text: "Bank account saved." }); loadStatements(); }}
        />
      )}
    </div>
  );
}

// ── Bank Account Modal (create / edit) ─────────────────────────────────────
// A bank account is the entity a statement is imported against and a
// reconciliation session is opened for. coa_account_id links it to a
// chart-of-accounts ledger account so postings hit the right GL account and
// the opening balance flows to the books (backend auto-syncs on save).

interface CoaAccountLite { id: string; account_code: string; account_name: string; account_type: string }

function BankAccountModal({ clientId, account, onClose, onSaved }: {
  clientId: string; account: BankAccount | null; onClose: () => void; onSaved: () => void;
}) {
  const editing = !!account;
  const [bankName, setBankName] = useState(account?.bank_name ?? "HDFC Bank");
  const [accountNo, setAccountNo] = useState(account?.account_no ?? "");
  const [ifsc, setIfsc] = useState(account?.ifsc ?? "");
  const [accountType, setAccountType] = useState(account?.account_type ?? "Current");
  const [openingBal, setOpeningBal] = useState(account ? (account.opening_balance_paise / 100).toString() : "");
  const [openingDate, setOpeningDate] = useState(account?.opening_balance_date ?? "");
  const [coaId, setCoaId] = useState(account?.coa_account_id ?? "");
  const [isActive, setIsActive] = useState(account?.is_active ?? true);
  const [coaAccounts, setCoaAccounts] = useState<CoaAccountLite[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      // Only Asset accounts can be a bank's GL account (Bank/Cash sit under Assets).
      const supabase = getSupabaseClient();
      const { data } = await selectAll(() => supabase
        .from("chart_of_accounts")
        .select("id, account_code, account_name, account_type")
        .or(`client_id.eq.${clientId},client_id.is.null`)
        .eq("is_active", true)
        .eq("account_type", "Asset")
        .order("account_code").order("id"));
      setCoaAccounts((data as CoaAccountLite[]) ?? []);
    })();
  }, [clientId]);

  async function save() {
    if (!bankName.trim()) { setError("Bank name is required."); return; }
    if (!editing && !accountNo.trim()) { setError("Account number is required."); return; }
    setSaving(true); setError(null);
    const openingPaise = Math.round(parseFloat(openingBal || "0") * 100);
    try {
      const res = (editing
        ? await api.banking.updateBankAccount(account!.id, {
            bank_name: bankName.trim(), ifsc: ifsc.trim() || null, account_type: accountType,
            opening_balance_paise: openingPaise, opening_balance_date: openingDate || null,
            coa_account_id: coaId || null, is_active: isActive,
          })
        : await api.banking.createBankAccount({
            client_id: clientId, bank_name: bankName.trim(), account_no: accountNo.trim(),
            ifsc: ifsc.trim() || null, account_type: accountType,
            opening_balance_paise: openingPaise, opening_balance_date: openingDate || null,
            coa_account_id: coaId || null,
          })
      ) as { success: boolean; error: string | null };
      if (!res.success) { setError(res.error ?? "Could not save the bank account."); setSaving(false); return; }
      onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save the bank account."); setSaving(false); }
  }

  const inputCls = "w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500";
  const labelCls = "block text-xs font-medium text-[#475569] mb-1";

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">{editing ? "Edit Bank Account" : "Add Bank Account"}</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className={labelCls}>Bank Name *</label>
            <input value={bankName} onChange={(e) => setBankName(e.target.value)} list="bank-name-options" className={inputCls} placeholder="HDFC Bank" />
            <datalist id="bank-name-options">
              {["HDFC Bank","SBI","ICICI Bank","Axis Bank","Kotak Mahindra Bank","IndusInd Bank","Yes Bank","IDFC First Bank","Punjab National Bank","Bank of Baroda"].map((b) => <option key={b} value={b} />)}
            </datalist>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Account Number *</label>
              <input value={accountNo} onChange={(e) => setAccountNo(e.target.value)} disabled={editing} className={`${inputCls} font-mono ${editing ? "bg-[#F8FAFC] text-[#94A3B8]" : ""}`} placeholder="50100XXXXXXX" />
            </div>
            <div>
              <label className={labelCls}>IFSC</label>
              <input value={ifsc} onChange={(e) => setIfsc(e.target.value.toUpperCase())} maxLength={11} className={`${inputCls} font-mono`} placeholder="HDFC0001234" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Account Type</label>
              <select value={accountType} onChange={(e) => setAccountType(e.target.value)} className={inputCls}>
                {["Current","Savings","Cash Credit","Overdraft"].map((t) => <option key={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className={labelCls}>Opening Balance (₹)</label>
              <input type="number" step="0.01" value={openingBal} onChange={(e) => setOpeningBal(e.target.value)} className={inputCls} placeholder="0.00" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Opening Balance Date</label>
              <input type="date" value={openingDate} onChange={(e) => setOpeningDate(e.target.value)} className={inputCls} />
            </div>
            {editing && (
              <div className="flex items-end pb-1">
                <label className="flex items-center gap-2 text-xs text-[#475569]">
                  <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} className="accent-[#4338CA]" /> Active
                </label>
              </div>
            )}
          </div>
          <div>
            <label className={labelCls}>Ledger Account (GL link)</label>
            <select value={coaId} onChange={(e) => setCoaId(e.target.value)} className={inputCls}>
              <option value="">— Not linked —</option>
              {coaAccounts.map((c) => <option key={c.id} value={c.id}>{c.account_code} · {c.account_name}</option>)}
            </select>
            <p className="text-[10px] text-[#94A3B8] mt-1">Links this bank account to a chart-of-accounts asset account so postings and the opening balance hit the right GL account.</p>
          </div>
        </div>
        {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
          <button onClick={save} disabled={saving} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
            {saving ? "Saving…" : editing ? "Save Changes" : "Add Account"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Bank Import Modal ──────────────────────────────────────────────────────

function BankImportModal({ clientId, accounts, onClose, onImported, onManageAccounts }: {
  clientId: string; accounts: BankAccount[]; onClose: () => void; onImported: () => void; onManageAccounts: () => void;
}) {
  const [accountId, setAccountId] = useState(accounts[0]?.id ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ imported: number; duplicates_skipped: number; total_rows: number } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const account = accounts.find((a) => a.id === accountId);

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) { setFile(f); setError(null); setResult(null); }
  }

  async function handleImport() {
    if (!account) { setError("Select a bank account."); return; }
    if (!file) { setError("Select a statement file (.csv or .xlsx)."); return; }
    setImporting(true); setError(null);
    try {
      // Server-side parse + normalize + dedup (bank-specific adapters, fail-loud,
      // integer-paise) — the browser sends the raw file, no client-side parsing.
      const form = new FormData();
      form.append("file", file);
      form.append("client_id", clientId);
      form.append("bank_account_id", account.id);
      form.append("bank_name", account.bank_name);
      if (account.account_no) form.append("account_number", account.account_no);
      const res = (await api.banking.uploadStatement(form)) as {
        success: boolean; data: { imported: number; duplicates_skipped: number; total_rows: number }; error?: string;
      };
      if (!res.success) { setError(res.error ?? "Import failed."); setImporting(false); return; }
      setResult(res.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setImporting(false);
    }
  }

  const inputCls = "w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500";

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">Import Bank Statement</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>

        {result ? (
          <>
            <div className="bg-green-50 border border-green-100 rounded-lg px-4 py-3 text-center space-y-1">
              <CheckCircle size={20} className="text-green-600 mx-auto" />
              <p className="text-sm font-medium text-green-700">{result.imported} transaction{result.imported === 1 ? "" : "s"} imported</p>
              {result.duplicates_skipped > 0 && (
                <p className="text-xs text-green-600">{result.duplicates_skipped} duplicate{result.duplicates_skipped === 1 ? "" : "s"} skipped (already imported)</p>
              )}
            </div>
            <div className="flex justify-end">
              <button onClick={onImported} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">Done</button>
            </div>
          </>
        ) : (
          <>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Bank Account *</label>
                {accounts.length === 0 ? (
                  <div className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
                    No active bank accounts. <button onClick={onManageAccounts} className="underline font-medium">Add one first</button>.
                  </div>
                ) : (
                  <select value={accountId} onChange={(e) => setAccountId(e.target.value)} className={inputCls}>
                    {accounts.map((a) => <option key={a.id} value={a.id}>{a.bank_name} · ····{a.account_no.slice(-4)}</option>)}
                  </select>
                )}
              </div>
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Statement File * <span className="font-normal text-[#94A3B8]">(.csv or .xlsx)</span></label>
                <input ref={fileRef} type="file" accept=".csv,.txt,.xlsx" onChange={handleFile} className="hidden" />
                <button onClick={() => fileRef.current?.click()} className="w-full border-2 border-dashed border-[#E2E8F0] rounded-lg py-4 text-sm text-[#64748B] hover:border-blue-300 hover:text-blue-600 transition-colors flex items-center justify-center gap-2">
                  <Upload size={16} /> {file ? file.name : "Click to select a statement file"}
                </button>
                <p className="text-[10px] text-[#94A3B8] mt-1">The file is parsed on the server — HDFC / SBI / ICICI / Axis formats are auto-detected. Amounts stay exact.</p>
              </div>
            </div>
            {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
            <div className="flex gap-3 justify-end">
              <button onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
              <button onClick={handleImport} disabled={importing || !file || accounts.length === 0} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
                {importing ? "Importing…" : "Import"}
              </button>
            </div>
          </>
        )}
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
      if (!res.success) throw new Error("Couldn't load reconciliation sessions.");
      setSessions(res.data ?? []);
      setError(null);
    } catch (e) {
      setSessions([]);
      setError(e instanceof Error ? e.message : "Couldn't load reconciliation sessions.");
    } finally {
      setLoading(false);
    }
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
      if (!res.success) throw new Error("Couldn't load the reconciliation report.");
      setReport(res.data);
      setAdj(((res.data.reconciliation.adjustments_paise || 0) / 100).toFixed(2));
    } catch (e) {
      setReport(null);
      setError(e instanceof Error ? e.message : "Couldn't load the reconciliation report.");
    } finally {
      setLoadingReport(false);
    }
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
      // The action completed — clear the row selection. Reconciled rows move to
      // a different view, so keeping their ids selected just leaves a stale
      // "N selected" count counting ghosts. (A thrown error below keeps the
      // selection for a retry.) Mirrors the shared DataTable behavior.
      setSel({});
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
      {selectedId && (loadingReport ? <StatementSkeleton sections={1} rowsPerSection={4} /> : report && (
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

// ── Page shell ─────────────────────────────────────────────────────────────

export default function BankPage() {
  const { clientId } = useClientNav();
  const [tab, setTab] = useState<BankTab>("accounts");
  // BankPostingQueue needs the chart of accounts to pick the contra account for
  // each posting, so it is loaded here rather than inside that component.
  const [accounts, setAccounts] = useState<Account[]>([]);

  const loadAccounts = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
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
    } catch {
      // A failed load leaves the account picker empty; the posting screen shows
      // its own empty state rather than this page swallowing the error.
      setAccounts([]);
    }
  }, [clientId]);

  useEffect(() => { loadAccounts(); }, [loadAccounts]);

  return (
    <div className="flex flex-col h-full overflow-hidden">
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

      <div className="flex-1 overflow-y-auto px-6 pb-6 pt-4 min-h-0">
        {tab === "accounts"   && <BankAccounts clientId={clientId} />}
        {tab === "categorize" && <BankMatchQueue clientId={clientId} />}
        {tab === "post"       && <BankPostingQueue clientId={clientId} accounts={accounts} />}
        {tab === "reconcile"  && <BankReconciliation clientId={clientId} />}
      </div>
    </div>
  );
}
