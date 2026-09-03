"use client";
// Reconcile (BRS) tab — sessions, manual reconcile, tie-out, report
//
// Moved verbatim out of app/clients/[id]/bank/page.tsx on 2026-09-03, when
// the bank module was rebuilt around ENTRIES (docs/architecture/09-bank-entries.md).
// The 4,964-line page was the reason small changes went unreviewed; each tab
// is its own file now. Behaviour here is unchanged by the move.

import { useEffect, useState, useCallback } from "react";
import { CheckCircle, FileText, Download } from "lucide-react";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { api } from "@/lib/api";
import { StatementSkeleton } from "@/components/ui/skeleton";

import { fmt } from "@/components/banking/shared";

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

/**
 * A reconciliation figure as typed → integer paise, or null if it is not an
 * amount. The callers below refuse rather than submit a null.
 *
 * This was `Math.round(parseFloat(s || "0") * 100)`, and a bank reconciliation
 * is the one screen where a silently coerced number is guaranteed not to be
 * noticed: the whole point is that the statement and the ledger agree, so an
 * opening balance read as ₹1 instead of ₹1,25,000 presents as a difference to
 * chase rather than as a typo to correct.
 */
const toPaise = (s: string): number | null => paiseFromRupeeInput(s || "0");

/** The message shown when one of them is not an amount. One wording, because
 *  all three fields are the same kind of mistake. */
const NOT_AN_AMOUNT = "Enter the amount in rupees, e.g. 125000 or 125000.50 — without commas.";

export function BankReconciliation({ clientId }: { clientId: string }) {
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
    const opening = toPaise(form.opening);
    const closing = toPaise(form.closing);
    if (opening === null || closing === null) { setError(NOT_AN_AMOUNT); return; }
    setBusy(true);
    try {
      const res = (await api.banking.reconciliations.create({
        client_id: clientId, bank_account_id: form.bank_account_id,
        statement_start_date: form.start, statement_end_date: form.end,
        opening_balance_paise: opening, closing_balance_paise: closing,
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
                <button
                  onClick={() => {
                    const paise = toPaise(adj);
                    if (paise === null) { setError(NOT_AN_AMOUNT); return; }
                    act(() => api.banking.reconciliations.update(selectedId, { adjustments_paise: paise }));
                  }}
                  disabled={busy}
                  className="text-[11px] px-2 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569]"
                >Apply</button>
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

