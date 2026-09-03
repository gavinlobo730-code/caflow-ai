"use client";
/**
 * Entries — the working list of the bank module.
 *
 * The design is docs/architecture/09-bank-entries.md. In one paragraph: a
 * statement line becomes a voucher (Receipt / Payment / Contra — decided by
 * direction, never chosen); the machine writes its best proposal ONTO the line
 * with a grade and a reason; the CA passes the ready ones in one click and
 * answers the rest. Nothing on this screen decides anything: the state is a
 * stored column the database maintains, the draft is a stored proposal, and
 * every verb is one endpoint.
 *
 * WHAT REPLACED WHAT
 *   For review / Categorized / Excluded  ->  one list, filtered by state, with
 *                                            counts: To do · Needs me ·
 *                                            Proposed · Ready · Passed · Set aside
 *   Apply suggestions                    ->  gone. Every line is always drafted;
 *                                            the draft is visible on the row.
 *   Set ledger / Record / Match / Add    ->  Pass (one verb), Book under… (the
 *                                            ledger), Answer (open the line)
 *
 * WHY THE LONG JOBS ARE LOOPS HERE
 *   Proposing for three thousand lines and passing three hundred are both too
 *   long for one request. The server does a chunk and says what remains; this
 *   screen keeps calling and shows the progress. No job table, no polling of
 *   a status — the loop IS the status.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle, Loader2, RotateCcw, Sparkles, Undo2 } from "lucide-react";
import { api, type EntryListState, type EntryState } from "@/lib/api";
import { DataTable } from "@/components/ui/data-table";
import type { BulkAction, Column } from "@/lib/table/types";
import { AccountLookup } from "@/components/lookups/AccountLookup";
import { commonNarrationPattern, MIN_PATTERN_LENGTH } from "@/lib/banking/narrationPattern";
import { useToast } from "@/components/ui/use-toast";
import { type Account, type BankAccount, fmt } from "@/components/banking/shared";
import { EntryDetailModal } from "@/components/banking/EntryDetailModal";

// ── the row, as the server sends it ─────────────────────────────────────────

export interface Entry {
  id: string; transaction_date: string; description: string; reference_no: string | null;
  debit_paise: number; credit_paise: number; match_status: string;
  category: string | null; account_id: string | null;
  matched_entity_type: string | null; matched_entity_id: string | null;
  posted_journal_id: string | null;
  transfer_pair_id: string | null; transfer_is_primary: boolean | null;
  payee_name: string | null; payee_type: string | null; payee_id: string | null;
  has_splits: boolean; is_split?: boolean; split_count?: number;
  splits?: { account_id: string; amount_paise: number; narration: string | null }[];
  /** Receipt / Payment / Contra — decided by the line, never chosen. */
  kind: "receipt" | "payment" | "contra";
  /** Maintained by the database. The browser never computes it. */
  entry_state: EntryState;
  draft_source: "rule" | "document" | "history" | "transfer" | null;
  draft_grade: "ready" | "proposed" | null;
  draft_label: string | null; draft_reason: string | null;
  draft_account_id: string | null; draft_category: string | null;
  draft_entity_type: string | null; draft_entity_id: string | null;
  draft_rule_id: string | null; draft_gst_rate_bps: number | null; draft_is_interstate: boolean;
  draft_error: string | null; drafted_at: string | null;
  posted_by_rule_id: string | null;
  gst_allowed?: boolean;
  parsed?: { channel: string | null; utr: string | null; vpa: string | null;
             counterparty: string | null; ifsc: string | null; summary: string } | null;
}

interface Counts {
  needs_you: number; proposed: number; ready: number; covered: number; passed: number;
  set_aside: number; to_do: number; undrafted: number; trusted_pending: number;
}

const ZERO: Counts = { needs_you: 0, proposed: 0, ready: 0, covered: 0, passed: 0,
                       set_aside: 0, to_do: 0, undrafted: 0, trusted_pending: 0 };

/** The chips, in the order a month is worked. Covered lines (the receiving
 *  side of a passed transfer) show only when there are any — they are nobody's
 *  work, and an always-present zero chip reads as a broken feature. */
const CHIPS: { id: EntryListState; label: string; key: keyof Counts; always: boolean }[] = [
  { id: "to_do",     label: "To do",     key: "to_do",     always: true },
  { id: "needs_you", label: "Needs me",  key: "needs_you", always: true },
  { id: "proposed",  label: "Proposed",  key: "proposed",  always: true },
  { id: "ready",     label: "Ready",     key: "ready",     always: true },
  { id: "passed",    label: "Passed",    key: "passed",    always: true },
  { id: "covered",   label: "Covered",   key: "covered",   always: false },
  { id: "set_aside", label: "Set aside", key: "set_aside", always: true },
];

const KIND_LABEL = { receipt: "Receipt", payment: "Payment", contra: "Contra" } as const;

const STATE_STYLE: Record<EntryState, string> = {
  needs_you: "bg-amber-50 text-amber-800 border-amber-200",
  proposed:  "bg-sky-50 text-sky-800 border-sky-200",
  ready:     "bg-emerald-50 text-emerald-800 border-emerald-200",
  covered:   "bg-slate-50 text-slate-600 border-slate-200",
  passed:    "bg-slate-100 text-slate-700 border-slate-200",
  set_aside: "bg-slate-50 text-slate-500 border-slate-200",
};
const STATE_LABEL: Record<EntryState, string> = {
  needs_you: "Needs you", proposed: "Proposed", ready: "Ready", covered: "Covered",
  passed: "Passed", set_aside: "Set aside",
};

const PER_PAGE = 50;
const PASS_CHUNK = 50;
const REDRAFT_CHUNK = 100;

type Progress = { label: string; done: number; total: number | null } | null;

export function EntriesTab({ clientId, accounts }: { clientId: string; accounts: Account[] }) {
  const { toast } = useToast();
  const [state, setState] = useState<EntryListState>("to_do");
  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([]);
  const [bankAccountId, setBankAccountId] = useState("");
  const [counts, setCounts] = useState<Counts>(ZERO);
  const [rows, setRows] = useState<Entry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(PER_PAGE);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [ledgerOrder, setLedgerOrder] = useState<string[]>([]);
  const [progress, setProgress] = useState<Progress>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [bookUnder, setBookUnder] = useState<Entry[] | null>(null);
  const [bookAccountId, setBookAccountId] = useState("");
  const [bookBusy, setBookBusy] = useState(false);
  const [rulePrompt, setRulePrompt] = useState<{ pattern: string; accountId: string } | null>(null);
  const [ruleSaving, setRuleSaving] = useState(false);
  const busyRef = useRef(false);

  const accountName = useCallback((id: string | null | undefined) => {
    if (!id) return "";
    const a = accounts.find((x) => x.id === id);
    return a ? a.account_name : "Unknown ledger";
  }, [accounts]);

  /** The chart ordered by what THIS client actually codes to, most used first
   *  — the server's ledger_order, applied to the picker. Orders, never filters. */
  const orderedAccounts = useMemo(() => {
    if (ledgerOrder.length === 0) return accounts;
    const rank = new Map(ledgerOrder.map((id, i) => [id, i]));
    return [...accounts].sort((a, b) =>
      (rank.get(a.id) ?? Number.MAX_SAFE_INTEGER) - (rank.get(b.id) ?? Number.MAX_SAFE_INTEGER));
  }, [accounts, ledgerOrder]);

  const acct = bankAccountId ? { bank_account_id: bankAccountId } : {};

  const loadCounts = useCallback(async () => {
    const res = (await api.banking.entries.counts({ client_id: clientId, ...acct })) as
      { success: boolean; data: Counts };
    if (res.success) setCounts(res.data);
    return res.data;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId, bankAccountId]);

  const loadRows = useCallback(async () => {
    setLoading(true);
    try {
      const res = (await api.banking.entries.list({
        client_id: clientId, state, limit: String(pageSize), offset: String(page * pageSize),
        ...(search ? { q: search } : {}), ...acct,
      })) as { success: boolean; data: { rows: Entry[]; total: number; ledger_order: string[] } };
      if (!res.success) throw new Error("Couldn't load the entries.");
      setRows(res.data.rows ?? []);
      setTotal(res.data.total ?? 0);
      setLedgerOrder(res.data.ledger_order ?? []);
      setLoadError(null);
    } catch (e) {
      setRows([]); setTotal(0);
      setLoadError(e instanceof Error ? e.message : "Couldn't load the entries.");
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId, state, page, pageSize, search, bankAccountId]);

  const reload = useCallback(async () => { await Promise.all([loadCounts(), loadRows()]); }, [loadCounts, loadRows]);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    (api.banking.listBankAccounts({ client_id: clientId }) as Promise<{ success: boolean; data: BankAccount[] }>)
      .then((r) => setBankAccounts(r.success ? (r.data ?? []) : []))
      .catch(() => setBankAccounts([]));
  }, [clientId]);

  useEffect(() => { if (clientId && clientId !== "_placeholder") loadRows(); }, [loadRows, clientId]);

  /** Propose for every undrafted line, then pass what the trusted rules
   *  drafted — both in chunks with progress. Runs on open and after an
   *  import, and never twice at once. */
  const settle = useCallback(async () => {
    if (busyRef.current || !clientId || clientId === "_placeholder") return;
    busyRef.current = true;
    try {
      let c = await loadCounts();
      if (c.undrafted > 0) {
        let done = 0; const totalToDo = c.undrafted;
        setProgress({ label: "Proposing entries", done, total: totalToDo });
        for (let i = 0; i < 200; i++) {
          const r = (await api.banking.entries.redraft({ client_id: clientId, limit: REDRAFT_CHUNK })) as
            { data: { drafted: number; remaining: number } };
          done += r.data.drafted;
          setProgress({ label: "Proposing entries", done, total: totalToDo });
          if (r.data.drafted === 0 || r.data.remaining === 0) break;
        }
        c = await loadCounts();
      }
      if (c.trusted_pending > 0) {
        const n = await passLoop({ only_trusted: true, label: "Passing trusted-rule entries", total: c.trusted_pending });
        if (n.passed > 0) toast({ title: `${n.passed} passed by trusted rules`,
                                 description: n.failed ? `${n.failed} refused — the reason is on each line.` : undefined });
      }
    } catch (e) {
      toast({ title: "Couldn't finish proposing", description: e instanceof Error ? e.message : String(e), variant: "destructive" });
    } finally {
      setProgress(null);
      busyRef.current = false;
      await reload();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId, loadCounts, reload]);

  useEffect(() => { settle(); }, [settle]);

  async function passLoop(opts: { only_trusted?: boolean; transaction_ids?: string[]; label: string; total: number | null }) {
    let passed = 0, failed = 0, skipped = 0;
    setProgress({ label: opts.label, done: 0, total: opts.total });
    for (let i = 0; i < 400; i++) {
      const r = (await api.banking.entries.passReady({
        client_id: clientId, limit: PASS_CHUNK, only_trusted: opts.only_trusted,
        transaction_ids: opts.transaction_ids, ...acct,
      })) as { data: { passed: number; failed: number; skipped: number; remaining: number } };
      passed += r.data.passed; failed += r.data.failed; skipped += r.data.skipped;
      setProgress({ label: opts.label, done: passed + failed + skipped, total: opts.total });
      if (r.data.remaining === 0 || (r.data.passed + r.data.failed + r.data.skipped) === 0) break;
    }
    return { passed, failed, skipped };
  }

  async function passAllReady() {
    if (busyRef.current) return;
    busyRef.current = true;
    try {
      const n = await passLoop({ label: "Passing ready entries", total: counts.ready });
      toast({
        title: `${n.passed} passed`,
        description: n.failed ? `${n.failed} refused — each says why on its line, under Needs me.` : "All ready entries are in the books.",
        variant: n.failed ? "destructive" : undefined,
      });
    } catch (e) {
      toast({ title: "Pass stopped", description: e instanceof Error ? e.message : String(e), variant: "destructive" });
    } finally {
      setProgress(null); busyRef.current = false; await reload();
    }
  }

  /** Pass ONE line from its row. A proposed draft may be passed this way —
   *  the click is the CA accepting it. A refusal is a toast, and the row
   *  carries it. */
  async function passOne(t: Entry) {
    try {
      await api.banking.entries.pass(t.id);
      toast({ title: `Passed as a ${KIND_LABEL[t.kind]}` });
    } catch (e) {
      toast({ title: "Not passed", description: e instanceof Error ? e.message : String(e), variant: "destructive" });
    }
    await reload();
  }

  async function undoOne(t: Entry) {
    try {
      await api.banking.undoPost(t.id);
      toast({ title: "Undone", description: "The journal is reversed and the line is back to do." });
    } catch (e) {
      toast({ title: "Couldn't undo", description: e instanceof Error ? e.message : String(e), variant: "destructive" });
    }
    await reload();
  }

  async function restoreOne(t: Entry) {
    try { await api.banking.unignoreTransaction(t.id); }
    catch (e) { toast({ title: "Couldn't restore", description: e instanceof Error ? e.message : String(e), variant: "destructive" }); }
    await reload();
  }

  // ── the entry column: what this line IS or is about to become ─────────────

  function entryText(t: Entry): { main: string; sub: string | null; tone: "solid" | "draft" | "ask" | "error" } {
    const kind = KIND_LABEL[t.kind];
    if (t.entry_state === "set_aside") return { main: `${kind} · set aside`, sub: null, tone: "draft" };
    if (t.entry_state === "covered") return { main: `${kind} · with its paying side`, sub: null, tone: "draft" };
    // What the CA coded — or what was passed — outranks any proposal.
    if (t.is_split || t.has_splits) {
      const legs = (t.splits ?? []).map((s) => `${accountName(s.account_id)} ${fmt(s.amount_paise)}`).join(" · ");
      return { main: `${kind} · split across ${t.split_count ?? t.splits?.length ?? "several"} ledgers`, sub: legs || null, tone: "solid" };
    }
    if (t.transfer_pair_id) return { main: `Contra · ${t.transfer_is_primary ? "to" : "from"} own account`, sub: null, tone: "solid" };
    if (t.matched_entity_id) {
      const doc = t.matched_entity_type === "sales_invoice" ? "against an invoice"
        : t.matched_entity_type === "purchase_bill" ? "against a bill"
        : `against a ${(t.matched_entity_type ?? "document").replace("_", " ")}`;
      return { main: `${kind} · ${t.draft_label && t.draft_source === "document" ? t.draft_label : doc}`, sub: null, tone: "solid" };
    }
    if (t.account_id) return { main: `${kind} · ${accountName(t.account_id)}`, sub: t.category && t.category !== "Other" ? t.category : null, tone: "solid" };
    if (t.category && ["Customer Payment", "Vendor Payment", "GST Payment"].includes(t.category)) {
      return { main: `${kind} · ${t.category}`, sub: "on account", tone: "solid" };
    }
    if (t.draft_error) return { main: t.draft_error, sub: t.draft_label ? `proposed: ${t.draft_label}` : null, tone: "error" };
    if (t.draft_source) {
      const gst = t.draft_gst_rate_bps ? ` · ${t.draft_is_interstate ? "IGST" : "GST"} ${t.draft_gst_rate_bps / 100}%` : "";
      return { main: `${kind} · ${t.draft_label ?? ""}${gst}`, sub: t.draft_reason, tone: t.draft_grade === "ready" ? "draft" : "ask" };
    }
    return { main: t.kind === "receipt" ? "From whom, or which ledger?" : t.kind === "payment" ? "To whom, or which ledger?" : "Which other account?", sub: null, tone: "ask" };
  }

  const columns: Column<Entry>[] = [
    {
      key: "transaction_date", header: "Date", width: "6.5rem", sortable: true, hideable: false,
      accessor: (t) => t.transaction_date,
      render: (t) => <span className="text-[#64748B] whitespace-nowrap tabular-nums">{t.transaction_date}</span>,
    },
    {
      key: "description", header: "Bank narration", sortable: true, searchable: true, hideable: false,
      accessor: (t) => t.parsed?.counterparty || t.description,
      render: (t) => (
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="truncate text-[#1E293B]" title={[t.description, t.parsed?.utr ? `UTR ${t.parsed.utr}` : null].filter(Boolean).join("\n")}>
            {t.parsed?.counterparty || t.description}
          </span>
          {t.parsed?.channel && (
            <span className="shrink-0 text-[9px] px-1 py-0.5 rounded bg-[#F1F5F9] text-[#64748B]">{t.parsed.channel}</span>
          )}
        </div>
      ),
    },
    {
      // THE column the old screen lacked: what this line is, or is about to
      // become. Solid for an answer, grey for a ready proposal, amber for a
      // question, red for a refusal. The reason sits under it.
      key: "entry", header: "Entry", sortable: false, hideable: false,
      accessor: (t) => entryText(t).main,
      render: (t) => {
        const e = entryText(t);
        const cls = e.tone === "solid" ? "text-[#0F172A] font-medium"
          : e.tone === "draft" ? "text-[#334155]"
          : e.tone === "ask" ? "text-amber-800"
          : "text-red-700";
        return (
          <div className="min-w-0">
            <p className={`truncate text-xs ${cls}`} title={e.main}>{e.main}</p>
            {e.sub && <p className="truncate text-[10px] text-[#94A3B8]" title={e.sub}>{e.sub}</p>}
          </div>
        );
      },
    },
    {
      key: "spent", header: "Spent", width: "7.5rem", align: "right", sortable: true,
      accessor: (t) => t.debit_paise, exportValue: (t) => t.debit_paise / 100,
      render: (t) => <span className="font-mono text-red-700">{t.debit_paise > 0 ? fmt(t.debit_paise) : ""}</span>,
    },
    {
      key: "received", header: "Received", width: "7.5rem", align: "right", sortable: true,
      accessor: (t) => t.credit_paise, exportValue: (t) => t.credit_paise / 100,
      render: (t) => <span className="font-mono text-green-700">{t.credit_paise > 0 ? fmt(t.credit_paise) : ""}</span>,
    },
    {
      key: "state", header: "Status", width: "6.5rem", sortable: true,
      accessor: (t) => STATE_LABEL[t.entry_state],
      render: (t) => (
        <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded border ${STATE_STYLE[t.entry_state]}`}
          title={t.posted_by_rule_id ? "Passed by a trusted rule" : undefined}>
          {STATE_LABEL[t.entry_state]}{t.posted_by_rule_id ? " · rule" : ""}
        </span>
      ),
    },
  ];

  /** ONE control per row, in the last cell. Pass on a line that can be
   *  passed; Answer opens the line when it cannot; Undo and Restore on the
   *  lines that are done or set aside. */
  const actionCell = (t: Entry) => {
    const stop = (e: React.MouseEvent) => e.stopPropagation();
    if (t.entry_state === "passed") {
      return <button onClick={(e) => { stop(e); undoOne(t); }} className="text-[11px] px-2.5 py-1 border border-[#E2E8F0] rounded-md text-[#475569] hover:bg-[#F8FAFC] inline-flex items-center gap-1"><Undo2 size={11} /> Undo</button>;
    }
    if (t.entry_state === "set_aside") {
      return <button onClick={(e) => { stop(e); restoreOne(t); }} className="text-[11px] px-2.5 py-1 border border-[#E2E8F0] rounded-md text-[#475569] hover:bg-[#F8FAFC] inline-flex items-center gap-1"><RotateCcw size={11} /> Restore</button>;
    }
    if (t.entry_state === "covered") return <span className="text-[10px] text-[#94A3B8]">—</span>;
    const canPass = t.entry_state === "ready" || (t.entry_state === "proposed" && t.draft_source !== "document");
    if (canPass) {
      return <button onClick={(e) => { stop(e); passOne(t); }}
        title={t.entry_state === "proposed" ? "Accept the proposal and pass it" : "Pass this entry into the books"}
        className={`text-[11px] px-2.5 py-1 rounded-md font-medium text-white ${t.entry_state === "ready" ? "bg-[#059669] hover:bg-[#047857]" : "bg-[#0284C7] hover:bg-[#0369A1]"}`}>Pass</button>;
    }
    return <button onClick={(e) => { stop(e); setDetailId(t.id); }}
      className="text-[11px] px-2.5 py-1 rounded-md font-medium text-[#B45309] bg-amber-50 border border-amber-200 hover:bg-amber-100">Answer</button>;
  };

  // ── bulk ─────────────────────────────────────────────────────────────────

  const open = (t: Entry) => ["needs_you", "proposed", "ready"].includes(t.entry_state);

  const bulkActions: BulkAction<Entry>[] = [
    {
      id: "pass", label: "Pass selected", icon: <CheckCircle size={13} />,
      appliesTo: (sel) => sel.some((t) => t.entry_state === "ready" || t.entry_state === "proposed"),
      run: async (sel) => {
        const ready = sel.filter((t) => t.entry_state === "ready").map((t) => t.id);
        const proposed = sel.filter((t) => t.entry_state === "proposed" && t.draft_source !== "document");
        let passed = 0, failed = 0;
        if (busyRef.current) return;
        busyRef.current = true;
        try {
          if (ready.length) { const n = await passLoop({ transaction_ids: ready, label: "Passing selected", total: ready.length }); passed += n.passed; failed += n.failed; }
          for (const t of proposed) {
            try { await api.banking.entries.pass(t.id); passed += 1; } catch { failed += 1; }
          }
        } finally { setProgress(null); busyRef.current = false; }
        toast({ title: `${passed} passed`, description: failed ? `${failed} refused — see each line.` : undefined, variant: failed ? "destructive" : undefined });
        await reload();
      },
    },
    {
      id: "book", label: "Book under…", appliesTo: (sel) => sel.some(open),
      run: (sel) => { setBookUnder(sel.filter(open)); setBookAccountId(""); },
    },
    {
      id: "aside", label: "Set aside", appliesTo: (sel) => sel.some(open),
      run: async (sel) => { await api.banking.batchExclude(sel.filter(open).map((t) => t.id)); await reload(); },
    },
    {
      id: "restore", label: "Restore", appliesTo: (sel) => sel.some((t) => t.entry_state === "set_aside"),
      run: async (sel) => { await api.banking.batchInclude(sel.filter((t) => t.entry_state === "set_aside").map((t) => t.id)); await reload(); },
    },
    {
      id: "undo", label: "Undo", appliesTo: (sel) => sel.some((t) => t.entry_state === "passed"),
      confirm: "Reverse the journals of the selected passed entries and put the lines back to do?",
      run: async (sel) => {
        let n = 0;
        for (const t of sel.filter((x) => x.entry_state === "passed")) {
          try { await api.banking.undoPost(t.id); n += 1; } catch { /* reported by the count */ }
        }
        toast({ title: `${n} undone` });
        await reload();
      },
    },
  ];

  async function applyBookUnder() {
    if (!bookUnder || !bookAccountId) return;
    setBookBusy(true);
    let n = 0;
    try {
      for (const t of bookUnder) {
        try { await api.banking.setTransactionAccount(t.id, { account_id: bookAccountId, derive_category: true }); n += 1; }
        catch { /* counted */ }
      }
      toast({ title: `${n} line${n === 1 ? "" : "s"} booked under ${accountName(bookAccountId)}`,
              description: n ? "They are Ready — pass them when you are." : undefined });
      // Offer to keep this decision as a rule when the lines share a phrase.
      const pattern = commonNarrationPattern(bookUnder.map((t) => t.description));
      if (n >= 2 && pattern && pattern.length >= MIN_PATTERN_LENGTH) setRulePrompt({ pattern, accountId: bookAccountId });
    } finally {
      setBookBusy(false); setBookUnder(null); await reload();
    }
  }

  async function createRuleFromPrompt() {
    if (!rulePrompt) return;
    setRuleSaving(true);
    try {
      await api.banking.rules.create({
        client_id: clientId, rule_name: `Book “${rulePrompt.pattern}” under ${accountName(rulePrompt.accountId)}`,
        description_pattern: rulePrompt.pattern, suggested_account_id: rulePrompt.accountId,
      });
      toast({ title: "Rule saved", description: "Lines with that phrase will arrive proposed. Make it trusted in Rules to pass them without a click." });
      setRulePrompt(null);
      await settle();
    } catch (e) {
      toast({ title: "Couldn't save the rule", description: e instanceof Error ? e.message : String(e), variant: "destructive" });
    } finally { setRuleSaving(false); }
  }

  // ── render ───────────────────────────────────────────────────────────────

  const chips = CHIPS.filter((c) => c.always || counts[c.key] > 0);

  return (
    <div className="space-y-3">
      {/* The count strip and the one primary action. */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1 bg-[#F8FAFC] rounded-lg p-1" role="tablist" aria-label="Entry state">
          {chips.map((c) => (
            <button key={c.id} role="tab" aria-selected={state === c.id}
              onClick={() => { setState(c.id); setPage(0); }}
              className={`px-2.5 py-1 text-xs rounded-md whitespace-nowrap ${state === c.id ? "bg-white text-[#0F172A] shadow-sm font-medium" : "text-[#64748B] hover:text-[#334155]"}`}>
              {c.label} <span className={`ml-1 tabular-nums ${state === c.id ? "text-[#334155]" : "text-[#94A3B8]"}`}>{counts[c.key]}</span>
            </button>
          ))}
        </div>
        {bankAccounts.length > 1 && (
          <select value={bankAccountId} onChange={(e) => { setBankAccountId(e.target.value); setPage(0); }}
            aria-label="Bank account" className="text-xs px-2 py-1.5 border border-[#E2E8F0] rounded-lg bg-white">
            <option value="">All accounts</option>
            {bankAccounts.map((b) => <option key={b.id} value={b.id}>{b.bank_name} · {b.account_no.slice(-4)}</option>)}
          </select>
        )}
        <div className="ml-auto flex items-center gap-2">
          <button onClick={settle} disabled={!!progress} title="Propose again for every line nobody has proposed for yet"
            className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg text-[#475569] hover:bg-[#F8FAFC] disabled:opacity-40 inline-flex items-center gap-1.5">
            <Sparkles size={12} /> Propose
          </button>
          <button onClick={passAllReady} disabled={!!progress || counts.ready === 0}
            title={counts.ready ? "Pass every Ready entry into the books" : "Nothing is ready to pass"}
            className="text-xs px-3 py-1.5 rounded-lg font-medium text-white bg-[#059669] hover:bg-[#047857] disabled:opacity-40 inline-flex items-center gap-1.5">
            <CheckCircle size={13} /> Pass {counts.ready} ready
          </button>
        </div>
      </div>

      {progress && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl px-4 py-2.5 flex items-center gap-3" role="status">
          <Loader2 size={14} className="animate-spin text-[#4338CA]" />
          <p className="text-xs text-[#334155]">
            {progress.label}… <span className="tabular-nums">{progress.done}{progress.total != null ? ` of ${progress.total}` : ""}</span>
          </p>
          {progress.total ? (
            <div className="flex-1 h-1.5 bg-[#F1F5F9] rounded-full overflow-hidden">
              <div className="h-full bg-[#4338CA] transition-all" style={{ width: `${Math.min(100, Math.round((progress.done / progress.total) * 100))}%` }} />
            </div>
          ) : null}
        </div>
      )}

      {rulePrompt && (
        <div className="bg-[#EEF2FF] border border-[#C7D2FE] rounded-xl px-4 py-3 space-y-2">
          <p className="text-xs text-[#312E81]">
            Those lines all contain <span className="font-mono">{rulePrompt.pattern}</span>. Keep this as a rule, so the next ones arrive proposed?
          </p>
          <div className="flex items-center gap-2">
            <input value={rulePrompt.pattern} disabled={ruleSaving}
              onChange={(e) => setRulePrompt((r) => (r ? { ...r, pattern: e.target.value } : r))}
              className="px-2 py-1 text-xs font-mono border border-[#C7D2FE] rounded bg-white min-w-[16rem] flex-1" />
            <button onClick={createRuleFromPrompt} disabled={ruleSaving} className="text-xs px-3 py-1.5 rounded-lg font-medium text-white bg-[#4338CA] hover:bg-[#3730A3] disabled:opacity-40">{ruleSaving ? "Saving…" : "Create rule"}</button>
            <button onClick={() => setRulePrompt(null)} disabled={ruleSaving} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg text-[#475569] hover:bg-white">Not now</button>
          </div>
        </div>
      )}

      <DataTable
        data={rows}
        columns={columns}
        getRowId={(t) => t.id}
        loading={loading}
        error={loadError}
        onRetry={reload}
        searchPlaceholder="Search narration, reference or payee…"
        persistKey="bank.entries.v1"
        emptyTitle={state === "to_do" ? "Nothing to do" : "Nothing here"}
        emptyDescription={state === "to_do" ? "Every line on this account is passed or set aside. Import a statement to continue." : "No entries in this state."}
        rowClassName={(t) => t.entry_state === "ready" ? "bg-[#F0FDF4] hover:bg-[#DCFCE7]" : t.entry_state === "needs_you" && t.draft_error ? "bg-red-50/40" : ""}
        onRowClick={(t) => setDetailId(t.id)}
        rowActions={actionCell}
        bulkActions={bulkActions}
        serverPaged={{
          total, offset: page * pageSize, pageSize, busy: loading, search,
          onSearchChange: (q) => { setSearch(q); setPage(0); },
          onChange: ({ offset, pageSize: size }) => { setPageSize(size); setPage(Math.floor(offset / size)); },
        }}
      />
      <p className="text-[10px] text-[#94A3B8] text-center">
        A line is a Receipt, a Payment or a Contra — the bank decides which. Click a line to answer it; Pass puts it in the books; Undo takes it back out.
      </p>

      {bookUnder && (
        <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4" onClick={() => !bookBusy && setBookUnder(null)}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-5 space-y-3" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Book under a ledger">
            <h3 className="text-sm font-semibold text-[#0F172A]">Book {bookUnder.length} line{bookUnder.length === 1 ? "" : "s"} under…</h3>
            <AccountLookup accounts={orderedAccounts} value={bookAccountId} onChange={setBookAccountId} ariaLabel="Ledger" placeholder="Choose a ledger…" />
            <p className="text-[10px] text-[#94A3B8]">The lines become Ready with this ledger; nothing is passed until you pass it.</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setBookUnder(null)} disabled={bookBusy} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg text-[#475569] hover:bg-[#F8FAFC]">Cancel</button>
              <button onClick={applyBookUnder} disabled={bookBusy || !bookAccountId} className="text-xs px-3 py-1.5 rounded-lg font-medium text-white bg-[#4338CA] hover:bg-[#3730A3] disabled:opacity-40">{bookBusy ? "Booking…" : "Book under"}</button>
            </div>
          </div>
        </div>
      )}

      {detailId && (
        <EntryDetailModal
          clientId={clientId}
          txnId={detailId}
          accounts={orderedAccounts}
          onClose={() => setDetailId(null)}
          onChanged={reload}
        />
      )}
    </div>
  );
}
