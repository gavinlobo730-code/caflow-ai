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
 *   For review / Categorized / Excluded  ->  one list with three filters —
 *                                            To do · Passed · Set aside — and,
 *                                            under To do, one line of text:
 *                                            "173 to do — 128 ready · 12
 *                                            proposed · 33 need you", each part
 *                                            clickable to narrow the list
 *   Accounts tab, Bank Book tab          ->  Import statement and Accounts on
 *                                            this toolbar (setup, not a step);
 *                                            Bank Book under Reports (a report,
 *                                            not a step). Three tabs, one
 *                                            working screen — 2026-09-03, after
 *                                            first use of the five-tab version
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
import { useRouter } from "next/navigation";
import { BookOpen, CheckCircle, Landmark, Loader2, Paperclip, RotateCcw, Sparkles, Undo2, Upload, X } from "lucide-react";
import { api, type EntryListState, type EntryState } from "@/lib/api";
import { DataTable } from "@/components/ui/data-table";
import type { BulkAction, Column } from "@/lib/table/types";
import { AccountLookup } from "@/components/lookups/AccountLookup";
import { commonNarrationPattern, MIN_PATTERN_LENGTH } from "@/lib/banking/narrationPattern";
import { useToast } from "@/components/ui/use-toast";
import { type Account, type BankAccount, fmt } from "@/components/banking/shared";
import { EntryDetailModal } from "@/components/banking/EntryDetailModal";
import { BankAccounts, BankImportModal } from "@/components/banking/AccountsPanel";

// ── the row, as the server sends it ─────────────────────────────────────────

export interface Entry {
  id: string; transaction_date: string; description: string; reference_no: string | null;
  debit_paise: number; credit_paise: number; match_status: string;
  category: string | null; account_id: string | null;
  matched_entity_type: string | null; matched_entity_id: string | null;
  /** The number the matched document is known by — INV-042, not its uuid.
   *  Resolved server-side, one query per document type on the page. Null when
   *  nothing is matched, or for a "manual" match, which has no document. */
  matched_document_no: string | null;
  posted_journal_id: string | null;
  transfer_pair_id: string | null; transfer_is_primary: boolean | null;
  payee_name: string | null; payee_type: string | null; payee_id: string | null;
  has_splits: boolean; is_split?: boolean; split_count?: number;
  /** Supporting documents kept against this line. A stored document has a
   *  document_id and NO url — the store's link expires, so one is minted when
   *  it is opened. A pasted link has a url and no id. */
  attachments?: { name: string; url?: string | null; document_id?: string | null }[];
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

/** The three filters: still to do, done, set aside — the three states a
 *  statement line is in as far as the person clearing it is concerned. Passed
 *  counts the covered side of a transfer with it (the server lists them
 *  together): it has no journal of its own, but it is done. The working
 *  states under To do are NOT chips — see WORKING. Six chips made the CA
 *  classify their own queue before they could work it. */
const CHIPS: { id: EntryListState; label: string; count: (c: Counts) => number }[] = [
  { id: "to_do",     label: "To do",     count: (c) => c.to_do },
  { id: "passed",    label: "Passed",    count: (c) => c.passed + c.covered },
  { id: "set_aside", label: "Set aside", count: (c) => c.set_aside },
];

/** The working states, as one line of text under To do — "128 ready · 12
 *  proposed · 33 need you" — in the order a CA clears them: what passes in
 *  one click, then what needs a look, then what needs an answer. Each part
 *  narrows the list to that state; the row already carries the colour. */
const WORKING: { id: EntryState; key: keyof Counts; word: (n: number) => string }[] = [
  { id: "ready",     key: "ready",     word: (n) => `${n} ready` },
  { id: "proposed",  key: "proposed",  word: (n) => `${n} proposed` },
  { id: "needs_you", key: "needs_you", word: (n) => `${n} need${n === 1 ? "s" : ""} you` },
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
  const router = useRouter();
  const [state, setState] = useState<EntryListState>("to_do");
  const [showImport, setShowImport] = useState(false);
  const [showAccounts, setShowAccounts] = useState(false);
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

  /** `quiet` keeps the rows on screen while they are re-read.
   *
   *  The shared table swaps its whole body for a skeleton whenever `loading`
   *  is true (AsyncBoundary in components/ui/data-table.tsx), which is right
   *  when there is nothing to show yet and wrong when there is: after a write
   *  the rows ARE on screen — one of them just changed — so blanking all
   *  thirteen into grey bars for the round trip reads as the page breaking
   *  rather than as one line updating. A first load, and a change of filter,
   *  page or search, still shows the skeleton: there the content genuinely is
   *  not there yet. */
  const loadRows = useCallback(async (opts?: { quiet?: boolean }) => {
    if (!opts?.quiet) setLoading(true);
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

  /** Every caller of this is "something was written, catch up" — never a
   *  first load — so the rows stay put while they are re-read. */
  const reload = useCallback(async () => {
    await Promise.all([loadCounts(), loadRows({ quiet: true })]);
  }, [loadCounts, loadRows]);

  /** The active bank accounts — the account filter, and what a statement can
   *  be imported against. Reloaded after anything the Accounts panel does. */
  const loadBankAccounts = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    try {
      const r = (await api.banking.listBankAccounts({ client_id: clientId })) as { success: boolean; data: BankAccount[] };
      setBankAccounts(r.success ? (r.data ?? []).filter((a) => a.is_active) : []);
    } catch {
      setBankAccounts([]);
    }
  }, [clientId]);

  useEffect(() => { loadBankAccounts(); }, [loadBankAccounts]);

  useEffect(() => { if (clientId && clientId !== "_placeholder") loadRows(); }, [loadRows, clientId]);

  /** The counts follow the ACCOUNT, and nothing else: they are per-state
   *  totals for the whole account, so paging, searching or switching chip
   *  cannot change them. loadCounts is memoised on exactly (clientId,
   *  bankAccountId), so this fires once per account change — one small
   *  request, not the settle sweep. Without it the chips kept whichever
   *  account's numbers were loaded last, and a filtered screen read "13 to do"
   *  over another account's empty list. */
  useEffect(() => {
    if (clientId && clientId !== "_placeholder") loadCounts().catch(() => { /* the chips keep their last honest value */ });
  }, [loadCounts, clientId]);

  /** Propose for every undrafted line, then pass what the trusted rules
   *  drafted — both in chunks with progress. Runs on open and after an
   *  import, and never twice at once — see settleRef below for why the
   *  trigger is pinned to clientId rather than to this function's identity. */
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

  /** settle's own identity is rebuilt on every filter change — it closes
   *  over loadCounts and reload, which close over bankAccountId, state, page,
   *  search. If the effect below depended on `settle` directly, switching the
   *  bank-account filter (or paging, or searching) would re-run the WHOLE
   *  propose-and-pass-trusted pipeline, not just re-fetch the rows: two
   *  loadCounts calls and a redraft/pass sweep on every click of the account
   *  dropdown, layered on top of the fetch loadRows already does for the same
   *  filter change. That is exactly the burst that produced a transient 500 in
   *  production — several requests landing on the API and the database pool
   *  at once for one user action. `settle` belongs on open only, so the
   *  effect below is pinned to clientId; settleRef keeps it calling the
   *  current closure (current bankAccountId etc.) without RE-RUNNING on every
   *  closure it captures. */
  const settleRef = useRef(settle);
  useEffect(() => { settleRef.current = settle; }, [settle]);
  useEffect(() => {
    if (clientId && clientId !== "_placeholder") settleRef.current();
  }, [clientId]);

  /** An import finished, or an account was added, edited or deactivated:
   *  the account list may differ, and new lines want proposing for at once —
   *  the CA should not have to close the panel and press Propose. */
  const afterSetupChange = useCallback(async () => {
    await loadBankAccounts();
    await settle();
  }, [loadBankAccounts, settle]);

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
      // The NUMBER first: "against an invoice" is the same sentence for every
      // matched line on the page, and tells a CA nothing about which one.
      const noun = t.matched_entity_type === "sales_invoice" ? "invoice"
        : t.matched_entity_type === "purchase_bill" ? "bill"
        : (t.matched_entity_type ?? "document").replace("_", " ");
      const doc = t.matched_document_no
        ? `against ${noun} ${t.matched_document_no}`
        : t.matched_entity_type === "sales_invoice" ? "against an invoice"
          : t.matched_entity_type === "purchase_bill" ? "against a bill"
          : `against a ${noun}`;
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
          {(t.attachments?.length ?? 0) > 0 && (
            <Paperclip size={11} className="shrink-0 text-[#94A3B8]"
              aria-label={`${t.attachments!.length} supporting document${t.attachments!.length === 1 ? "" : "s"}`} />
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

  /** Which chip is lit: a working state narrows To do, so To do stays lit. */
  const filter: EntryListState = WORKING.some((w) => w.id === state) ? "to_do" : state;

  /** Nothing in ANY state — so there are no lines here at all, rather than
   *  lines that have all been dealt with. The two want different words: an
   *  account that has been added but never imported from is the first case,
   *  and telling that CA every line is "passed or set aside" is a false
   *  statement about books they have not started. */
  const noLinesAtAll = counts.to_do + counts.passed + counts.covered + counts.set_aside === 0;

  return (
    <div className="space-y-3">
      {/* The three filters, setup on the right, and the one primary action. */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1 bg-[#F8FAFC] rounded-lg p-1" role="tablist" aria-label="Entry state">
          {CHIPS.map((c) => (
            <button key={c.id} role="tab" aria-selected={filter === c.id}
              onClick={() => { setState(c.id); setPage(0); }}
              className={`px-2.5 py-1 text-xs rounded-md whitespace-nowrap ${filter === c.id ? "bg-white text-[#0F172A] shadow-sm font-medium" : "text-[#64748B] hover:text-[#334155]"}`}>
              {c.label} <span className={`ml-1 tabular-nums ${filter === c.id ? "text-[#334155]" : "text-[#94A3B8]"}`}>{c.count(counts)}</span>
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
          <button onClick={() => setShowAccounts(true)} title="Bank accounts and imported statements"
            className="text-xs px-2 py-1.5 text-[#64748B] hover:text-[#334155] inline-flex items-center gap-1.5">
            <Landmark size={12} /> Accounts
          </button>
          <button onClick={() => router.push(`/clients/${clientId}/reports/bank-book`)}
            title="The bank ledger with a running balance — under Reports"
            className="text-xs px-2 py-1.5 text-[#64748B] hover:text-[#334155] inline-flex items-center gap-1.5">
            <BookOpen size={12} /> Bank Book
          </button>
          <button onClick={() => (bankAccounts.length === 0 ? setShowAccounts(true) : setShowImport(true))}
            disabled={!!progress}
            title={bankAccounts.length === 0 ? "Add a bank account first" : "Import a statement (.csv or .xlsx) for one of the bank accounts"}
            className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg text-[#475569] hover:bg-[#F8FAFC] disabled:opacity-40 inline-flex items-center gap-1.5">
            <Upload size={12} /> Import statement
          </button>
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

      {/* Under To do, the working states as one line — each part narrows the
          list to that state; the lit one is bold, and clicking it again widens. */}
      {filter === "to_do" && counts.to_do > 0 && (
        <p className="text-xs text-[#475569]" role="group" aria-label="Working states">
          <span className="font-medium text-[#0F172A] tabular-nums">{counts.to_do} to do</span>
          <span className="text-[#94A3B8]"> — </span>
          {WORKING.filter((w) => counts[w.key] > 0).map((w, i) => (
            <span key={w.id}>
              {i > 0 && <span className="text-[#94A3B8]"> · </span>}
              <button onClick={() => { setState(state === w.id ? "to_do" : w.id); setPage(0); }}
                aria-pressed={state === w.id}
                className={`tabular-nums underline decoration-dotted underline-offset-2 hover:text-[#0F172A] ${state === w.id ? "font-semibold text-[#0F172A]" : ""}`}>
                {w.word(counts[w.key])}
              </button>
            </span>
          ))}
          {state !== "to_do" && <span className="text-[#94A3B8]"> · showing only these</span>}
        </p>
      )}

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
        emptyTitle={noLinesAtAll ? "No statements imported yet" : state === "to_do" ? "Nothing to do" : "Nothing here"}
        emptyDescription={
          noLinesAtAll
            ? `${bankAccountId ? "This account has" : "This client has"} no bank lines yet — import a statement and they arrive here, proposed for.`
            : state === "to_do"
              ? "Every line on this account is passed or set aside. Import a statement to continue."
              : "No entries in this state."}
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

      {showImport && (
        <BankImportModal
          clientId={clientId}
          accounts={bankAccounts}
          onClose={() => setShowImport(false)}
          onImported={() => { setShowImport(false); afterSetupChange(); }}
          onManageAccounts={() => { setShowImport(false); setShowAccounts(true); }}
        />
      )}

      {/* The Accounts panel: setup, not a step. z-40 so the panel's own
          modals (add account, import) float above it at z-50. */}
      {showAccounts && (
        <div className="fixed inset-0 bg-[#0F172A]/60 z-40 flex items-start justify-center p-4 overflow-y-auto" onClick={() => setShowAccounts(false)}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-5xl my-6 p-5 space-y-4" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Bank accounts and statements">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-sm font-semibold text-[#0F172A]">Bank accounts and statements</h3>
                <p className="text-[11px] text-[#94A3B8] mt-0.5">Add an account once; import a statement when the bank sends one. New lines are proposed for the moment an import finishes.</p>
              </div>
              <button onClick={() => setShowAccounts(false)} className="text-[#94A3B8] hover:text-[#475569]" aria-label="Close"><X size={16} /></button>
            </div>
            <BankAccounts clientId={clientId} onChanged={afterSetupChange} />
          </div>
        </div>
      )}

      {detailId && (
        <EntryDetailModal
          clientId={clientId}
          txnId={detailId}
          // The row this page already holds. The modal renders from it at once
          // and treats GET /entries/{id} as an enrichment, so a slow or failed
          // detail fetch can never leave the CA looking at an empty box.
          initial={rows.find((r) => r.id === detailId)}
          accounts={orderedAccounts}
          onClose={() => setDetailId(null)}
          onChanged={reload}
        />
      )}
    </div>
  );
}
