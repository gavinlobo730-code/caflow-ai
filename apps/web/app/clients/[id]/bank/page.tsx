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
 *
 * RULES
 *   A fifth tab, after the pipeline rather than inside it: rules are SETUP for
 *   the Categorize step, not a step you work through. The engine behind it had
 *   shipped years earlier with no screen to create a rule, so the table could
 *   only ever be empty — see
 *   docs/audits/2026-08-02-bank-module-quickbooks-gap-audit.md.
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

type BankTab = "accounts" | "categorize" | "post" | "reconcile" | "rules";

const TABS: { id: BankTab; label: string }[] = [
  { id: "accounts",   label: "Accounts" },
  { id: "categorize", label: "Categorize" },
  { id: "post",       label: "Post to Books" },
  { id: "reconcile",  label: "Reconcile" },
  // Setup for the Categorize step rather than a step of its own, so it sits
  // after the pipeline — the same place QuickBooks puts its Rules tab.
  { id: "rules",      label: "Rules" },
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
  // What a matching rule proposes for this row (Rules tab). The account and
  // narration are new: the rule engine used to return only a category.
  suggested_account_id: string | null;
  suggested_narration: string | null;
  suggested_by_rule: string | null;
}
interface MatchSuggestion {
  matched_entity_type: string; matched_entity_id: string; label: string;
  amount_paise: number; confidence: number; confidence_label: string; reasons: string[];
  // >0 when the bank line is SHORT of the document — a customer withholding TDS,
  // or bank charges. Accepting such a match settles only what actually arrived,
  // so the UI routes it to the settlement modal instead of a plain Accept.
  difference_paise: number;
  tds_rate_bps: number | null;
  party_id: string | null;
  outstanding_paise: number | null;
}

const QUEUE_FILTERS: { id: string; label: string }[] = [
  { id: "unmatched", label: "Unmatched" },
  { id: "categorized", label: "Categorized" },
  { id: "needs_review", label: "Needs Review" },
  { id: "matched", label: "Matched" },
  // Ignoring used to be one-way — no endpoint to undo it and no view that
  // listed ignored rows, so a mis-click permanently hid a statement line.
  { id: "ignored", label: "Excluded" },
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
  // Settlement modal — allocate ONE transaction across one or more invoices/
  // bills for a party, with any TDS the customer withheld. `prefill` is set when
  // the modal is opened from a short suggestion, so the CA lands on the right
  // party and document instead of re-finding what we just showed them.
  const [splitTxn, setSplitTxn] = useState<QueueTxn | null>(null);
  const [prefill, setPrefill] = useState<SettlePrefill | null>(null);

  function openSettle(t: QueueTxn, from?: MatchSuggestion) {
    setPrefill(from && from.party_id ? {
      partyId: from.party_id,
      docId: from.matched_entity_id,
      tdsPaise: from.difference_paise,
    } : null);
    setSplitTxn(t);
  }

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
  // Take everything the firing rule proposed: the category and, when it named
  // one, the counter GL account. Category first — set_account flips the row to
  // "matched", and categorize refuses to run once a draft journal exists, so
  // doing it the other way round would work today and break the moment posting
  // gets involved.
  async function applyRule(t: QueueTxn) {
    setBusy((b) => ({ ...b, [t.id]: true }));
    try {
      if (t.suggested_category) await api.banking.categorize(t.id, { category: t.suggested_category });
      if (t.suggested_account_id) await api.banking.setTransactionAccount(t.id, { account_id: t.suggested_account_id });
      await load();
    } catch (e) { alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy((b) => ({ ...b, [t.id]: false })); }
  }
  async function setIgnored(id: string, ignored: boolean) {
    setBusy((b) => ({ ...b, [id]: true }));
    try {
      await (ignored ? api.banking.ignoreTransaction(id) : api.banking.unignoreTransaction(id));
      await load();
    } catch (e) { alert(e instanceof Error ? e.message : "Failed"); }
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
                {t.match_status === "ignored" ? (
                  <button onClick={() => setIgnored(t.id, false)} disabled={busy[t.id]} className="text-xs px-2.5 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569]">
                    Restore to queue
                  </button>
                ) : t.matched_entity_id ? (
                  <>
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-green-50 text-green-700">Matched · {t.matched_entity_type}</span>
                    <button onClick={() => reject(t.id)} disabled={busy[t.id]} className="text-[10px] text-red-600 hover:underline">Unmatch</button>
                  </>
                ) : (
                  <>
                    <button onClick={() => loadSugg(t.id)} disabled={busy[t.id]} className="text-xs px-2.5 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569]">
                      Suggest matches
                    </button>
                    {/* Renamed from "Split across multiple invoices/bills": this
                        is also how you settle ONE invoice paid net of TDS, and
                        nobody looks under "split" for that. */}
                    <button onClick={() => openSettle(t)} disabled={busy[t.id]} className="text-xs px-2.5 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569]">
                      Settle {t.credit_paise > 0 ? "invoices" : "bills"} / TDS
                    </button>
                    <button onClick={() => setIgnored(t.id, true)} disabled={busy[t.id]} className="text-[10px] text-[#94A3B8] hover:text-[#64748B] hover:underline ml-auto">
                      Exclude
                    </button>
                  </>
                )}
              </div>

              {/* What a matching rule proposes for this row, with one click to
                  take it. Displaying the suggestion without a way to apply it
                  would repeat the original defect one layer up. */}
              {t.suggested_by_rule && !t.category && t.match_status !== "ignored" && (
                <div className="flex items-center gap-2 ml-1">
                  <p className="text-[10px] text-[#94A3B8] min-w-0 truncate">
                    Rule <span className="font-medium text-[#64748B]">{t.suggested_by_rule}</span>
                    {t.suggested_category ? ` → ${t.suggested_category}` : ""}
                    {t.suggested_account_id ? " + account" : ""}
                    {t.suggested_narration ? ` · ${t.suggested_narration}` : ""}
                  </p>
                  <button onClick={() => applyRule(t)} disabled={busy[t.id]}
                    className="text-[10px] px-2 py-0.5 border border-[#C7D2FE] bg-[#EEF2FF] text-[#4338CA] rounded hover:bg-[#E0E7FF] shrink-0">
                    Apply rule
                  </button>
                </div>
              )}

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
                        {/* A SHORT match settles only what arrived, leaving the
                            document partly open — which is wrong when the
                            shortfall is withheld TDS. Send it to the settlement
                            modal (party + document + TDS prefilled) rather than
                            let one click quietly under-settle. */}
                        {s.difference_paise > 0 ? (
                          <button onClick={() => openSettle(t, s)} disabled={busy[t.id]}
                            className="text-[10px] px-2 py-0.5 bg-amber-600 text-white rounded hover:bg-amber-700"
                            title={`Bank line is ${fmt(s.difference_paise)} short of this document`}>
                            {s.tds_rate_bps ? "Settle with TDS" : "Settle difference"}
                          </button>
                        ) : (
                          <button onClick={() => accept(t.id, s)} disabled={busy[t.id]} className="text-[10px] px-2 py-0.5 bg-blue-600 text-white rounded hover:bg-blue-700">Accept</button>
                        )}
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
          prefill={prefill}
          onClose={() => { setSplitTxn(null); setPrefill(null); }}
          onDone={() => { setSplitTxn(null); setPrefill(null); load(); }}
        />
      )}
    </div>
  );
}

// ── Bank settlement modal ───────────────────────────────────────────────────
// Allocates ONE bank transaction across one or more sales invoices (a credit
// transaction) or purchase bills (a debit transaction) for a single customer/
// vendor — reached from "Settle invoices / TDS" in the Bank Match Queue.
//
// TDS
//   The everyday Indian receipt: a customer settles a ₹1,00,000 invoice,
//   withholds 10% under s.194J of the Income-tax Act 1961, and remits ₹90,000.
//   The invoice is settled IN FULL; only the cash is short. The backend has
//   always supported this (match_and_settle_multi's `tds_paise` raises the
//   allocation cap accordingly) but the modal never collected the figure, so it
//   was always zero and the case had no route through the UI at all.
//
//   TDS is entered by the CA, never inferred. When the modal is opened from a
//   short match suggestion the field is PRE-FILLED with the shortfall the
//   backend measured — a starting figure to confirm or correct, not a decision.

interface SplitDoc {
  id: string; no: string; date: string; outstanding_paise: number; currency: string;
}
interface SplitParty { id: string; name: string; gstin?: string | null }
interface SettlePrefill {
  partyId: string;
  docId: string | null;
  tdsPaise: number;
}

function MultiInvoiceMatchModal({ txn, clientId, prefill, onClose, onDone }: {
  txn: QueueTxn; clientId: string; prefill?: SettlePrefill | null;
  onClose: () => void; onDone: () => void;
}) {
  const isCredit = txn.credit_paise > 0;
  const txnAmount = isCredit ? txn.credit_paise : txn.debit_paise;
  const entityType: "sales_invoice" | "purchase_bill" = isCredit ? "sales_invoice" : "purchase_bill";
  const docLabel = isCredit ? "invoice" : "bill";

  const [parties, setParties] = useState<SplitParty[]>([]);
  const [partyId, setPartyId] = useState(prefill?.partyId ?? "");
  const [docs, setDocs] = useState<SplitDoc[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [amounts, setAmounts] = useState<Record<string, string>>({});   // rupees, per doc id
  const [exchangeRate, setExchangeRate] = useState("");
  // TDS withheld by the customer, in rupees as typed. Only meaningful on a
  // credit (a receipt): TDS the client itself withholds on a vendor payment is
  // already carried in the bill's net_payable_paise, so it must not be added a
  // second time here — the backend applies tds_paise to sales invoices only.
  const [tds, setTds] = useState(
    prefill?.tdsPaise ? (prefill.tdsPaise / 100).toFixed(2) : "");
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

  // Opened from a short match suggestion: tick the document the backend
  // matched and allocate its FULL outstanding — the point of the TDS field is
  // that the document clears even though less cash arrived. Runs once the docs
  // for the prefilled party have loaded, and only while nothing is ticked, so
  // it never fights the CA's own selection.
  const prefillDocId = prefill?.docId ?? null;
  useEffect(() => {
    if (!prefillDocId || docs.length === 0 || checked.size > 0) return;
    const doc = docs.find((d) => d.id === prefillDocId);
    if (!doc) return;
    setChecked(new Set([doc.id]));
    setAmounts({ [doc.id]: (doc.outstanding_paise / 100).toFixed(2) });
    // `checked` is deliberately excluded: this must fire when the docs arrive,
    // not re-run every time the selection changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillDocId, docs]);

  const totalAllocatedPaise = Array.from(checked).reduce((sum, id) => sum + rsToP(parseFloat(amounts[id] || "0") || 0), 0);
  // Mirror of bank_posting_service.match_and_settle_multi's settlement_cap: the
  // documents that can be settled total the cash received PLUS any TDS the
  // customer withheld, because the withheld amount discharges the receivable
  // just as cash does (it lands in TDS receivable instead of the bank).
  const tdsPaise = isCredit ? Math.max(rsToP(parseFloat(tds || "0") || 0), 0) : 0;
  const settlementCap = txnAmount + tdsPaise;
  const remaining = settlementCap - totalAllocatedPaise;
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
        const remainingBefore = Math.max(settlementCap - alreadyAllocated, 0);
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
    if (totalAllocatedPaise > settlementCap) {
      setError(tdsPaise > 0
        ? "Total allocated exceeds the amount received plus TDS."
        : "Total allocated exceeds the transaction amount.");
      return;
    }
    setSaving(true); setError(null);
    try {
      const res = await api.banking.matchMulti(txn.id, {
        entity_type: entityType,
        allocations: Array.from(checked).map((id) => ({ entity_id: id, allocated_paise: rsToP(parseFloat(amounts[id] || "0") || 0) })),
        tds_paise: tdsPaise > 0 ? tdsPaise : undefined,
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
            <h3 className="text-sm font-semibold text-[#0F172A]">Settle {docLabel}s</h3>
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

          {/* TDS — receipts only. On a vendor payment the withholding is already
              inside the bill's net payable, so adding it here would double it. */}
          {isCredit && (
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">
                TDS withheld by the customer (₹)
              </label>
              <input
                type="number" min="0" step="0.01" value={tds}
                onChange={(e) => setTds(e.target.value)}
                className="w-full border rounded-lg px-3 py-2 text-sm font-mono" placeholder="0.00" />
              <p className="text-[10px] text-[#94A3B8] mt-1">
                {tdsPaise > 0
                  ? `Invoices totalling ${fmt(settlementCap)} can be settled from this ${fmt(txnAmount)} receipt — the ${fmt(tdsPaise)} withheld clears the receivable too.`
                  : "Leave blank unless the customer deducted tax at source. Enter the amount deducted, not the rate."}
              </p>
            </div>
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
              Allocated {fmt(totalAllocatedPaise)} of {fmt(settlementCap)}
              {tdsPaise > 0 && ` (${fmt(txnAmount)} received + ${fmt(tdsPaise)} TDS)`}
              {remaining > 0 && ` — ${fmt(remaining)} will remain unallocated on the ${isCredit ? "receipt" : "payment"}.`}
              {remaining < 0 && (tdsPaise > 0 ? " — exceeds the receipt plus TDS." : " — exceeds the transaction amount.")}
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
  /** Reopen provenance (Tier 2.5). A reopened period is a fact about the books. */
  reopen_count?: number;
  reopened_at?: string | null;
  reopen_reason?: string | null;
}
/** Beginning-balance suggestion + mismatch check (backend computes all of it). */
interface OpeningSuggestion {
  bank_account_id: string;
  /** Where it came from: the last completed reconciliation, or — if there has
   *  never been one — the bank account's own opening balance. */
  source: "previous_reconciliation" | "bank_account_opening";
  previous_reconciliation: {
    reconciliation_id: string; period_end: string;
    closing_balance_paise: number; completed_at: string | null;
  } | null;
  completed_count: number;
  suggested_opening_paise: number;
  /** The books' own record of everything reconciled so far. Equal to the
   *  suggestion unless something changed after a session was completed. */
  reconciled_book_balance_paise: number;
  mismatch_paise: number;
  matches: boolean;
}
interface ReconSummary {
  opening_balance_paise: number; deposits_paise: number; withdrawals_paise: number;
  adjustments_paise: number; reconciled_book_balance_paise: number;
  statement_closing_balance_paise: number; difference_paise: number; reconciles: boolean;
}
/** Tie-out as if the selected transactions were also reconciled (Tier 2.4). */
interface ReconPreview {
  reconciliation_id: string; selected_count: number; ineligible_ids: string[];
  current: ReconSummary; projected: ReconSummary; would_tie_out: boolean;
}
/** Prior certifications of one session (Tier 2.7). */
interface ReconHistory {
  reconciliation_id: string; status: string; reopen_count: number;
  current: { completed_at: string | null; completed_by: string | null;
             summary: ReconSummary | null; ties_out: boolean } | null;
  superseded: {
    completed_at: string | null; completed_by: string | null;
    superseded_at: string | null; superseded_by: string | null;
    reason: string | null; summary: ReconSummary | null; ties_out: boolean;
  }[];
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
  // Where this account's next reconciliation should start, fetched as soon as an
  // account is picked. The opening balance is not a matter of opinion — it is
  // the closing balance the last completed reconciliation tied out to, and it is
  // already stored in that session's frozen snapshot. Typing it by hand meant a
  // typo produced a reconciliation that tied out perfectly to the wrong number.
  const [opening, setOpening] = useState<OpeningSuggestion | null>(null);
  const [openingLoading, setOpeningLoading] = useState(false);
  const [reopening, setReopening] = useState(false);
  const [reopenReason, setReopenReason] = useState("");
  const [lineSearch, setLineSearch] = useState("");
  const [lineSort, setLineSort] = useState<"date" | "-date" | "amount" | "-amount">("date");
  // The tie-out AS IF the current selection were reconciled. Computed on the
  // server by the same tie-out the real reconcile uses — a second copy of that
  // formula in the browser is exactly the drift this codebase has paid for
  // before, so the round trip is the point rather than a compromise.
  const [projection, setProjection] = useState<ReconPreview | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<ReconHistory | null>(null);
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

  // Fetch the suggestion when the account changes, and prefill the field with
  // it. The CA can still overwrite it — this is a default, not a lock.
  useEffect(() => {
    if (!showNew || !form.bank_account_id || !clientId || clientId === "_placeholder") {
      setOpening(null);
      return;
    }
    let cancelled = false;
    setOpeningLoading(true);
    (async () => {
      try {
        const res = (await api.banking.reconciliations.openingSuggestion({
          client_id: clientId, bank_account_id: form.bank_account_id,
        })) as { success: boolean; data: OpeningSuggestion };
        if (cancelled || !res.success) return;
        setOpening(res.data);
        setForm((f) => ({ ...f, opening: (res.data.suggested_opening_paise / 100).toFixed(2) }));
      } catch {
        if (!cancelled) setOpening(null);   // non-blocking: the field stays manual
      } finally {
        if (!cancelled) setOpeningLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [showNew, form.bank_account_id, clientId]);

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

  // Debounced so ticking through a list is one request at the end of a burst,
  // not one per checkbox.
  // Derived here rather than from the `completed` / `selectedIds` consts below,
  // which are declared after the hooks.
  const selectionKey = Object.keys(sel).filter((k) => sel[k]).sort().join(",");
  const isCompleted = report?.reconciliation.status === "completed";
  useEffect(() => {
    if (!selectedId || isCompleted || view !== "unreconciled" || selectionKey === "") {
      setProjection(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const res = (await api.banking.reconciliations.preview(selectedId, selectionKey.split(","))) as
          { success: boolean; data: ReconPreview };
        if (!cancelled && res.success) setProjection(res.data);
      } catch {
        if (!cancelled) setProjection(null);   // non-blocking: the indicator just hides
      }
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [selectedId, isCompleted, view, selectionKey]);

  const loadHistory = useCallback(async () => {
    if (!selectedId) return;
    try {
      const res = (await api.banking.reconciliations.history(selectedId)) as
        { success: boolean; data: ReconHistory };
      if (res.success) setHistory(res.data);
    } catch { setHistory(null); }
  }, [selectedId]);
  useEffect(() => { if (showHistory) loadHistory(); }, [showHistory, loadHistory]);
  useEffect(() => { setShowHistory(false); setHistory(null); setLineSearch(""); }, [selectedId]);

  async function doReopen() {
    setBusy(true); setError(null);
    try {
      const res = (await api.banking.reconciliations.reopen(selectedId, reopenReason.trim())) as
        { success: boolean; error?: string | null };
      if (!res.success) { setError(res.error ?? "Could not reopen this reconciliation."); return; }
      setReopening(false); setReopenReason("");
      await refresh();
    } catch (e) {
      // A non-Partner gets a 403 here — surface it rather than failing silently.
      setError(e instanceof Error ? e.message : "Could not reopen this reconciliation.");
    } finally { setBusy(false); }
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
  const selectedIds = Object.keys(sel).filter((k) => sel[k]);

  // Filter / sort over the loaded lines. Pure presentation — matching text and
  // ordering rows is not accounting, so it stays in the browser. Every figure
  // shown still comes from the backend.
  const lines = (() => {
    const rows = report ? [...report[view]] : [];
    const q = lineSearch.trim().toLowerCase();
    const filtered = q
      ? rows.filter((t) =>
          (t.description || "").toLowerCase().includes(q) ||
          (t.reference_no || "").toLowerCase().includes(q) ||
          String(t.transaction_date).includes(q))
      : rows;
    const dir = lineSort.startsWith("-") ? -1 : 1;
    const key = lineSort.replace(/^-/, "");
    return filtered.sort((a, b) => {
      if (key === "amount") {
        const av = (a.credit_paise || 0) - (a.debit_paise || 0);
        const bv = (b.credit_paise || 0) - (b.debit_paise || 0);
        return (av - bv) * dir;
      }
      return String(a.transaction_date).localeCompare(String(b.transaction_date)) * dir;
    });
  })();
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

          {/* Where the opening balance came from, and whether the books agree. */}
          {openingLoading && <p className="text-[10px] text-[#94A3B8]">Looking up the previous reconciliation…</p>}
          {opening && !openingLoading && (
            <>
              <p className="text-[10px] text-[#94A3B8]">
                {opening.source === "previous_reconciliation" && opening.previous_reconciliation ? (
                  <>Carried forward from the reconciliation completed to {opening.previous_reconciliation.period_end} — closing {fmt(opening.suggested_opening_paise)}.</>
                ) : (
                  <>First reconciliation for this account — starting from its opening balance of {fmt(opening.suggested_opening_paise)}.</>
                )}
              </p>
              {!opening.matches && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
                  <p className="text-[11px] font-semibold text-amber-800">
                    Beginning balance doesn&apos;t match the books
                  </p>
                  <p className="text-[10px] text-amber-700 mt-1">
                    The last completed reconciliation closed at {fmt(opening.suggested_opening_paise)}, but the
                    books&apos; own record of everything reconciled so far comes to{" "}
                    {fmt(opening.reconciled_book_balance_paise)} — a difference of{" "}
                    <strong>{fmt(Math.abs(opening.mismatch_paise))}</strong>. Something changed after that
                    reconciliation was completed: a transaction un-reconciled, an adjustment altered, or a
                    posted journal reversed.
                  </p>
                  <p className="text-[10px] text-amber-700 mt-1">
                    You can still open this period — but the difference will follow you into it, so it is
                    worth finding first.
                  </p>
                </div>
              )}
            </>
          )}

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
              <button onClick={() => api.banking.reconciliations.exportCsv(selectedId)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569] flex items-center gap-1.5"><Download size={12} /> CSV</button>
              {/* The document a CA actually hands to a client or an auditor.
                  For a completed session it renders the FROZEN snapshot. */}
              <button onClick={() => api.banking.reconciliations.exportPdf(selectedId)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569] flex items-center gap-1.5"><FileText size={12} /> PDF</button>
              <button onClick={() => setShowHistory((v) => !v)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569]">
                {showHistory ? "Hide history" : "History"}
              </button>
              {!completed && (
                <button onClick={() => act(() => api.banking.reconciliations.complete(selectedId))} disabled={busy || !report.ties_out} title={report.ties_out ? "" : "Reconcile until the statement ties out"} className="text-xs px-4 py-1.5 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed ml-auto">Complete Reconciliation</button>
              )}
              {completed && (
                <>
                  <span className="text-[11px] text-green-700 ml-auto flex items-center gap-1"><CheckCircle size={12} /> Completed {report.reconciliation.completed_at ? String(report.reconciliation.completed_at).slice(0, 10) : ""} · locked</span>
                  {/* The deliberate escape hatch. Partner-only server-side; a
                      non-Partner gets a 403 and the message says so. */}
                  <button onClick={() => setReopening(true)} disabled={busy}
                    className="text-[11px] px-2.5 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#64748B]">
                    Reopen…
                  </button>
                </>
              )}
            </div>

            {/* A period that has been reopened is a fact about the books, so it
                stays visible on the session rather than only in the audit log. */}
            {(report.reconciliation.reopen_count ?? 0) > 0 && (
              <p className="text-[10px] text-amber-700 bg-amber-50 border border-amber-100 rounded px-3 py-2">
                Reopened {report.reconciliation.reopen_count}
                {report.reconciliation.reopen_count === 1 ? " time" : " times"}
                {report.reconciliation.reopened_at ? ` · last on ${String(report.reconciliation.reopened_at).slice(0, 10)}` : ""}
                {report.reconciliation.reopen_reason ? ` — “${report.reconciliation.reopen_reason}”` : ""}
              </p>
            )}
          </div>

          {reopening && (
            <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
              <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
                <div className="px-5 py-4 border-b border-[#F1F5F9]">
                  <h3 className="text-sm font-semibold text-[#0F172A]">Reopen this reconciliation</h3>
                  <p className="text-xs text-[#64748B] mt-0.5">
                    {report.reconciliation.statement_start_date} → {report.reconciliation.statement_end_date}
                  </p>
                </div>
                <div className="px-5 py-4 space-y-3">
                  <p className="text-[11px] text-[#475569]">
                    This undoes a completed period so it can be corrected. The report as it was
                    certified is kept, the change is recorded against your name, and the period must
                    tie out again before it can be completed. Reconciled transactions stay reconciled
                    — untick whatever was wrong after reopening.
                  </p>
                  <label className="block">
                    <span className="text-[11px] font-medium text-[#475569]">Reason *</span>
                    <textarea value={reopenReason} onChange={(e) => setReopenReason(e.target.value)} rows={3}
                      placeholder="e.g. April rent was reconciled into March by mistake"
                      className="mt-1 w-full px-2 py-1.5 text-xs border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500" />
                    <span className="text-[10px] text-[#94A3B8]">At least 10 characters — this goes into the audit trail.</span>
                  </label>
                  {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
                </div>
                <div className="flex gap-2 justify-end px-5 py-4 border-t border-[#F1F5F9]">
                  <button onClick={() => { setReopening(false); setReopenReason(""); setError(null); }}
                    className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
                  <button onClick={doReopen} disabled={busy || reopenReason.trim().length < 10}
                    className="text-xs px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-40">
                    {busy ? "Reopening…" : "Reopen"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Prior certifications (Tier 2.7). A session can be completed,
              reopened and completed again; only the newest snapshot lives on the
              session, the rest are preserved in reopen_history. */}
          {showHistory && (
            <div className="bg-white rounded-xl border border-[#F1F5F9] p-4 space-y-2">
              <p className="text-xs font-semibold text-[#334155]">Certification history</p>
              {!history ? (
                <p className="text-[11px] text-[#94A3B8]">Loading…</p>
              ) : !history.current && history.superseded.length === 0 ? (
                <p className="text-[11px] text-[#94A3B8]">
                  This reconciliation has never been completed, so there is nothing certified yet.
                </p>
              ) : (
                <div className="divide-y divide-[#F8FAFC]">
                  {history.current && (
                    <div className="py-2 flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-[11px] font-medium text-[#1E293B]">
                          Current certification
                          <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded-full bg-green-50 text-green-700">in force</span>
                        </p>
                        <p className="text-[10px] text-[#94A3B8] mt-0.5">
                          Completed {String(history.current.completed_at ?? "").slice(0, 10)}
                        </p>
                      </div>
                      <span className="text-[11px] font-mono shrink-0">
                        {history.current.summary ? fmt(history.current.summary.statement_closing_balance_paise) : "—"}
                      </span>
                    </div>
                  )}
                  {history.superseded.map((h, i) => (
                    <div key={i} className="py-2 flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-[11px] font-medium text-[#64748B]">
                          Superseded certification
                          <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded-full bg-[#F1F5F9] text-[#94A3B8]">replaced</span>
                        </p>
                        <p className="text-[10px] text-[#94A3B8] mt-0.5">
                          Completed {String(h.completed_at ?? "").slice(0, 10)} · reopened{" "}
                          {String(h.superseded_at ?? "").slice(0, 10)}
                          {h.reason ? ` — “${h.reason}”` : ""}
                        </p>
                      </div>
                      <span className="text-[11px] font-mono text-[#64748B] shrink-0">
                        {h.summary ? fmt(h.summary.statement_closing_balance_paise) : "—"}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Item buckets + find/sort. A long statement is unusable without
              them — hunting one ₹4,500 line in 300 rows is the actual work. */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex gap-1 bg-[#F1F5F9] p-1 rounded-lg w-fit">
              {([["unreconciled", "Unreconciled", report.counts.unreconciled], ["reconciled", "Reconciled", report.counts.reconciled], ["exceptions", "Exceptions", report.counts.exceptions]] as const).map(([id, label, n]) => (
                <button key={id} onClick={() => { setView(id); setSel({}); }} className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${view === id ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"}`}>{label} ({n})</button>
              ))}
            </div>
            <input
              value={lineSearch} onChange={(e) => setLineSearch(e.target.value)}
              placeholder="Find description, reference or date…"
              aria-label="Filter reconciliation lines"
              className="flex-1 min-w-[180px] px-2 py-1.5 text-xs border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500" />
            <select value={lineSort} onChange={(e) => setLineSort(e.target.value as typeof lineSort)}
              aria-label="Sort reconciliation lines"
              className="px-2 py-1.5 text-xs border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500">
              <option value="date">Date ↑</option>
              <option value="-date">Date ↓</option>
              <option value="amount">Amount ↑</option>
              <option value="-amount">Amount ↓</option>
            </select>
          </div>
          {lineSearch.trim() && (
            <p className="text-[10px] text-[#94A3B8]">
              Showing {lines.length} of {report[view].length} — filtering hides rows, it does not
              exclude them from the tie-out.
            </p>
          )}

          {!completed && view !== "exceptions" && selectedIds.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              {view === "unreconciled"
                ? <button onClick={() => act(() => api.banking.reconciliations.reconcile(selectedId, selectedIds))} disabled={busy} className="text-xs px-4 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">Reconcile {selectedIds.length} selected</button>
                : <button onClick={() => act(() => api.banking.reconciliations.unreconcile(selectedId, selectedIds))} disabled={busy} className="text-xs px-4 py-1.5 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569]">Unreconcile {selectedIds.length} selected</button>}

              {/* Live difference: what the tie-out becomes if you commit this
                  selection. Answers "am I nearly there?" before the commit,
                  instead of reconcile → look → unreconcile → try again. */}
              {projection && (
                <span className={`text-[11px] px-2.5 py-1 rounded-lg border font-mono ${
                  projection.would_tie_out
                    ? "bg-green-50 border-green-200 text-green-800"
                    : "bg-[#F8FAFC] border-[#E2E8F0] text-[#475569]"}`}>
                  {projection.would_tie_out
                    ? "Ties out if reconciled ✓"
                    : <>Difference would be {fmt(Math.abs(projection.projected.difference_paise))}
                        <span className="text-[#94A3B8]"> (now {fmt(Math.abs(projection.current.difference_paise))})</span></>}
                </span>
              )}
              {projection && projection.ineligible_ids.length > 0 && (
                <span className="text-[10px] text-amber-700">
                  {projection.ineligible_ids.length} selected line(s) can&apos;t be reconciled here.
                </span>
              )}
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

// ── Bank rules (B.2.3) ─────────────────────────────────────────────────────
//
// A rule annotates the Categorize queue with a suggested category, counter GL
// account and narration. It NEVER posts and never writes to a transaction on
// its own — the CA accepts the suggestion. Precedence is creation order: the
// first rule that fires wins, so put the specific ones first.
//
// The engine and its endpoints shipped long before this screen; without a way
// to create a rule, bank_matching_rules could only ever be empty and the whole
// engine was dead code. See
// docs/audits/2026-08-02-bank-module-quickbooks-gap-audit.md §2.1.

interface BankRule {
  id: string;
  rule_name: string;
  description_pattern: string | null;
  amount_min_paise: number | null;
  amount_max_paise: number | null;
  txn_type: "debit" | "credit" | "any";
  suggested_category: string | null;
  suggested_account_id: string | null;
  suggested_narration: string | null;
  is_active: boolean;
}

const BLANK_RULE = {
  rule_name: "",
  description_pattern: "",
  amount_min: "",
  amount_max: "",
  txn_type: "any" as "debit" | "credit" | "any",
  suggested_category: "",
  suggested_account_id: "",
  suggested_narration: "",
};

function BankRules({ clientId, accounts }: { clientId: string; accounts: Account[] }) {
  const [rules, setRules] = useState<BankRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [form, setForm] = useState({ ...BLANK_RULE });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    try {
      const res = (await api.banking.rules.list(clientId)) as { success: boolean; data: BankRule[] };
      if (!res.success) throw new Error("Couldn't load matching rules.");
      setRules(res.data ?? []);
      setLoadError(null);
    } catch (e) {
      setRules([]);
      setLoadError(e instanceof Error ? e.message : "Couldn't load matching rules.");
    } finally {
      setLoading(false);
    }
  }, [clientId]);
  useEffect(() => { load(); }, [load]);

  const accountName = (id: string | null) => {
    if (!id) return null;
    const a = accounts.find((x) => x.id === id);
    return a ? `${a.account_code} · ${a.account_name}` : "Unknown account";
  };

  function startNew() {
    setForm({ ...BLANK_RULE });
    setFormError(null);
    setEditing("new");
  }
  function startEdit(r: BankRule) {
    setForm({
      rule_name: r.rule_name,
      description_pattern: r.description_pattern ?? "",
      amount_min: r.amount_min_paise != null ? (r.amount_min_paise / 100).toFixed(2) : "",
      amount_max: r.amount_max_paise != null ? (r.amount_max_paise / 100).toFixed(2) : "",
      txn_type: r.txn_type ?? "any",
      suggested_category: r.suggested_category ?? "",
      suggested_account_id: r.suggested_account_id ?? "",
      suggested_narration: r.suggested_narration ?? "",
    });
    setFormError(null);
    setEditing(r.id);
  }

  // Empty string means "no bound", which is not the same as zero.
  const boundToPaise = (v: string) => (v.trim() === "" ? null : rsToP(parseFloat(v) || 0));

  async function save() {
    const payload = {
      rule_name: form.rule_name.trim(),
      description_pattern: form.description_pattern.trim() || null,
      amount_min_paise: boundToPaise(form.amount_min),
      amount_max_paise: boundToPaise(form.amount_max),
      txn_type: form.txn_type,
      suggested_category: form.suggested_category || null,
      suggested_account_id: form.suggested_account_id || null,
      suggested_narration: form.suggested_narration.trim() || null,
    };
    // The backend re-validates all of this; these checks just avoid a round trip
    // to say what the form already knows.
    if (!payload.rule_name) { setFormError("Give the rule a name."); return; }
    const hasCondition = payload.description_pattern || payload.amount_min_paise != null
      || payload.amount_max_paise != null || payload.txn_type !== "any";
    if (!hasCondition) {
      setFormError("Add at least one condition — a description pattern, an amount range, or money-in/money-out. A rule with no conditions would match every transaction.");
      return;
    }
    if (!payload.suggested_category && !payload.suggested_account_id && !payload.suggested_narration) {
      setFormError("Add at least one suggestion — a category, an account, or a narration.");
      return;
    }
    setSaving(true); setFormError(null);
    try {
      if (editing === "new") await api.banking.rules.create({ client_id: clientId, ...payload });
      else if (editing) await api.banking.rules.update(editing, payload);
      setEditing(null);
      await load();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Couldn't save the rule.");
    } finally {
      setSaving(false);
    }
  }

  async function toggle(r: BankRule) {
    setBusy((b) => ({ ...b, [r.id]: true }));
    try { await api.banking.rules.update(r.id, { is_active: !r.is_active }); await load(); }
    catch (e) { alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy((b) => ({ ...b, [r.id]: false })); }
  }
  async function remove(r: BankRule) {
    if (!confirm(`Delete the rule “${r.rule_name}”? Transactions it has already been applied to are unaffected.`)) return;
    setBusy((b) => ({ ...b, [r.id]: true }));
    try { await api.banking.rules.remove(r.id); await load(); }
    catch (e) { alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy((b) => ({ ...b, [r.id]: false })); }
  }

  function conditionSummary(r: BankRule) {
    const bits: string[] = [];
    if (r.description_pattern) bits.push(`narration contains “${r.description_pattern}”`);
    if (r.amount_min_paise != null && r.amount_max_paise != null) bits.push(`${fmt(r.amount_min_paise)}–${fmt(r.amount_max_paise)}`);
    else if (r.amount_min_paise != null) bits.push(`≥ ${fmt(r.amount_min_paise)}`);
    else if (r.amount_max_paise != null) bits.push(`≤ ${fmt(r.amount_max_paise)}`);
    if (r.txn_type === "debit") bits.push("money out");
    if (r.txn_type === "credit") bits.push("money in");
    return bits.join(" · ") || "every transaction";
  }

  return (
    <div className="space-y-4 max-w-3xl mx-auto">
      <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-3">
        <p className="text-xs font-semibold text-blue-800">How rules work</p>
        <p className="text-[11px] text-blue-600 mt-1">
          A rule watches for transactions that match its conditions and suggests how to
          code them in <strong>Categorize</strong>. It never posts anything and never
          changes a transaction on its own — you still accept each suggestion. When two
          rules match, the <strong>older one wins</strong>, so create your specific rules
          before the broad ones.
        </p>
      </div>

      <div className="flex items-center justify-between">
        <p className="text-xs text-[#64748B]">
          {loading ? "Loading…" : `${rules.length} rule${rules.length === 1 ? "" : "s"}`}
        </p>
        <button onClick={startNew} className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-1.5">
          <Plus size={12} /> New rule
        </button>
      </div>

      {editing && (
        <div className="bg-white rounded-xl border border-[#E2E8F0] p-4 space-y-3">
          <p className="text-xs font-semibold text-[#334155]">{editing === "new" ? "New rule" : "Edit rule"}</p>

          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Rule name *</label>
            <input value={form.rule_name} onChange={(e) => setForm((f) => ({ ...f, rule_name: e.target.value }))}
              className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="e.g. HDFC bank charges" />
          </div>

          <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8] pt-1">When</p>
          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Narration contains</label>
            <input value={form.description_pattern} onChange={(e) => setForm((f) => ({ ...f, description_pattern: e.target.value }))}
              className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="e.g. BANK CHARGES" />
            <p className="text-[10px] text-[#94A3B8] mt-1">Plain text, not case-sensitive. No wildcards.</p>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Min amount (₹)</label>
              <input type="number" min="0" step="0.01" value={form.amount_min}
                onChange={(e) => setForm((f) => ({ ...f, amount_min: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm font-mono" placeholder="any" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Max amount (₹)</label>
              <input type="number" min="0" step="0.01" value={form.amount_max}
                onChange={(e) => setForm((f) => ({ ...f, amount_max: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm font-mono" placeholder="any" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Direction</label>
              <select value={form.txn_type} onChange={(e) => setForm((f) => ({ ...f, txn_type: e.target.value as "debit" | "credit" | "any" }))}
                className="w-full border rounded-lg px-3 py-2 text-sm">
                <option value="any">Either</option>
                <option value="credit">Money in</option>
                <option value="debit">Money out</option>
              </select>
            </div>
          </div>

          <p className="text-[10px] font-semibold uppercase tracking-wide text-[#94A3B8] pt-1">Suggest</p>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Category</label>
              <select value={form.suggested_category} onChange={(e) => setForm((f) => ({ ...f, suggested_category: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm">
                <option value="">— None —</option>
                {BANK_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Counter account</label>
              <AccountLookup accounts={accounts} value={form.suggested_account_id}
                onChange={(v) => setForm((f) => ({ ...f, suggested_account_id: v }))}
                ariaLabel="Suggested counter account" placeholder="— None —" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Narration</label>
            <input value={form.suggested_narration} onChange={(e) => setForm((f) => ({ ...f, suggested_narration: e.target.value }))}
              className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="e.g. Bank charges" />
          </div>

          {formError && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{formError}</p>}

          <div className="flex gap-2 justify-end pt-1">
            <button onClick={() => setEditing(null)} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
            <button onClick={save} disabled={saving} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
              {saving ? "Saving…" : editing === "new" ? "Create rule" : "Save changes"}
            </button>
          </div>
        </div>
      )}

      {loading ? <TableSkeleton cols={3} rows={3} /> : loadError ? (
        <div className="bg-white rounded-xl border border-red-200 p-10 text-center">
          <p className="text-sm text-red-600 font-medium mb-2">{loadError}</p>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      ) : rules.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-10 text-center">
          <p className="text-sm text-[#94A3B8]">No rules yet.</p>
          <p className="text-[11px] text-[#94A3B8] mt-1">
            Rules save you re-coding the same transaction every month — bank charges, salary
            transfers, a recurring vendor.
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden divide-y divide-[#F8FAFC]">
          {rules.map((r, i) => (
            <div key={r.id} className={`px-4 py-3 flex items-start gap-3 ${r.is_active ? "" : "bg-[#FCFCFD]"}`}>
              <span className="text-[10px] text-[#CBD5E1] font-mono mt-0.5 w-4 shrink-0">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className={`text-xs font-medium truncate ${r.is_active ? "text-[#1E293B]" : "text-[#94A3B8]"}`}>{r.rule_name}</p>
                  {!r.is_active && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[#F1F5F9] text-[#94A3B8]">Off</span>}
                </div>
                <p className="text-[10px] text-[#94A3B8] mt-0.5">When {conditionSummary(r)}</p>
                <p className="text-[10px] text-[#64748B] mt-0.5">
                  Suggest{" "}
                  {[r.suggested_category, accountName(r.suggested_account_id), r.suggested_narration]
                    .filter(Boolean).join(" · ")}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button onClick={() => toggle(r)} disabled={busy[r.id]} className="text-[10px] px-2 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569]">
                  {r.is_active ? "Turn off" : "Turn on"}
                </button>
                <button onClick={() => startEdit(r)} disabled={busy[r.id]} className="text-[#94A3B8] hover:text-[#475569]" aria-label={`Edit ${r.rule_name}`}>
                  <Pencil size={13} />
                </button>
                <button onClick={() => remove(r)} disabled={busy[r.id]} className="text-[#94A3B8] hover:text-red-600" aria-label={`Delete ${r.rule_name}`}>
                  <X size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
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
        {tab === "rules"      && <BankRules clientId={clientId} accounts={accounts} />}
      </div>
    </div>
  );
}
