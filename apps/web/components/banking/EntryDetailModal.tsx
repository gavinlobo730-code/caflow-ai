"use client";
/**
 * One entry, opened. Everything a line can be asked lives here; the row asks
 * nothing (docs/architecture/09-bank-entries.md).
 *
 * TOP: what this line is about to become — the draft with its reason, or the
 * CA's own coding — and the Pass button. Then the answers a CA can give,
 * largest first: the ledger, the document, a split, a transfer, the payee,
 * and the history evidence. Last: what the bank actually sent.
 *
 * Every control calls an endpoint that already existed; this modal adds no
 * second way to do anything. The live candidates, history and transfer
 * counterpart come from GET /entries/{id} — fetched for the ONE line that is
 * open, not for every row on the page.
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Search, Split, X } from "lucide-react";
import { api } from "@/lib/api";
import { AccountLookup } from "@/components/lookups/AccountLookup";
import { SplitAcrossLedgersModal } from "@/components/banking/SplitAcrossLedgersModal";
import { MultiInvoiceMatchModal, type SettlePrefill } from "@/components/banking/SettleDocumentsModal";
import { FindMatchModal, type CandidateResult } from "@/components/banking/FindMatchModal";
import { useToast } from "@/components/ui/use-toast";
import {
  type Account, type QueueTxn, type MatchSuggestion, fmt, gstWhy, GST_WHY_LONG, GST_RATE_OPTIONS,
} from "@/components/banking/shared";
import type { Entry } from "@/components/banking/EntriesTab";

interface EntryDetail extends Entry {
  suggestions: MatchSuggestion[];
  history: {
    account_id: string | null; category: string | null; times_seen: number; total_seen: number;
    is_unanimous: boolean; summary: string;
    alternatives: { account_id: string | null; category: string | null; times: number }[];
  } | null;
  suggested_payee: { payee_name: string; payee_type: "customer" | "vendor" | "other"; payee_id: string | null;
                     source: "matched_party" | "narration" } | null;
  transfer_candidate: { primary_id: string; counterpart_id: string; amount_paise: number;
                        confidence: "high" | "medium" | "low"; is_unambiguous: boolean; summary: string } | null;
}

const KIND_LABEL = { receipt: "Receipt", payment: "Payment", contra: "Contra" } as const;

/** The legacy modals take the queue's row shape; an entry carries everything
 *  they read, under the same names, plus fields they never look at. */
function asQueueTxn(t: EntryDetail): QueueTxn {
  return {
    ...t,
    balance_paise: 0,
    suggested_category: t.draft_category, needs_review: false,
    suggested_account_id: t.draft_account_id, suggested_narration: null, suggested_by_rule: null,
    suggested_gst_rate_bps: t.draft_gst_rate_bps, suggested_is_interstate: t.draft_is_interstate,
    suggestions: t.suggestions, history: t.history, suggested_payee: t.suggested_payee,
    is_split: t.is_split ?? t.has_splits,
  } as unknown as QueueTxn;
}

export function EntryDetailModal({ clientId, txnId, accounts, onClose, onChanged }: {
  clientId: string; txnId: string; accounts: Account[];
  onClose: () => void; onChanged: () => Promise<void> | void;
}) {
  const { toast } = useToast();
  const [t, setT] = useState<EntryDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [gstRate, setGstRate] = useState<string>("");
  const [interstate, setInterstate] = useState(false);
  const [splitMode, setSplitMode] = useState<"ledgers" | "documents" | null>(null);
  const [prefill, setPrefill] = useState<SettlePrefill | null>(null);
  const [finding, setFinding] = useState(false);

  const accountName = (id: string | null | undefined) => {
    if (!id) return "";
    const a = accounts.find((x) => x.id === id);
    return a ? a.account_name : "Unknown ledger";
  };

  const load = useCallback(async () => {
    try {
      const res = (await api.banking.entries.get(txnId)) as { success: boolean; data: EntryDetail };
      if (!res.success) throw new Error("Couldn't load this entry.");
      setT(res.data);
      setError(null);
      setGstRate(res.data.draft_gst_rate_bps != null ? String(res.data.draft_gst_rate_bps) : "");
      setInterstate(!!res.data.draft_is_interstate);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load this entry.");
    }
  }, [txnId]);

  useEffect(() => { load(); }, [load]);

  /** Every write: do it, reload this line, tell the list. Errors become a
   *  toast and the modal stays open so the CA can try something else. */
  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      await load();
      await onChanged();
      return true;
    } catch (e) {
      toast({ title: label, description: e instanceof Error ? e.message : String(e), variant: "destructive" });
      return false;
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <Shell onClose={onClose} title="Entry">
        <p className="text-sm text-red-600">{error}</p>
      </Shell>
    );
  }
  if (!t) {
    return <Shell onClose={onClose} title="Entry"><p className="text-xs text-[#94A3B8]">Loading…</p></Shell>;
  }

  const passed = t.entry_state === "passed";
  const aside = t.entry_state === "set_aside";
  const covered = t.entry_state === "covered";
  const editable = !passed && !aside && !covered;
  const amount = t.credit_paise > 0 ? t.credit_paise : t.debit_paise;
  const isSplit = t.is_split ?? t.has_splits;
  const coded = Boolean(t.account_id || t.matched_entity_id || isSplit || t.transfer_pair_id
    || ["Customer Payment", "Vendor Payment", "GST Payment"].includes(t.category ?? ""));
  const canPass = editable && (coded || (t.draft_source && !(t.draft_source === "document" && t.draft_grade !== "ready")));

  const summary = (): { text: string; sub: string | null } => {
    const kind = KIND_LABEL[t.kind];
    if (isSplit) return { text: `${kind} · split across ${t.split_count ?? t.splits?.length ?? "several"} ledgers`,
                          sub: (t.splits ?? []).map((s) => `${accountName(s.account_id)} ${fmt(s.amount_paise)}`).join(" · ") };
    if (t.transfer_pair_id) return { text: `Contra · ${t.transfer_is_primary ? "paying side — this one carries the journal" : "receiving side — passes with the paying side"}`, sub: null };
    if (t.matched_entity_id) return { text: `${kind} · against ${t.matched_entity_type?.replace("_", " ") ?? "a document"}`, sub: t.draft_source === "document" ? t.draft_label : null };
    if (t.account_id) return { text: `${kind} · ${accountName(t.account_id)}`, sub: t.category };
    if (t.category && ["Customer Payment", "Vendor Payment", "GST Payment"].includes(t.category)) return { text: `${kind} · ${t.category} (on account)`, sub: null };
    if (t.draft_source) return { text: `${kind} · ${t.draft_label ?? ""}`, sub: t.draft_reason };
    return { text: t.kind === "receipt" ? "From whom, or which ledger?" : t.kind === "payment" ? "To whom, or which ledger?" : "Which other account?", sub: null };
  };
  const s = summary();

  const splitModeSwitch = (
    <div className="inline-flex rounded-lg border border-[#E2E8F0] overflow-hidden" role="tablist" aria-label="What to split this line across">
      {([["ledgers", "Across ledgers"], ["documents", t.credit_paise > 0 ? "Across invoices" : "Across bills"]] as const).map(([mode, label]) => (
        <button key={mode} type="button" role="tab" aria-selected={splitMode === mode} onClick={() => setSplitMode(mode)}
          className={`text-xs px-3 py-1.5 font-medium ${splitMode === mode ? "bg-[#4338CA] text-white" : "bg-white text-[#475569] hover:bg-[#F8FAFC]"}`}>
          {label}
        </button>
      ))}
    </div>
  );

  /** A short match goes to the settlement modal with the party, the document
   *  and the shortfall already filled — linking it whole would under-settle
   *  the document by whatever the customer withheld. */
  const openSettle = (from?: MatchSuggestion | CandidateResult) => {
    setPrefill(from && from.party_id
      ? { partyId: from.party_id, docId: from.matched_entity_id, tdsPaise: from.difference_paise }
      : null);
    setSplitMode("documents");
  };

  async function pass() {
    const body = t!.gst_allowed && gstRate !== "" ? { gst_rate_bps: Number(gstRate), is_interstate: interstate } : undefined;
    const ok = await act("Not passed", () => api.banking.entries.pass(t!.id, body));
    if (ok) { toast({ title: `Passed as a ${KIND_LABEL[t!.kind]}` }); onClose(); }
  }

  return (
    <Shell onClose={onClose} title={t.parsed?.counterparty || t.description}
      note={<>{t.transaction_date} · <span className="font-mono">{fmt(amount)}</span> {t.credit_paise > 0 ? "received" : "spent"} · {KIND_LABEL[t.kind]}</>}
      footer={
        <>
          {editable && (
            <button onClick={() => act("Couldn't set aside", () => api.banking.ignoreTransaction(t.id)).then((ok) => ok && onClose())} disabled={busy}
              className="text-[11px] text-[#94A3B8] hover:text-[#64748B] hover:underline mr-auto disabled:opacity-50">Set aside</button>
          )}
          {aside && (
            <button onClick={() => act("Couldn't restore", () => api.banking.unignoreTransaction(t.id))} disabled={busy}
              className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg text-[#475569] hover:bg-[#F8FAFC] mr-auto">Restore</button>
          )}
          {passed && (
            <button onClick={() => act("Couldn't undo", () => api.banking.undoPost(t.id)).then((ok) => ok && onClose())} disabled={busy}
              className="text-xs px-3 py-1.5 border border-red-200 text-red-600 rounded-lg hover:bg-red-50 mr-auto">Undo</button>
          )}
          <button onClick={onClose} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569]">Close</button>
          {editable && (
            <button onClick={pass} disabled={busy || !canPass}
              title={canPass ? "Pass this entry into the books" : t.draft_source === "document" ? "Settle it from the document below" : "Choose a ledger or a document first"}
              className="text-xs px-4 py-1.5 rounded-lg font-medium text-white bg-[#059669] hover:bg-[#047857] disabled:opacity-40 disabled:cursor-not-allowed">
              {busy ? "…" : "Pass"}
            </button>
          )}
        </>
      }>

      {/* ── what it becomes ── */}
      <section className={`rounded-lg px-3 py-2.5 border ${t.draft_error ? "border-red-200 bg-red-50/50" : coded ? "border-emerald-200 bg-emerald-50/50" : t.draft_source ? "border-[#E2E8F0] bg-[#F8FAFC]" : "border-amber-200 bg-amber-50/50"}`}>
        <p className="text-[10px] uppercase tracking-wide text-[#94A3B8] mb-0.5">
          {passed ? "Passed" : aside ? "Set aside" : covered ? "Covered" : coded ? "Will pass as" : t.draft_source ? (t.draft_grade === "ready" ? "Proposed — ready" : "Proposed — your call") : "Needs you"}
          {t.posted_by_rule_id ? " · by a trusted rule" : ""}
        </p>
        <p className="text-sm font-medium text-[#0F172A]">{s.text}</p>
        {s.sub && <p className="text-[11px] text-[#64748B] mt-0.5">{s.sub}</p>}
        {t.draft_error && <p className="text-[11px] text-red-700 mt-1">Last pass refused: {t.draft_error}</p>}
      </section>

      {/* ── the ledger and GST ── */}
      {editable && !isSplit && !t.transfer_pair_id && (
        <section className="space-y-2">
          <div>
            <label className="block text-[11px] font-medium text-[#475569] mb-1">Book under</label>
            <AccountLookup accounts={accounts} value={t.account_id ?? ""} disabled={busy} ariaLabel="Ledger"
              placeholder={t.draft_account_id ? `Proposed: ${accountName(t.draft_account_id)}` : "Choose a ledger…"}
              onChange={(id) => id && act("Couldn't book under that ledger",
                () => api.banking.setTransactionAccount(t.id, { account_id: id, derive_category: true }))} />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-[#475569] mb-1">GST inside this amount</label>
            {t.gst_allowed ? (
              <div className="flex items-center gap-3 flex-wrap">
                <select value={gstRate} disabled={busy} onChange={(e) => setGstRate(e.target.value)}
                  aria-label={t.credit_paise > 0 ? "Output GST on this receipt" : "Input GST on this payment"}
                  className="px-2 py-1.5 text-xs border border-[#E2E8F0] rounded-lg bg-white">
                  <option value="">No GST split</option>
                  {GST_RATE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                {gstRate !== "" && gstRate !== "0" && (
                  <label className="flex items-center gap-1.5 text-xs text-[#475569]">
                    <input type="checkbox" disabled={busy} checked={interstate} onChange={(e) => setInterstate(e.target.checked)} className="h-3.5 w-3.5 rounded border-[#CBD5E1]" />
                    IGST (inter-state)
                  </label>
                )}
                <span className="text-[10px] text-[#94A3B8]">{t.credit_paise > 0 ? "Output tax owed — CGST Act s.9" : "Input credit claimed — CGST Act s.16"}</span>
              </div>
            ) : (
              <p className="text-[11px] text-[#94A3B8]">{GST_WHY_LONG[gstWhy(asQueueTxn(t))] ?? "Not available on this line."}</p>
            )}
          </div>
        </section>
      )}

      {/* ── the document ── */}
      {editable && !isSplit && !t.transfer_pair_id && (
        <section className="space-y-1.5">
          <p className="text-[11px] font-medium text-[#475569]">{t.credit_paise > 0 ? "Invoice" : "Bill"} this settles</p>
          {t.matched_entity_id ? (
            <div className="flex items-center gap-2">
              <p className="text-xs text-[#334155]">Linked to {t.matched_entity_type?.replace("_", " ")}.</p>
              <button onClick={() => act("Couldn't unlink", () => api.banking.unmatch(t.id))} disabled={busy}
                className="text-[11px] px-2.5 py-1 border border-red-200 text-red-600 rounded-lg hover:bg-red-50">Unlink</button>
            </div>
          ) : (
            <>
              {t.suggestions.length > 0 && (
                <ul className="divide-y divide-[#F1F5F9] border border-[#E2E8F0] rounded-lg overflow-hidden">
                  {t.suggestions.slice(0, 5).map((sg) => (
                    <li key={sg.matched_entity_id} className="flex items-center gap-2 px-3 py-1.5">
                      <div className="min-w-0 flex-1">
                        <p className="text-xs text-[#334155] truncate">{sg.label}</p>
                        <p className="text-[10px] text-[#94A3B8]">
                          {fmt(sg.amount_paise)} · {sg.reasons.join(", ")}
                          {sg.difference_paise > 0 && <span className="text-amber-700"> · short by {fmt(sg.difference_paise)}{sg.tds_rate_bps ? ` (TDS ${sg.tds_rate_bps / 100}%?)` : ""}</span>}
                        </p>
                      </div>
                      {sg.difference_paise > 0 ? (
                        <button onClick={() => openSettle(sg)} disabled={busy} className="text-[11px] px-2.5 py-1 border border-amber-200 bg-amber-50 text-amber-800 rounded-lg hover:bg-amber-100 shrink-0">Settle…</button>
                      ) : (
                        <button onClick={() => act("Couldn't link", () => api.banking.matchEntity(t.id, { matched_entity_type: sg.matched_entity_type, matched_entity_id: sg.matched_entity_id }))}
                          disabled={busy} className="text-[11px] px-2.5 py-1 border border-[#BBF7D0] bg-[#F0FDF4] text-[#15803D] rounded-lg hover:bg-[#DCFCE7] shrink-0">Link</button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex items-center gap-2 flex-wrap">
                <button onClick={() => setFinding(true)} disabled={busy}
                  className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 border border-[#CBD5E1] bg-white rounded-lg hover:bg-[#F1F5F9] text-[#334155] font-medium disabled:opacity-50">
                  <Search size={13} /> Find the {t.credit_paise > 0 ? "invoice" : "bill"}
                </button>
                <button onClick={() => setSplitMode("ledgers")} disabled={busy}
                  title={`Allocate this line across several ledgers, across several ${t.credit_paise > 0 ? "invoices" : "bills"}, or record TDS withheld on it`}
                  className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 border border-[#CBD5E1] bg-white rounded-lg hover:bg-[#F1F5F9] text-[#334155] font-medium disabled:opacity-50">
                  <Split size={13} /> Split across several
                </button>
              </div>
            </>
          )}
        </section>
      )}

      {/* ── a split already made ── */}
      {isSplit && (
        <section className="flex items-start gap-2 flex-wrap">
          <p className="text-[11px] text-[#64748B] min-w-0">Split across <span className="text-[#334155]">{(t.splits ?? []).map((sp) => `${accountName(sp.account_id)} ${fmt(sp.amount_paise)}`).join(" · ")}</span></p>
          {editable && <button onClick={() => setSplitMode("ledgers")} disabled={busy} className="text-[10px] px-2 py-0.5 border border-[#E2E8F0] rounded hover:bg-white text-[#475569] shrink-0">Edit the split</button>}
        </section>
      )}

      {/* ── transfer ── */}
      {editable && (t.transfer_pair_id || t.transfer_candidate) && (
        <section className="flex items-center gap-2 flex-wrap">
          {t.transfer_pair_id ? (
            <>
              <p className="text-[11px] text-[#64748B]">{t.transfer_is_primary ? "Paying side of a transfer — this one carries the journal." : "Receiving side of a transfer — the paying side carries the journal."}</p>
              <button onClick={() => act("Couldn't unpair", () => api.banking.unpairTransfer(t.id))} disabled={busy} className="text-[10px] px-2 py-0.5 border border-[#E2E8F0] rounded hover:bg-white text-[#475569]">Not a transfer</button>
            </>
          ) : t.transfer_candidate ? (
            <>
              <p className="text-[11px] text-[#64748B]">Looks like a transfer between own accounts: <span className="text-[#334155]">{t.transfer_candidate.summary}</span></p>
              <button onClick={() => act("Couldn't confirm the transfer", () => api.banking.pairTransfer(t.transfer_candidate!.primary_id, t.transfer_candidate!.counterpart_id))}
                disabled={busy} className="text-[11px] px-2.5 py-1 border border-[#C7D2FE] bg-[#EEF2FF] text-[#4338CA] rounded-lg hover:bg-[#E0E7FF]">Confirm transfer</button>
            </>
          ) : null}
        </section>
      )}

      {/* ── payee and history ── */}
      {editable && (
        <section className="space-y-1.5 border-l-2 border-[#E2E8F0] pl-3">
          {t.payee_name ? (
            <div className="flex items-center gap-2">
              <p className="text-[10px] text-[#94A3B8] min-w-0 truncate">Payee <span className="text-[#334155]">{t.payee_name}</span>{t.payee_type ? <span className="text-[#CBD5E1]"> ({t.payee_type})</span> : null}</p>
              <button onClick={() => act("Couldn't clear the payee", () => api.banking.setPayee(t.id, { payee_name: "" }))} disabled={busy} className="text-[10px] text-[#94A3B8] hover:text-red-600 hover:underline shrink-0">Clear payee</button>
            </div>
          ) : t.suggested_payee ? (
            <div className="flex items-center gap-2">
              <p className="text-[10px] text-[#94A3B8] min-w-0 truncate">Payee looks like <span className="text-[#334155] font-medium">{t.suggested_payee.payee_name}</span><span className="text-[#CBD5E1]"> ({t.suggested_payee.source === "narration" ? "from the narration" : "from the matched party"})</span></p>
              <button onClick={() => act("Couldn't confirm the payee", () => api.banking.setPayee(t.id, { payee_name: t.suggested_payee!.payee_name, payee_type: t.suggested_payee!.payee_type, payee_id: t.suggested_payee!.payee_id ?? undefined }))}
                disabled={busy} className="text-[10px] px-2 py-0.5 border border-[#E2E8F0] rounded hover:bg-white text-[#475569] shrink-0">Confirm payee</button>
            </div>
          ) : null}
          {t.history && !t.account_id && !isSplit && (
            <div className="flex items-center gap-2">
              <p className="text-[10px] text-[#94A3B8] min-w-0 truncate">
                <span className={t.history.is_unanimous ? "text-emerald-700" : "text-amber-700"}>{t.history.summary}</span>
                {t.history.account_id ? ` · ${accountName(t.history.account_id)}` : ""}
                {t.history.alternatives.length > 0 && <span className="text-[#CBD5E1]"> (also {t.history.alternatives.map((a) => `${accountName(a.account_id)} ×${a.times}`).join(", ")})</span>}
              </p>
              {t.history.account_id && (
                <button onClick={() => act("Couldn't apply", () => api.banking.setTransactionAccount(t.id, { account_id: t.history!.account_id!, derive_category: true }))}
                  disabled={busy} className="text-[10px] px-2 py-0.5 border border-[#BBF7D0] bg-[#F0FDF4] text-[#15803D] rounded hover:bg-[#DCFCE7] shrink-0">Book like last time</button>
              )}
            </div>
          )}
        </section>
      )}

      {/* ── what the bank sent ── */}
      <section>
        <p className="text-[10px] uppercase tracking-wide text-[#94A3B8] mb-0.5">Bank narration</p>
        <p className="text-[10px] text-[#475569] break-words select-text font-mono leading-relaxed">{t.description}</p>
        {(t.parsed?.utr || t.reference_no || t.parsed?.vpa || t.parsed?.ifsc) && (
          <p className="text-[10px] text-[#94A3B8] break-words select-text mt-0.5">
            {[t.parsed?.utr ? `UTR ${t.parsed.utr}` : null, t.reference_no && t.reference_no !== t.parsed?.utr ? t.reference_no : null, t.parsed?.vpa, t.parsed?.ifsc].filter(Boolean).join(" · ")}
          </p>
        )}
      </section>

      {splitMode === "ledgers" && (
        <SplitAcrossLedgersModal txnId={t.id} description={t.description} amountPaise={amount} isCredit={t.credit_paise > 0}
          accounts={accounts} modeSwitch={splitModeSwitch}
          onClose={() => { setSplitMode(null); setPrefill(null); }}
          onDone={async () => { setSplitMode(null); setPrefill(null); await load(); await onChanged(); }} />
      )}
      {splitMode === "documents" && (
        <MultiInvoiceMatchModal txn={asQueueTxn(t)} clientId={clientId} prefill={prefill} modeSwitch={splitModeSwitch}
          onClose={() => { setSplitMode(null); setPrefill(null); }}
          onDone={async () => { setSplitMode(null); setPrefill(null); await load(); await onChanged(); onClose(); }} />
      )}
      {finding && (
        <FindMatchModal txn={asQueueTxn(t)} onClose={() => setFinding(false)}
          onPicked={async (r) => {
            const ok = await act("Couldn't link this document", () => api.banking.matchEntity(t.id, { matched_entity_type: r.matched_entity_type, matched_entity_id: r.matched_entity_id }));
            if (ok) setFinding(false);
          }}
          onSettle={(r) => { setFinding(false); openSettle(r); }} />
      )}
    </Shell>
  );
}

function Shell({ title, note, footer, onClose, children }: {
  title: string; note?: ReactNode; footer?: ReactNode; onClose: () => void; children: ReactNode;
}) {
  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-xl max-h-[85vh] flex flex-col" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={title}>
        <div className="flex items-start justify-between px-5 py-4 border-b border-[#F1F5F9]">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-[#0F172A] truncate" title={title}>{title}</h3>
            {note && <p className="text-xs text-[#64748B] mt-0.5">{note}</p>}
          </div>
          <button onClick={onClose} aria-label="Close" className="text-[#94A3B8] hover:text-[#475569] shrink-0"><X size={16} /></button>
        </div>
        <div className="px-5 py-4 space-y-4 overflow-y-auto flex-1">{children}</div>
        {footer && <div className="px-5 py-3 border-t border-[#F1F5F9] flex items-center justify-end gap-2">{footer}</div>}
      </div>
    </div>
  );
}
