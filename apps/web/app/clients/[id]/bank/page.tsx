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

import { useEffect, useState, useCallback, useMemo, useRef, Fragment, type ReactNode } from "react";
import { Plus, RefreshCw, Upload, CheckCircle, X, FileText, Download, Pencil, Landmark, Search, Split } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { getFirmId } from "@/lib/data/getFirmId";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { formatPaise } from "@/lib/services/formatting";
import { AccountLookup } from "@/components/lookups/AccountLookup";
import { SplitAcrossLedgersModal } from "@/components/banking/SplitAcrossLedgersModal";
import { CustomerLookup } from "@/components/lookups/CustomerLookup";
import { VendorLookup } from "@/components/lookups/VendorLookup";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { api } from "@/lib/api";
import { TableSkeleton, StatementSkeleton, TransactionListSkeleton } from "@/components/ui/skeleton";
// Throttles the per-row candidate lookups. Same helper, same reason, as the
// cash-flow matrix: one request per visible row, fired at once, is a fan-out at
// the slowest endpoint in the app.
import { mapWithLimit } from "@/lib/accounting/cashFlowMatrix";
import { commonNarrationPattern, MIN_PATTERN_LENGTH } from "@/lib/banking/narrationPattern";
import { DataTable } from "@/components/ui/data-table";
import type { BulkAction, Column } from "@/lib/table/types";
import {
  getBankStatements,
  getBankTransactions,
  type BankStatement,
  type BankTransaction,
} from "@/lib/data/bankStatements";

// ── Tabs, in pipeline order ────────────────────────────────────────────────

type BankTab = "accounts" | "register" | "categorize" | "reconcile" | "rules";

const TABS: { id: BankTab; label: string }[] = [
  { id: "accounts",   label: "Accounts" },
  // The ledger view of one account. Sits next to Accounts rather than in the
  // pipeline: it is where you go to LOOK something up, not a step you work
  // through. Same placement as QuickBooks.
  { id: "register",   label: "Register" },
  // One screen, not two. Categorising and posting were never two decisions —
  // they were one decision and its consequence, split across two tabs and eight
  // sub-views, with a Partner approval in between that nobody could perform at
  // 300 lines a client. The row posts.
  { id: "categorize", label: "Categorize" },
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
  /** Ranked match candidates, computed for the whole page server-side and
   *  returned with the queue. Absent on a row that already has an answer
   *  (posted, excluded, or linked), which is not given candidates. */
  suggestions?: MatchSuggestion[];
  /** The counter GL account already chosen for this row, when one was. Categories
   *  in AUTO_COUNTER_CATEGORIES derive theirs and leave this null. */
  account_id?: string | null;
  /** Set once the row is on the books. Its presence is what "Categorized" means. */
  posted_journal_id?: string | null;
  /** What a rule proposed for a tax-INCLUSIVE amount. A proposal only — the
   *  person clicking Add is the one asserting the rate. Offered in BOTH
   *  directions now: out is input credit (CGST Act s.16), in is output tax
   *  (s.9). */
  suggested_gst_rate_bps?: number | null;
  suggested_is_interstate?: boolean | null;
  /** Whether a GST rate may go on this line AT ALL — decided server-side by
   *  posting_map.gst_split_allowed, the same call the posting engine makes to
   *  refuse one. Reading it rather than re-deriving the rule here is what stops
   *  the screen offering a control the server rejects. */
  gst_allowed?: boolean;
  // What a matching rule proposes for this row (Rules tab). The account and
  // narration are new: the rule engine used to return only a category.
  suggested_account_id: string | null;
  suggested_narration: string | null;
  suggested_by_rule: string | null;
  /** What the bank already wrote down, parsed server-side. An Indian narration
   *  is a delimited record — channel, UTR, counterparty and VPA are all in
   *  there. The raw text stays in `description` as the record of what arrived. */
  parsed?: {
    channel: string | null; utr: string | null; vpa: string | null;
    counterparty: string | null; ifsc: string | null; summary: string;
  } | null;
  /** Tier 1.2 — the ledgers this ONE line was allocated across. A split row
   *  carries a null category and a null account_id exactly like an untouched
   *  one, so without these the screen would offer a ledger picker over an
   *  allocation that was already made and quietly replace it. */
  is_split?: boolean;
  split_count?: number;
  splits?: { account_id: string; amount_paise: number; narration: string | null }[];
  /** Tier 1.5 — the other half of the same movement, once confirmed. Only the
   *  primary side carries a journal; the counterpart is the same cash. */
  transfer_pair_id?: string | null;
  transfer_is_primary?: boolean | null;
  /** Tier 1.3 — who the money went to or came from, once a human confirms it. */
  payee_name?: string | null;
  payee_type?: "customer" | "vendor" | "other" | null;
  payee_id?: string | null;
  /** What the narration looks like it was with. A proposal — never written
   *  without the CA accepting it, and never offered over an answer they gave. */
  suggested_payee?: {
    payee_name: string; payee_type: "customer" | "vendor" | "other";
    payee_id: string | null; source: "matched_party" | "narration";
  } | null;
  /** Tier 1.4 — what was done with this payee before, WITH the evidence.
   *  `summary` is the sentence to show; a CA cannot audit a bare score, but can
   *  judge "coded this way 8 of the last 9 times" on sight. */
  history?: {
    account_id: string | null; category: string | null;
    times_seen: number; total_seen: number; share_bps: number;
    is_unanimous: boolean; last_seen: string | null; summary: string;
    matched_on: string;
    alternatives: { account_id: string | null; category: string | null; times: number }[];
  } | null;
}
/** Tier 1.7 — what happened to ONE row of a batch. Every row comes back with
 *  an outcome; a partial success shown as a success hides uncoded lines. */
interface BatchResult {
  transaction_id: string;
  /** "would_apply" is the dry run's verdict — this row WOULD be coded. It is a
   *  distinct value on purpose: a preview that reported "applied" would count
   *  writes that never happened. */
  status: "applied" | "skipped" | "failed" | "would_apply";
  reason: string;
  /** Present on accept outcomes and on every dry-run row, so the screen can say
   *  which line is getting which ledger, and on whose authority. */
  account_id?: string | null;
  category?: string | null;
  source?: string;
  description?: string;
}
interface BatchOutcome {
  results: BatchResult[]; applied: number; skipped: number; failed: number; total: number;
}
/** Tier 1.5 — two bank lines that look like one movement between the client's
 *  own accounts. `primary_id` is the outflow: the side that will carry the
 *  journal. Confirming does NOT post anything. */
interface TransferSuggestion {
  primary_id: string; counterpart_id: string; amount_paise: number;
  primary_date: string | null; counterpart_date: string | null;
  day_gap: number; confidence: "high" | "medium" | "low";
  is_unambiguous: boolean; summary: string;
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

// Three, because a statement line is in one of three states as far as the person
// clearing it is concerned: still to do, done, or set aside. The five it replaced
// — Unmatched / Categorized / Needs Review / Matched / Excluded — described the
// DATA's states, and made a reader classify their own queue before they could
// work it. Categorized and Matched were two roads to the same place; Needs Review
// was a subset of Unmatched.
const QUEUE_FILTERS: { id: string; label: string }[] = [
  { id: "for_review", label: "For review" },
  { id: "done",       label: "Categorized" },
  { id: "ignored",    label: "Excluded" },
];

// Categories whose counter account the posting engine derives on its own
// (posting_map.AUTO_COUNTER). Everything else needs one chosen before the row
// can post, which is what decides whether the primary button is live.
const AUTO_COUNTER_CATEGORIES = new Set(["Customer Payment", "Vendor Payment", "GST Payment"]);

// Matches the Register tab's page size, and the API's default. Big enough that
// a month of statement lines is one or two pages; small enough that the browser
// is not laying out three hundred disclosure rows nobody opened.
const QUEUE_PER_PAGE = 50;

function BankMatchQueue({ clientId, accounts }: { clientId: string; accounts: Account[] }) {
  const [status, setStatus] = useState("for_review");
  const [rows, setRows] = useState<QueueTxn[]>([]);
  // Paged. A statement is 300 lines a month and the queue used to render all of
  // them in one scroll, with nothing on screen saying how many there were.
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(QUEUE_PER_PAGE);
  const [total, setTotal] = useState(0);
  // SERVER-side. The screen holds one page, so a box that filtered the rows
  // already fetched would answer "no match" for a line on page four.
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [sugg, setSugg] = useState<Record<string, MatchSuggestion[]>>({});
  const [transfers, setTransfers] = useState<TransferSuggestion[]>([]);
  const [batchOutcome, setBatchOutcome] = useState<BatchOutcome | null>(null);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [bulkBusy, setBulkBusy] = useState(false);
  /** The lines a bulk "Set ledger" is acting on, captured when the action ran.
   *  DataTable clears its own selection the moment a bulk action resolves, so
   *  by the time the modal is on screen there is nothing left to read back —
   *  it has to hold its own copy of what was picked. */
  const [bulkRows, setBulkRows] = useState<QueueTxn[] | null>(null);
  const [bulkAccountId, setBulkAccountId] = useState("");
  const [bulkGstRate, setBulkGstRate] = useState("");
  const [bulkGstInterstate, setBulkGstInterstate] = useState(false);
  /** What a matching rule made from the bulk coding just done would say.
   *  Held after the modal closes, because the offer belongs AFTER the work: the
   *  CA has just demonstrated the answer on real lines, which is the only
   *  moment they know the pattern without being asked to invent one. */
  const [rulePrompt, setRulePrompt] = useState<{
    pattern: string; accountId: string; count: number;
    gstRateBps: number | null; isInterstate: boolean;
    txnType: "debit" | "credit" | "any";
  } | null>(null);
  const [ruleSaving, setRuleSaving] = useState(false);
  const [ruleSaved, setRuleSaved] = useState<string | null>(null);
  const [ruleError, setRuleError] = useState<string | null>(null);
  /** What "Apply suggestions" WOULD do, straight from the server's dry run.
   *  Held so the CA can read it before anything is written. */
  const [preview, setPreview] = useState<{ rows: BatchResult[]; ids: string[] } | null>(null);
  const [bulkError, setBulkError] = useState<string | null>(null);
  // Distinguishes "fetch failed" from "queue genuinely empty" (a masked
  // failure here reads as a fully-reconciled bank, which it may not be).
  const [loadError, setLoadError] = useState<string | null>(null);
  // Settlement modal — allocate ONE transaction across one or more invoices/
  // bills for a party, with any TDS the customer withheld. `prefill` is set when
  // the modal is opened from a short suggestion, so the CA lands on the right
  // party and document instead of re-finding what we just showed them.
  const [splitTxn, setSplitTxn] = useState<QueueTxn | null>(null);
  // WHICH split. One line can be split across LEDGERS (a landlord payment that
  // is rent + maintenance + parking) or across DOCUMENTS (one receipt settling
  // three invoices). Both are real; they used to be one button whose label said
  // "several" and whose behaviour was always documents, so the ledger split —
  // fully built in the backend since migration 256 — had no way in at all.
  const [splitMode, setSplitMode] = useState<"ledgers" | "documents">("ledgers");
  const [prefill, setPrefill] = useState<SettlePrefill | null>(null);
  // B.1.6 — the searchable candidate picker, for the document the ranked list
  // could not reach.
  const [findTxn, setFindTxn] = useState<QueueTxn | null>(null);
  // Which rows the reader has opened. Everything past the one decision a row
  // needs lives behind this — payee, history, the other candidates, split,
  // TDS, exclude. A row that already knows its answer shows a button and
  // nothing else.
  /** The line whose detail modal is open, if any. One id, not a set: the modal
   *  is centred and singular, where the old expanded rows could be opened all
   *  at once and turn the queue into a wall. */
  const [detailId, setDetailId] = useState<string | null>(null);
  /** Account ids ranked by how often this client posts bank lines to them. */
  const [ledgerOrder, setLedgerOrder] = useState<string[]>([]);
  const [rowError, setRowError] = useState<Record<string, string>>({});
  // Input GST split out of a tax-inclusive bank charge, per row. Carried here
  // rather than left in the posting drawer that used to own it: that drawer is
  // gone, and losing the s.16 split with it would quietly cost every client the
  // credit on their bank charges.
  const [gstRate, setGstRate] = useState<Record<string, string>>({});
  const [gstInterstate, setGstInterstate] = useState<Record<string, boolean>>({});


  /** The split editor, opened on the LEDGER side — the everyday case, and the
   *  one that had no route through the UI. The mode switch inside reaches the
   *  document side. */
  function openSplit(t: QueueTxn) {
    setPrefill(null);
    setSplitMode("ledgers");
    setSplitTxn(t);
  }

  function openSettle(t: QueueTxn, from?: { party_id: string | null; matched_entity_id: string; difference_paise: number }) {
    setSplitMode("documents");
    setPrefill(from && from.party_id ? {
      partyId: from.party_id,
      docId: from.matched_entity_id,
      tdsPaise: from.difference_paise,
    } : null);
    setSplitTxn(t);
  }

  /** The chart, reordered so the handful this client actually uses come first.
   *
   *  ORDERS, NEVER FILTERS. The picker offered every active account in
   *  account_code order — 100-200 entries on a normal Indian chart, with
   *  Accumulated Depreciation and Retained Earnings sitting between the two
   *  anyone would pick. Removing them would be worse: a ledger nobody has used
   *  YET is often exactly why a CA opened the list. So nothing goes missing,
   *  things simply come up in the order a person would look for them.
   */
  const orderedAccounts = useMemo(() => {
    if (ledgerOrder.length === 0) return accounts;
    const rank = new Map(ledgerOrder.map((id, i) => [id, i]));
    // Stable: equal ranks keep the chart's own account_code order, so the list
    // below the used ones stays where the reader last saw it.
    return [...accounts].sort((a, b) =>
      (rank.get(a.id) ?? Number.MAX_SAFE_INTEGER) - (rank.get(b.id) ?? Number.MAX_SAFE_INTEGER));
  }, [accounts, ledgerOrder]);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    try {
      const res = (await api.banking.queue({
        client_id: clientId, status,
        limit: String(pageSize), offset: String(page * pageSize),
        ...(search.trim() ? { q: search.trim() } : {}),
      })) as { success: boolean; data: { rows: QueueTxn[]; total: number; ledger_order?: string[] } };
      if (!res.success) throw new Error("Couldn't load the bank match queue.");
      const got = res.data?.rows ?? [];
      setRows(got);
      setTotal(res.data?.total ?? 0);
      // Which ledgers THIS client actually codes bank lines to, most-used
      // first. A property of the client, so it arrives once per page.
      setLedgerOrder(res.data?.ledger_order ?? []);
      // Candidates arrive WITH the rows. They used to be fetched one request
      // per row after the queue landed, three at a time — five Mumbai round
      // trips each, so the matched rows lit up a few at a time over several
      // seconds and the reader could see it happening. The ranking was never
      // the slow part; the fetching was, and it re-read the same pool for
      // every row.
      setSugg(Object.fromEntries(got.map((t) => [t.id, t.suggestions ?? []])));
      setLoadError(null);
    } catch (e) {
      setRows([]); setTotal(0);
      setLoadError(e instanceof Error ? e.message : "Couldn't load the bank match queue.");
    } finally {
      setLoading(false);
    }
  }, [clientId, status, page, pageSize, search]);
  useEffect(() => { load(); }, [load]);
  // A different view, client or search term is a different queue — page one.
  useEffect(() => { setPage(0); }, [status, clientId, search]);
  // A different view or page is a different set of lines; close the modal.
  useEffect(() => { setDetailId(null); }, [status, page]);

  /** The GST rate to SEND with a post, or "" for none.

   *  Gated on the server's own verdict. A matching rule can propose a rate on a
   *  row the posting engine will refuse it on — a receipt later matched to an
   *  invoice, say — and the cell then correctly shows nothing. Without this
   *  gate the proposal would still be sent, and Add would fail with a message
   *  about a control the reader cannot see.
   */
  const rateToSend = (t: QueueTxn): string => {
    if (!t.gst_allowed) return "";
    return gstRate[t.id] ?? (t.suggested_gst_rate_bps != null ? String(t.suggested_gst_rate_bps) : "");
  };

  /** Code a row by naming the LEDGER — the one field this screen asks for.
   *
   *  The category follows from the account server-side
   *  (domain/banking/account_category); it is not a second question, and the
   *  panel's Category control is only there to refine the word. Written
   *  through on the click rather than held as a draft: a choice that sits in
   *  the browser until someone presses Add is a choice that gets lost when
   *  they page, search or reload. */
  /** Patch ONE row from what an endpoint just returned.
   *
   *  Every per-row action used to end in load(), which sets `loading` and
   *  refetches the whole page — a cross-region round trip to Mumbai — so
   *  picking one ledger tore down and rebuilt the entire table in front of the
   *  reader. Nothing about the other forty-nine rows changed; only this one
   *  did, and the server already says how.
   */
  const patchRow = useCallback((id: string, fields: Partial<QueueTxn>) => {
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...fields } : r)));
  }, []);

  async function codeToAccount(t: QueueTxn, accountId: string) {
    if (!accountId) return;
    setBusy((b) => ({ ...b, [t.id]: true }));
    setRowError((e) => ({ ...e, [t.id]: "" }));
    try {
      const res = (await api.banking.setTransactionAccount(t.id, {
        account_id: accountId, derive_category: true,
      })) as { data?: { account_id?: string; category?: string | null; gst_allowed?: boolean;
                        match_status?: string } };
      const d = res?.data ?? {};
      // gst_allowed comes back WITH the row precisely so this patch keeps the
      // GST cell in step: picking a ledger is what turns "pick a ledger" into a
      // usable rate, and without it the cell would contradict the line beside it.
      patchRow(t.id, {
        account_id: d.account_id ?? accountId,
        category: d.category ?? null,
        gst_allowed: d.gst_allowed ?? false,
        match_status: d.match_status ?? t.match_status,
      });
    } catch (e) {
      setRowError((x) => ({ ...x, [t.id]: e instanceof Error ? e.message : "Could not set the ledger." }));
    } finally { setBusy((b) => ({ ...b, [t.id]: false })); }
  }

  /** Ask the server what Apply suggestions would do, and show it.
   *
   *  NOT computed here. The browser has each row's `suggested_account_id` and
   *  could draw a list from it — and that list would be a SECOND answer: it
   *  knows nothing about payee history, and nothing about the refusals the
   *  server applies (already posted, already coded). The CA would approve one
   *  thing and the books would take another, with nothing reporting the
   *  difference. The dry run is the same function that does the work.
   */
  async function previewSuggestions(picked: QueueTxn[]) {
    const ids = picked.map((t) => t.id);
    // No busy flag of its own: DataTable disables the whole bulk bar while a
    // bulk action's promise is in flight, and this runs inside one.
    setBulkError(null);
    try {
      const res = (await api.banking.batchAcceptPreview(ids)) as
        { success: boolean; data?: { results?: BatchResult[] }; error: string | null };
      if (!res.success) { setBulkError(res.error ?? "Could not read the suggestions."); return; }
      setPreview({ rows: res.data?.results ?? [], ids });
    } catch (e) {
      setBulkError(e instanceof Error ? e.message : "Could not read the suggestions.");
    }
  }

  /** Put recorded lines back, in bulk. The Categorized tab had no way to do
   *  this at all: every action the bar offered there was one a posted line
   *  cannot take, so the one thing a CA actually wants on that tab — "these
   *  should not have been recorded" — was the one thing missing, and they had
   *  to press Undo forty times instead.
   *
   *  Undo is the reversal path, not a delete: bank_posting_service.undo writes
   *  an append-only reversal and un-settles the document. Per line, so one
   *  refusal does not strand the rest. */
  async function undoPicked(picked: QueueTxn[]) {
    const targets = picked.filter((t) => t.match_status === "posted");
    const results: BatchResult[] = picked
      .filter((t) => !targets.includes(t))
      .map((t) => ({ transaction_id: t.id, status: "skipped" as const,
                     reason: "Not recorded — there is nothing to undo." }));
    if (targets.length === 0) {
      setBatchOutcome({ results, applied: 0, skipped: results.length, failed: 0,
                        total: results.length });
      return;
    }
    setBulkBusy(true);
    setBulkError(null);
    try {
      await mapWithLimit(targets, 3, async (t) => {
        try {
          await api.banking.undoPost(t.id);
          results.push({ transaction_id: t.id, status: "applied", reason: "Put back." });
        } catch (e) {
          results.push({ transaction_id: t.id, status: "failed",
            reason: e instanceof Error ? e.message : "Could not undo." });
        }
      });
      setBatchOutcome({
        results,
        applied: results.filter((r) => r.status === "applied").length,
        skipped: results.filter((r) => r.status === "skipped").length,
        failed: results.filter((r) => r.status === "failed").length,
        total: results.length,
      });
      setSugg({});
      await load();
    } catch (e) {
      setBulkError(e instanceof Error ? e.message : "Could not undo the selected rows.");
    } finally { setBulkBusy(false); }
  }

  /** Save the proposed rule. Nothing here is automatic: the pattern is on
   *  screen and editable, and this runs only on the CA's click.
   *
   *  Rules never post anything (domain/banking/rules is "SUGGESTIONS ONLY") —
   *  the most a wrong one can do is propose a ledger the CA then declines, so
   *  the cost of a bad pattern is a suggestion to ignore, not a bad entry. */
  async function createRuleFromPrompt() {
    const r = rulePrompt;
    if (!r) return;
    const pattern = r.pattern.trim();
    if (pattern.length < MIN_PATTERN_LENGTH) {
      setRuleError(`A pattern needs at least ${MIN_PATTERN_LENGTH} characters — a shorter one would fire on nearly every line, and the first rule that fires is the one that wins.`);
      return;
    }
    setRuleSaving(true);
    setRuleError(null);
    try {
      const res = (await api.banking.rules.create({
        client_id: clientId,
        rule_name: `${pattern} → ${accountLabel(r.accountId)}`,
        description_pattern: pattern,
        amount_min_paise: null,
        amount_max_paise: null,
        txn_type: r.txnType,
        suggested_category: null,
        suggested_account_id: r.accountId,
        suggested_narration: null,
        suggested_gst_rate_bps: r.gstRateBps,
        suggested_is_interstate: r.isInterstate,
      })) as { success: boolean; error: string | null };
      if (!res.success) { setRuleError(res.error ?? "Could not save the rule."); return; }
      setRuleSaved(pattern);
      setRulePrompt(null);
    } catch (e) {
      setRuleError(e instanceof Error ? e.message : "Could not save the rule.");
    } finally {
      setRuleSaving(false);
    }
  }

  /** Set ONE ledger on every line the CA picked, and record them.
   *
   *  This replaced a "— Bulk category —" dropdown that called categorize()
   *  with a category and nothing else. That word is the one the row stopped
   *  asking for: the category FOLLOWS the ledger server-side
   *  (domain/banking/account_category). For the three auto-counter categories
   *  the posting engine could still derive its own counter account, so those
   *  lines did become recordable; for the other eight it set a word, left the
   *  line without a ledger and therefore unpostable, and cleared the selection
   *  as though the work were done.
   *
   *  Per line, never all-or-nothing: one rejected line must not strand the
   *  other seven, and the reader has to be told WHICH failed.
   */
  async function applyBulkLedger() {
    const picked = bulkRows ?? [];
    const eligible = bulkEligible(picked);
    if (!bulkAccountId || eligible.length === 0) return;
    const rate = bulkGstOffered(eligible) ? bulkGstRate : "";
    setBulkBusy(true);
    setBulkError(null);
    // The lines that were selected but cannot take a ledger are reported as
    // skipped rather than dropped — a selection of eight that records six
    // must say what happened to the other two.
    const results: BatchResult[] = picked
      .filter((t) => !eligible.includes(t))
      .map((t) => ({
        transaction_id: t.id,
        status: "skipped" as const,
        reason: t.match_status === "posted" ? "Already recorded — Undo it first."
          : t.match_status === "ignored" ? "Excluded — put it back first."
          : "Allocated across several ledgers — open the line to change that.",
      }));
    try {
      await mapWithLimit(eligible, 3, async (t) => {
        try {
          const res = (await api.banking.setTransactionAccount(t.id, {
            account_id: bulkAccountId, derive_category: true,
          })) as { data?: { gst_allowed?: boolean } };
          const allowed = res?.data?.gst_allowed ?? false;
          // A rate was asked for and the SERVER says this line cannot carry
          // one. The ledger is set, but the line is left in the queue rather
          // than recorded without the tax: quietly booking one line of a batch
          // gross while the rest are split is a difference the CA would have
          // no way to see.
          if (rate !== "" && !allowed) {
            results.push({ transaction_id: t.id, status: "skipped",
              reason: `Ledger set — no GST is available on this line. ${
                GST_WHY_LONG[gstWhy({ ...t, account_id: bulkAccountId })] ?? ""} Left in the queue.` });
            return;
          }
          const post = (await api.banking.postTransaction(t.id, {
            ...(rate !== "" ? {
              gst_rate_bps: Number(rate), is_interstate: bulkGstInterstate,
            } : {}),
          })) as { success: boolean; error: string | null };
          results.push({ transaction_id: t.id,
            status: post.success ? "applied" : "failed",
            reason: post.success ? "Recorded." : (post.error ?? "Could not record.") });
        } catch (e) {
          results.push({ transaction_id: t.id, status: "failed",
            reason: e instanceof Error ? e.message : "Could not record." });
        }
      });
      setBatchOutcome({
        results,
        applied: results.filter((r) => r.status === "applied").length,
        skipped: results.filter((r) => r.status === "skipped").length,
        failed: results.filter((r) => r.status === "failed").length,
        total: results.length,
      });
      // The offer, made only from lines that were actually RECORDED. Proposing
      // a rule off lines that failed would teach the client a pattern the CA
      // never confirmed.
      const done = new Set(results.filter((r) => r.status === "applied")
                                  .map((r) => r.transaction_id));
      const coded = eligible.filter((t) => done.has(t.id));
      const pattern = commonNarrationPattern(coded.map((t) => t.description));
      if (pattern) {
        const anyCredit = coded.some((t) => t.credit_paise > 0);
        const anyDebit = coded.some((t) => t.debit_paise > 0);
        setRuleSaved(null);
        setRuleError(null);
        setRulePrompt({
          pattern,
          accountId: bulkAccountId,
          count: coded.length,
          // A rate is carried onto the rule only where the rule could hold it.
          // The backend refuses a rate on a credit-only rule (a GST rate on a
          // bank charge is money OUT), and mirroring that here avoids sending a
          // payload we already know will be rejected — the same pre-check the
          // Rules form does, for the same reason.
          gstRateBps: rate !== "" && anyDebit ? Number(rate) : null,
          isInterstate: bulkGstInterstate,
          txnType: anyCredit && anyDebit ? "any" : anyCredit ? "credit" : "debit",
        });
      }
      setBulkRows(null);
      await load();
    } catch (e) {
      setBulkError(e instanceof Error ? e.message : "Could not set the ledger.");
    } finally {
      setBulkBusy(false);
    }
  }

  /** The single action behind Match / Add: post the row and settle its document.
   *  There is no approval step any more — posting is reversible, and a queue
   *  nobody can get through is not a control. */
  async function postRow(t: QueueTxn) {
    setBusy((b) => ({ ...b, [t.id]: true }));
    setRowError((e) => ({ ...e, [t.id]: "" }));
    try {
      const rate = rateToSend(t);
      // No account_id: the ledger is already ON the row, written when it was
      // picked, and the posting engine reads it from there. Sending a browser
      // copy of it would be a second source of the same fact.
      const res = (await api.banking.postTransaction(t.id, {
        ...(rate !== "" ? {
          gst_rate_bps: Number(rate),
          is_interstate: gstInterstate[t.id] ?? !!t.suggested_is_interstate,
        } : {}),
      })) as { success: boolean; error: string | null };
      if (!res.success) { setRowError((e) => ({ ...e, [t.id]: res.error ?? "Could not post." })); return; }
      await load();
    } catch (e) {
      setRowError((x) => ({ ...x, [t.id]: e instanceof Error ? e.message : "Could not post." }));
    } finally { setBusy((b) => ({ ...b, [t.id]: false })); }
  }

  /** Accept a candidate and post it, in one click. Two requests, one decision —
   *  which is the right unit here: "yes, that is the invoice this paid". */
  async function matchAndPost(t: QueueTxn, sgg: MatchSuggestion) {
    setBusy((b) => ({ ...b, [t.id]: true }));
    setRowError((e) => ({ ...e, [t.id]: "" }));
    try {
      await api.banking.matchEntity(t.id, {
        matched_entity_type: sgg.matched_entity_type, matched_entity_id: sgg.matched_entity_id });
      const res = (await api.banking.postTransaction(t.id, {})) as
        { success: boolean; error: string | null };
      if (!res.success) { setRowError((e) => ({ ...e, [t.id]: res.error ?? "Matched, but could not post." })); }
      await load();
    } catch (e) {
      setRowError((x) => ({ ...x, [t.id]: e instanceof Error ? e.message : "Could not match." }));
    } finally { setBusy((b) => ({ ...b, [t.id]: false })); }
  }

  /** Undo. The reason it is safe to go fast: a posted row is one click from
   *  being back in the queue, so nothing needs approving in advance.
   *
   *  It called `unmatch`, which REFUSES a posted transaction — so this button,
   *  which only ever appears on posted rows, returned 409 every time it was
   *  pressed. `undoPost` reverses the journal and un-settles the document,
   *  which is what putting a posted row back actually requires. */
  async function undoRow(t: QueueTxn) {
    setBusy((b) => ({ ...b, [t.id]: true }));
    setRowError((e) => ({ ...e, [t.id]: "" }));
    try {
      await api.banking.undoPost(t.id);
      setSugg((x) => ({ ...x, [t.id]: undefined as unknown as MatchSuggestion[] }));
      await load();
    } catch (e) {
      setRowError((x) => ({ ...x, [t.id]: e instanceof Error ? e.message : "Could not undo." }));
    } finally { setBusy((b) => ({ ...b, [t.id]: false })); }
  }

  /** The candidate a row can be posted against without anyone thinking: exact
   *  amount, nothing withheld. A short one goes to the settlement drawer
   *  instead, because the shortfall is usually TDS and one click must not
   *  quietly write it off. */
  function confidentMatch(t: QueueTxn): MatchSuggestion | null {
    const list = sugg[t.id] ?? [];
    const best = list.find((x) => x.difference_paise === 0 && x.confidence >= 90);
    return best ?? null;
  }

  /** Record the picked rows. Walks them and does what a reader clicking each
   *  green button would do, three at a time — not a second code path, and no
   *  row is recorded that the screen was not already offering to record.
   *  Server-side batching would be one request instead of N, but it would also
   *  need its own copy of "which rows are confident", and two copies drift.
   *
   *  It used to take no argument and act on every ready row in the queue,
   *  driven by a green banner above the table. The banner is gone: with a
   *  selection bar that can already say "all N matching rows", a second
   *  always-on control doing a fixed subset of the same thing was one control
   *  too many. Ready-ness is not gone with it — the same test still paints the
   *  row green, and a picked row that is NOT ready is reported as skipped
   *  rather than silently passed over, which the banner could never do because
   *  the reader never chose those rows in the first place.
   */
  async function recordPicked(picked: QueueTxn[]) {
    const targets = picked.filter(readyRow);
    const results: BatchResult[] = picked
      .filter((t) => !targets.includes(t))
      .map((t) => ({
        transaction_id: t.id,
        status: "skipped" as const,
        reason: t.match_status === "posted" ? "Already recorded."
          : t.match_status === "ignored" ? "Excluded — put it back first."
          : "No ledger or document yet — open the line and choose one.",
      }));
    if (targets.length === 0) {
      setBatchOutcome({ results, applied: 0, skipped: results.length, failed: 0,
                        total: results.length });
      return;
    }
    setBulkBusy(true);
    setBulkError(null);
    try {
      await mapWithLimit(targets, 3, async (t) => {
        try {
          const best = confidentMatch(t);
          if (best && !t.matched_entity_id) {
            await api.banking.matchEntity(t.id, {
              matched_entity_type: best.matched_entity_type,
              matched_entity_id: best.matched_entity_id });
          }
          const rate = rateToSend(t);
          const res = (await api.banking.postTransaction(t.id, {
            ...(rate !== "" ? {
              gst_rate_bps: Number(rate),
              is_interstate: gstInterstate[t.id] ?? !!t.suggested_is_interstate,
            } : {}),
          })) as { success: boolean; error: string | null };
          results.push({ transaction_id: t.id,
            status: res.success ? "applied" : "failed",
            reason: res.success ? "Recorded." : (res.error ?? "Could not record.") });
        } catch (e) {
          // Per-row, never all-or-nothing: one rejected line must not strand
          // the other forty-six, and the reader has to be told WHICH failed.
          results.push({ transaction_id: t.id, status: "failed",
            reason: e instanceof Error ? e.message : "Could not record." });
        }
      });
      setBatchOutcome({
        results,
        applied: results.filter((r) => r.status === "applied").length,
        skipped: results.filter((r) => r.status === "skipped").length,
        failed: results.filter((r) => r.status === "failed").length,
        total: results.length,
      });
      await load();
    } catch (e) {
      setBulkError(e instanceof Error ? e.message : "Could not record the selected rows.");
    } finally { setBulkBusy(false); }
  }

  /** A row the screen already has an answer for — a rule fired, an exact
   *  document was found, or it is coded. The SAME test that enables its
   *  button, so the green tint and "Record all" can never disagree. */
  const readyRow = useCallback((t: QueueTxn) => (
    t.match_status !== "posted" && t.match_status !== "ignored"
    && (Boolean(confidentMatch(t)) || Boolean(t.matched_entity_id) || readyToAdd(t))
  ), [sugg]); // eslint-disable-line react-hooks/exhaustive-deps

  /** TWO verbs, not three. Match links this line to a document that already
   *  exists; Add creates the entry from a category. */
  const actionCell = (t: QueueTxn) => {
    const best = confidentMatch(t);
    const isMatch = Boolean(t.matched_entity_id) || Boolean(best);
    if (t.match_status === "posted") {
      return (
        <button onClick={() => undoRow(t)} disabled={busy[t.id]}
          className="text-[11px] px-2 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569] disabled:opacity-50">
          {busy[t.id] ? "…" : "Undo"}
        </button>
      );
    }
    if (t.match_status === "ignored") {
      return (
        <button onClick={() => setIgnored(t.id, false)} disabled={busy[t.id]}
          className="text-[11px] px-2 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569] disabled:opacity-50">
          {busy[t.id] ? "…" : "Restore"}
        </button>
      );
    }
    return (
      <button
        // A ready line posts straight away — with 47 to clear, a confirmation
        // step on every one is 47 trips through a dialogue nobody reads. A line
        // that is NOT ready opens its detail instead of sitting disabled: a
        // greyed button with a tooltip is a dead end, and the modal is where the
        // missing answer actually gets given.
        onClick={() => {
          if (!isMatch && !readyToAdd(t)) { setDetailId(t.id); return; }
          if (best && !t.matched_entity_id) { matchAndPost(t, best); return; }
          postRow(t);
        }}
        disabled={busy[t.id]}
        title={isMatch ? "Link this line to that document and record it"
          : readyToAdd(t) ? "Record this line on the books"
          : "Open this line and choose a ledger"}
        className={`text-[11px] px-3 py-1 rounded font-medium text-white disabled:opacity-40 disabled:cursor-not-allowed ${
          isMatch ? "bg-[#059669] hover:bg-[#047857]" : "bg-[#4338CA] hover:bg-[#3730A3]"}`}>
        {busy[t.id] ? "…" : isMatch ? "Match" : "Add"}
      </button>
    );
  };

  /** Categorized and Excluded hold rows nothing can be set on any more, so a
   *  GST column there is a column of dashes. It is dropped from those views
   *  entirely rather than rendered empty — the first version shipped it on
   *  every tab and it read as a broken feature. */
  const showGstColumn = status !== "done" && status !== "ignored";

  /** The columns. `accessor` is what search, sort and CSV export read, so it
   *  is the plain value; `render` is what the reader sees. Money stays in
   *  paise for sorting and is formatted only in the cell. */
  const queueColumns: Column<QueueTxn>[] = [
    {
      key: "transaction_date", header: "Date", width: "7rem", sortable: true, hideable: false,
      accessor: (t) => t.transaction_date,
      render: (t) => <span className="text-[#64748B] whitespace-nowrap tabular-nums">{t.transaction_date}</span>,
    },
    {
      key: "description", header: "Description", sortable: true, searchable: true, hideable: false,
      accessor: (t) => t.parsed?.counterparty || t.description,
      // HOVER for the raw narration — a tooltip is less work than opening the
      // row, and it is what QuickBooks does.
      render: (t) => (
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="truncate font-medium text-[#1E293B]" title={t.description}>
            {t.parsed?.counterparty || t.description}
          </span>
          {t.parsed?.channel && (
            <span className="shrink-0 text-[9px] px-1 py-0.5 rounded bg-[#F1F5F9] text-[#64748B]">
              {t.parsed.channel}
            </span>
          )}
          {t.transfer_pair_id && (
            <span className="shrink-0 text-[9px] px-1 py-0.5 rounded bg-indigo-50 text-indigo-700"
              title={t.transfer_is_primary
                ? "Paying side — this one posts the journal"
                : "Receiving side — the paying side posts it"}>
              Transfer
            </span>
          )}
          {/* The ONE status the removed Ledger column cannot be allowed to
              take with it. A split line reads exactly like an untouched one —
              null category, null account_id — and it is already allocated, so
              a reader who cannot see that may open it and code it as if it
              were blank. A chip beside the narration, next to the Transfer one
              that set the precedent: not a control, and not a column. */}
          {t.is_split && (
            <span className="shrink-0 text-[9px] px-1 py-0.5 rounded bg-[#EEF2FF] text-[#4338CA]"
              title={`Allocated across ${t.split_count ?? 0} ledgers — open the line to see them`}>
              Split
            </span>
          )}
          {/* WHAT A RULE PROPOSES FOR THIS LINE, on the line.
              It used to show as the ledger picker's placeholder —
              "Suggested: Bank Charges" — and removing that column removed the
              only place a suggestion was ever visible. Apply suggestions then
              became a blind write: press it and N lines are coded from rules
              and history with no way to see, beforehand, which lines had a
              suggestion or what it was. Reported by the CA in those words.

              Grey and unemphatic because it is a PROPOSAL, and only on a line
              that has not been coded — once the CA has answered, the machine's
              opinion is no longer news. */}
          {!t.account_id && !t.is_split && t.suggested_account_id && (
            <span className="shrink-0 text-[10px] text-[#94A3B8] truncate"
              title={t.suggested_by_rule
                ? `Rule “${t.suggested_by_rule}” proposes ${accountLabel(t.suggested_account_id)}`
                : `Proposed: ${accountLabel(t.suggested_account_id)}`}>
              → {accountLabel(t.suggested_account_id)}
            </span>
          )}
        </div>
      ),
    },
    {
      key: "payee", header: "Payee", width: "10rem", sortable: true, searchable: true,
      accessor: (t) => t.payee_name ?? t.suggested_payee?.payee_name ?? "",
      render: (t) => t.payee_name
        ? <span className="truncate block text-[#334155]" title={t.payee_name}>{t.payee_name}</span>
        : t.suggested_payee
          // Greyed and italic so a PROPOSAL never reads as a fact the CA asserted.
          ? <span className="truncate block text-[#94A3B8] italic"
              title={`Suggested from the ${t.suggested_payee.source === "narration" ? "narration" : "matched party"}`}>
              {t.suggested_payee.payee_name}
            </span>
          : <span className="text-[#CBD5E1]">—</span>,
    },
    // NO LEDGER COLUMN. It held the picker, and before that a Category
    // dropdown; the CA read the line as "not presentable" twice — the second
    // time after using the built version. The line asks NOTHING now. It
    // reports what the bank sent and what moved, and every answer is given in
    // the detail modal, reached by clicking the line, or by pressing Add on a
    // line that has no answer yet (actionCell opens the modal rather than
    // sitting disabled).
    //
    // WHAT WAS GIVEN UP, deliberately and said out loud: that column was also
    // the STATUS column — "Recorded · Cost of Goods Sold", "Matched · invoice",
    // "Split across 3 ledgers". The list no longer says what a line was coded
    // to. What is left to read it by is the green tint on a ready row
    // (readyRow — the same test that enables its button), the button's own
    // word (Match on a line with a document, Add on one without), and the
    // Categorized tab. That is the trade the CA chose, in those terms.
    {
      // GST on the line, the way a CA reads a statement: one column, both
      // directions, their call. It used to live inside the opened row, offered
      // on every unmatched DEBIT — including rows the server would then refuse,
      // and never on a receipt at all, so a banked cash sale could not be
      // recorded with its output tax.
      //
      // `gst_allowed` is the SERVER's answer (posting_map.gst_split_allowed),
      // not a rule re-derived here: a control that appears where the post would
      // be rejected is worse than no control.
      // DEFAULT-HIDDEN, and one click away in the Columns menu. On the tab
      // where the work happens this column is placeholder text: on an uncoded
      // queue every cell reads "pick a ledger", because a rate needs a ledger
      // to book the ex-tax amount to. It is also already dropped entirely from
      // Categorized and Excluded, so hiding it here makes the three tabs agree.
      // The rate is set in the detail modal, where it has a label and the room
      // to say which section it is claimed under.
      key: "gst", header: "GST", width: "7rem", defaultHidden: true,
      accessor: (t) => gstRate[t.id] ?? (t.suggested_gst_rate_bps ?? ""),
      render: (t) => {
        // A READ-OUT, not a control. A select and a checkbox squeezed beside a
        // ledger picker is what made the line look like a form; the rate is set
        // in the detail modal, where it has a label and room to explain itself.
        if (!t.gst_allowed) {
          const why = gstWhy(t);
          return <span className="text-[#CBD5E1] text-[10px]" title={GST_WHY_LONG[why]}>{why}</span>;
        }
        const rate = gstRate[t.id] ?? (t.suggested_gst_rate_bps != null
          ? String(t.suggested_gst_rate_bps) : "");
        if (rate === "") return <span className="text-[#CBD5E1] text-[10px]">none</span>;
        const inter = gstInterstate[t.id] ?? !!t.suggested_is_interstate;
        return (
          <span className="text-[11px] text-[#334155]" title="Set the rate in the line's detail">
            {inter && rate !== "0" ? "IGST " : ""}{Number(rate) / 100}%
          </span>
        );
      },
    },
    // Spent and Received as SEPARATE columns, not one with Dr/Cr: money out and
    // money in are the two things the eye separates first.
    {
      key: "spent", header: "Spent", width: "8rem", align: "right", sortable: true,
      accessor: (t) => t.debit_paise,
      exportValue: (t) => t.debit_paise / 100,
      render: (t) => <span className="font-mono text-red-700">{t.debit_paise > 0 ? fmt(t.debit_paise) : ""}</span>,
    },
    {
      key: "received", header: "Received", width: "8rem", align: "right", sortable: true,
      accessor: (t) => t.credit_paise,
      exportValue: (t) => t.credit_paise / 100,
      render: (t) => <span className="font-mono text-green-700">{t.credit_paise > 0 ? fmt(t.credit_paise) : ""}</span>,
    },
  ];
  const visibleQueueColumns: Column<QueueTxn>[] =
    queueColumns.filter((c) => c.key !== "gst" || showGstColumn);

  /** Across LEDGERS or across DOCUMENTS. Rendered inside whichever split
   *  editor is open, so the two are one control in one place rather than two
   *  buttons on the row competing for the same word. Prefill forces the
   *  document side — a short match arrived with an invoice already in hand. */
  const splitModeSwitch = (
    <div className="inline-flex rounded-lg border border-[#E2E8F0] overflow-hidden" role="tablist"
      aria-label="What to split this line across">
      {([
        ["ledgers", "Across ledgers"],
        ["documents", splitTxn && splitTxn.credit_paise > 0 ? "Across invoices" : "Across bills"],
      ] as const).map(([mode, label]) => (
        <button
          key={mode} type="button" role="tab" aria-selected={splitMode === mode}
          onClick={() => setSplitMode(mode as "ledgers" | "documents")}
          className={`text-xs px-3 py-1.5 font-medium ${
            splitMode === mode
              ? "bg-[#4338CA] text-white"
              : "bg-white text-[#475569] hover:bg-[#F8FAFC]"}`}>
          {label}
        </button>
      ))}
    </div>
  );

  /** Which of the picked lines a ledger can be set on, and what is left
   *  alone. A posted line needs Undo first, an excluded one needs putting
   *  back, and a split line already HAS its ledgers — writing one over that
   *  allocation would replace an answer the CA has already given. */
  const bulkEligible = (picked: QueueTxn[]) => picked.filter(
    (t) => t.match_status !== "posted" && t.match_status !== "ignored" && !t.is_split);

  /** A rate is offered only when EVERY line could take one.
   *
   *  `gst_allowed` is false on an uncoded line for exactly the reason choosing
   *  a ledger fixes, so the test is "nothing but the missing ledger is in the
   *  way". A line blocked because it settles an invoice, or because it is a
   *  transfer, never becomes eligible whatever ledger is picked — and one rate
   *  applied across a mixed selection would tax the invoice line a second
   *  time, on top of the tax the invoice already carries (CGST Act s.16). */
  const bulkGstOffered = (eligible: QueueTxn[]) =>
    eligible.length > 0
    && eligible.every((t) => t.gst_allowed || gstWhy(t) === "pick a ledger");

  /** What a line still has to say for itself, if anything. A rule fired
   *  (suggested_account_id), history knows the payee (suggested_payee), or a
   *  document was found — all three are on the row, so the bar can tell
   *  BEFORE the click whether Apply suggestions has anything to accept. */
  const hasSomethingToAccept = (t: QueueTxn) =>
    t.match_status !== "posted" && t.match_status !== "ignored"
    // AND STILL MISSING WHAT THE SUGGESTION WOULD FILL. The first version asked
    // only "does this line have a suggestion?", so the button appeared on a
    // line that was already coded and then reported "Already coded — nothing
    // was changed" — which is the same dead button the guard was added to
    // remove, one step further along. batch_accept fills a field only when it
    // is empty, and this is that rule read back.
    && !t.account_id && !t.is_split
    && (Boolean(t.suggested_account_id) || Boolean(t.suggested_payee)
        || Boolean(t.matched_entity_id) || Boolean(confidentMatch(t)));

  /** The bulk bar, and every entry says when it applies.
   *
   *  It used to offer all five actions on all three tabs. On Categorized that
   *  meant Set ledger, Record, Apply suggestions, Exclude and Put back — five
   *  buttons, not one of which a recorded line can take — while Undo, the only
   *  thing anyone wants there, was missing entirely. Pressing one was not an
   *  error: it completed and reported "0 applied · 6 skipped", which reads as a
   *  broken button rather than an inapplicable one. Reported exactly that way.
   *
   *  So each action now states the rows it needs, and DataTable renders only
   *  the ones the current selection satisfies. What that produces per tab:
   *    For review  — Set ledger, Exclude, plus Record and Apply suggestions
   *                  when something selected is actually ready or suggested
   *    Categorized — Undo
   *    Excluded    — Put back
   */
  const queueBulkActions: BulkAction<QueueTxn>[] = [
    {
      // Opens the modal rather than acting: the ledger is the question, and a
      // toolbar dropdown that had to be set BEFORE selecting rows was a
      // control you could press with nothing chosen and be told off for it.
      //
      // DataTable clears its selection as soon as a bulk action resolves, and
      // this one resolves on open — so the ticks are gone by the time the
      // modal is up, and cancelling means re-ticking. That is the honest cost
      // of not abusing the one thing that preserves a selection, which is a
      // THROWN error: a CA changing their mind is not a crash, and logging it
      // as one to buy back four checkboxes is a worse trade.
      id: "set-ledger",
      label: "Set ledger",
      appliesTo: (picked) => bulkEligible(picked).length > 0,
      run: (picked) => {
        setBulkRows(picked);
        setBulkAccountId("");
        setBulkGstRate("");
        setBulkGstInterstate(false);
        setBulkError(null);
      },
    },
    {
      // Where "Record all N" used to live, as a green banner permanently above
      // the table. The banner acted on a set the reader had not chosen and
      // could not see the edges of; this acts on the rows they ticked, and
      // reports the ones it would not record instead of skipping them in
      // silence.
      //
      // It appears only where something IS ready. Asked why it existed at all
      // next to Set ledger — a fair question, since Set ledger records what it
      // codes. The answer is the line that needs no ledger: one already matched
      // to an invoice, or already carrying a rule's answer. On a queue with
      // none of those, the button was pure noise, and now it is absent.
      id: "record",
      label: "Record",
      appliesTo: (picked) => picked.some(readyRow),
      run: async (picked) => { await recordPicked(picked); },
    },
    {
      // PREVIEWS, then writes on a second click. It used to code every selected
      // line on the first press and report "20 applied" — a CA answerable for
      // each of those lines could not see beforehand which had a suggestion or
      // what it was, and could not see afterwards which ledger went where.
      id: "apply-suggestions",
      label: "Apply suggestions",
      appliesTo: (picked) => picked.some(hasSomethingToAccept),
      run: async (picked) => { await previewSuggestions(picked); },
    },
    {
      // The Categorized tab's reason to exist. undo reverses the journal and
      // un-settles the document — never a delete.
      id: "undo",
      label: "Undo",
      appliesTo: (picked) => picked.some((t) => t.match_status === "posted"),
      run: async (picked) => { await undoPicked(picked); },
    },
    {
      id: "exclude",
      label: "Exclude",
      appliesTo: (picked) => picked.some(
        (t) => t.match_status !== "posted" && t.match_status !== "ignored"),
      run: async (picked) => { await runBatchIds("exclude", picked.map((t) => t.id)); },
    },
    {
      // Only on the Excluded tab, which is the only place an excluded line is.
      id: "include",
      label: "Put back",
      appliesTo: (picked) => picked.some((t) => t.match_status === "ignored"),
      run: async (picked) => { await runBatchIds("include", picked.map((t) => t.id)); },
    },
  ];

  /** Whether Add can post this row as it stands.
   *
   *  Reads the SERVER's row and nothing else. It used to also consult a
   *  browser-side draft of the account, which meant the button could be live
   *  for a choice that existed only on this screen — and dead for one the row
   *  already carried. The ledger is written when it is picked, so there is no
   *  draft to consult any more. */
  function readyToAdd(t: QueueTxn): boolean {
    // A split line already says where every paisa goes — that IS the answer,
    // and it needs no category: bank_posting_service builds the n-leg journal
    // from the splits and never consults one. Without this the allocation
    // could be saved and then never posted, which is the worst of both.
    if (t.is_split) return true;
    const cat = t.category;
    if (!cat) return false;
    // A transfer needs a destination: either the counterpart line, confirmed as
    // a pair, or the other bank/cash ledger picked directly.
    if (cat === "Transfer") return Boolean(t.transfer_pair_id || t.account_id);
    if (AUTO_COUNTER_CATEGORIES.has(cat)) return true;
    return Boolean(t.account_id);
  }

  async function reject(id: string) {
    setBusy((b) => ({ ...b, [id]: true }));
    setRowError((e) => ({ ...e, [id]: "" }));
    try { await api.banking.unmatch(id); setSugg((s) => ({ ...s, [id]: [] })); await load(); }
    catch (e) { setRowError((x) => ({ ...x, [id]: e instanceof Error ? e.message : "Could not unmatch." })); }
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
      // Coding a row does not move it between views, so the row is patched in
      // place — the same reason codeToAccount stopped calling load().
      if (t.suggested_account_id) {
        const res = (await api.banking.setTransactionAccount(
          t.id, { account_id: t.suggested_account_id })) as { data?: Partial<QueueTxn> };
        patchRow(t.id, { ...(res?.data ?? {}), account_id: t.suggested_account_id,
                         category: t.suggested_category ?? t.category });
      } else {
        patchRow(t.id, { category: t.suggested_category ?? t.category });
      }
    } catch (e) { alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy((b) => ({ ...b, [t.id]: false })); }
  }
  // Tier 1.7 — one action over the checked rows. The outcome panel below shows
  // what happened to EACH row rather than a count, because some legitimately
  // fail and a silent partial success leaves transactions uncoded.
  async function runBatchIds(kind: "accept" | "exclude" | "include", ids: string[]) {
    if (ids.length === 0) return;
    setBulkBusy(true); setBulkError(null); setBatchOutcome(null);
    try {
      const fn = kind === "accept" ? api.banking.batchAccept
        : kind === "exclude" ? api.banking.batchExclude : api.banking.batchInclude;
      const res = (await fn(ids)) as { success: boolean; data: BatchOutcome; error: string | null };
      if (!res.success) throw new Error(res.error ?? "The batch action failed.");
      setBatchOutcome(res.data);
      await load();
    } catch (e) {
      setBulkError(e instanceof Error ? e.message : "The batch action failed.");
    } finally { setBulkBusy(false); }
  }

  // Tier 1.5 — detected transfer pairs for this client.
  const loadTransfers = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    try {
      const res = (await api.banking.transferSuggestions({ client_id: clientId })) as
        { success: boolean; data: TransferSuggestion[] };
      setTransfers(res.success ? (res.data ?? []) : []);
    } catch {
      setTransfers([]);   // a missing suggestion must never break the queue
    }
  }, [clientId]);
  useEffect(() => { loadTransfers(); }, [loadTransfers]);

  async function confirmTransfer(p: TransferSuggestion) {
    setBusy((b) => ({ ...b, [p.primary_id]: true }));
    try {
      await api.banking.pairTransfer(p.primary_id, p.counterpart_id);
      await Promise.all([load(), loadTransfers()]);
    } catch (e) { alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy((b) => ({ ...b, [p.primary_id]: false })); }
  }
  async function undoTransfer(t: QueueTxn) {
    setBusy((b) => ({ ...b, [t.id]: true }));
    try {
      await api.banking.unpairTransfer(t.id);
      await Promise.all([load(), loadTransfers()]);
    } catch (e) { alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy((b) => ({ ...b, [t.id]: false })); }
  }

  // Tier 1.3 — confirm the payee the parser proposed. A separate click from
  // coding it: naming who you paid and deciding which account it belongs to are
  // two different judgements, and one should not silently carry the other.
  async function acceptPayee(t: QueueTxn) {
    if (!t.suggested_payee) return;
    setBusy((b) => ({ ...b, [t.id]: true }));
    try {
      await api.banking.setPayee(t.id, {
        payee_name: t.suggested_payee.payee_name,
        payee_type: t.suggested_payee.payee_type,
        payee_id: t.suggested_payee.payee_id ?? undefined,
      });
      await load();
    } catch (e) { alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy((b) => ({ ...b, [t.id]: false })); }
  }
  async function clearPayee(t: QueueTxn) {
    setBusy((b) => ({ ...b, [t.id]: true }));
    try {
      await api.banking.setPayee(t.id, { payee_name: "" });
      await load();
    } catch (e) { alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy((b) => ({ ...b, [t.id]: false })); }
  }

  // Tier 1.4 — take the coding this payee got last time. Explicit, like every
  // other suggestion in this module: history proposes, the CA disposes.
  async function applyHistory(t: QueueTxn) {
    if (!t.history) return;
    setBusy((b) => ({ ...b, [t.id]: true }));
    try {
      if (t.history.category) await api.banking.categorize(t.id, { category: t.history.category });
      if (t.history.account_id) {
        const res = (await api.banking.setTransactionAccount(
          t.id, { account_id: t.history.account_id })) as { data?: Partial<QueueTxn> };
        patchRow(t.id, { ...(res?.data ?? {}), account_id: t.history.account_id,
                         category: t.history.category ?? t.category });
      } else {
        patchRow(t.id, { category: t.history.category ?? t.category });
      }
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

  // Names a learned account. History returns ids; a CA reading "coded to
  // 3f2a-…" learns nothing, so fall back to the id only when the account is
  // genuinely not in this client's chart.
  const accountLabel = (id: string | null) => {
    if (!id) return "";
    const a = accounts.find((x) => x.id === id);
    return a ? a.account_name : id.slice(0, 8);
  };


  return (
    <div className="space-y-4 max-w-6xl mx-auto">
      <div className="flex gap-1 bg-[#F1F5F9] p-1 rounded-lg w-fit">
        {QUEUE_FILTERS.map((f) => (
          <button key={f.id} onClick={() => setStatus(f.id)}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${status === f.id ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"}`}>
            {f.label}
          </button>
        ))}
      </div>

      {/* Tier 1.5 — one movement between the client's own accounts lands on two
          statements. Coded separately it becomes two journals and double the
          apparent activity, so pairing them is the point: only the paying side
          will post, because that journal already carries both legs. */}
      {transfers.length > 0 && (
        <div className="bg-white rounded-xl border border-[#E2E8F0] overflow-hidden">
          <div className="px-4 py-2.5 bg-[#F8FAFC] border-b border-[#F1F5F9]">
            <p className="text-xs font-semibold text-[#334155]">
              {transfers.length} possible transfer{transfers.length === 1 ? "" : "s"} between this
              client&apos;s own accounts
            </p>
            <p className="text-[10px] text-[#64748B] mt-0.5">
              Confirming records both lines as one movement. Only the paying side posts —
              otherwise the same money would be counted twice.
            </p>
          </div>
          <div className="divide-y divide-[#F8FAFC]">
            {transfers.map((p) => (
              <div key={`${p.primary_id}-${p.counterpart_id}`}
                   className="px-4 py-2.5 flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-[#1E293B]">
                    <span className="font-mono">{fmt(p.amount_paise)}</span> out on{" "}
                    {p.primary_date} → in on {p.counterpart_date}
                  </p>
                  <p className={`text-[10px] mt-0.5 ${
                    p.is_unambiguous ? "text-[#94A3B8]" : "text-amber-700"}`}>
                    {p.summary}
                  </p>
                </div>
                <span className={`text-[9px] px-1.5 py-0.5 rounded-full shrink-0 ${
                  p.confidence === "high" ? "bg-green-50 text-green-700"
                    : p.confidence === "medium" ? "bg-amber-50 text-amber-700"
                    : "bg-[#F1F5F9] text-[#64748B]"}`}>
                  {p.confidence}
                </span>
                <button onClick={() => confirmTransfer(p)} disabled={busy[p.primary_id]}
                  className="text-[10px] px-2 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569] shrink-0">
                  Confirm transfer
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {loading ? <TransactionListSkeleton rows={4} /> : loadError ? (
        <div className="bg-white rounded-xl border border-red-200 p-10 text-center">
          <p className="text-sm text-red-600 font-medium mb-2">{loadError}</p>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      ) : rows.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-10 text-center text-sm text-[#94A3B8]">No transactions in this view.</div>
      ) : (
        <>
          {bulkError && <p className="text-[11px] text-red-600 px-1">{bulkError}</p>}

          {/* THE OFFER, made at the only moment the CA knows the answer without
              being asked to invent it: they have just coded several real lines
              to one ledger. The Rules tab could always do this, but it asks for
              a pattern up front — which means guessing what next month's
              narration will look like, from memory, in a form. Here the pattern
              is read off the lines themselves, shown, and editable before
              anything is saved. Nothing is created without the click. */}
          {rulePrompt && (
            <div className="rounded-lg border border-[#C7D2FE] bg-[#EEF2FF] px-3 py-2 space-y-2">
              <p className="text-xs text-[#3730A3]">
                Recorded <span className="font-semibold">{rulePrompt.count}</span> lines to{" "}
                <span className="font-semibold">{accountLabel(rulePrompt.accountId)}</span>.
                Should next month&apos;s do it themselves?
              </p>
              <div className="flex items-center gap-2 flex-wrap">
                <label htmlFor="rule-pattern" className="text-[11px] text-[#475569]">
                  Lines whose narration contains
                </label>
                <input
                  id="rule-pattern"
                  value={rulePrompt.pattern}
                  disabled={ruleSaving}
                  onChange={(e) => setRulePrompt((r) => (r ? { ...r, pattern: e.target.value } : r))}
                  className="px-2 py-1 text-xs font-mono border border-[#C7D2FE] rounded bg-white min-w-[16rem] flex-1"
                />
                <button onClick={createRuleFromPrompt} disabled={ruleSaving}
                  className="text-xs px-3 py-1.5 rounded-lg font-medium text-white bg-[#4338CA] hover:bg-[#3730A3] disabled:opacity-40">
                  {ruleSaving ? "Saving…" : "Create rule"}
                </button>
                <button onClick={() => setRulePrompt(null)} disabled={ruleSaving}
                  className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg text-[#475569] hover:bg-white disabled:opacity-40">
                  Not now
                </button>
              </div>
              <p className="text-[10px] text-[#64748B]">
                A rule only SUGGESTS — it proposes the ledger
                {rulePrompt.gstRateBps != null && <> and the {rulePrompt.gstRateBps / 100}% GST split</>}
                {" "}on a matching line and waits for you. It never records anything by itself.
              </p>
              {ruleError && <p className="text-[10px] text-red-600">{ruleError}</p>}
            </div>
          )}

          {ruleSaved && (
            <p className="text-[11px] text-[#166534] px-1">
              Rule saved. Lines containing <span className="font-mono">{ruleSaved}</span> will
              arrive with the ledger already suggested — clear them with Apply suggestions.
              {" "}Edit or delete it in the Rules tab.
            </p>
          )}

          {/* Tier 1.7 — what happened to EACH row. A count alone would hide the
              two that did not apply, and those are the ones needing attention. */}
          {batchOutcome && (
            <div className="bg-white rounded-xl border border-[#E2E8F0] overflow-hidden">
              <div className="px-4 py-2 bg-[#F8FAFC] border-b border-[#F1F5F9] flex items-center justify-between">
                <p className="text-[11px] text-[#334155]">
                  <span className="font-semibold">{batchOutcome.applied}</span> applied
                  {batchOutcome.skipped > 0 && <> · {batchOutcome.skipped} skipped</>}
                  {batchOutcome.failed > 0 && <> · <span className="text-red-700">{batchOutcome.failed} failed</span></>}
                  {" "}of {batchOutcome.total}
                </p>
                <button onClick={() => setBatchOutcome(null)}
                  className="text-[#94A3B8] hover:text-[#475569]" aria-label="Dismiss batch result">
                  <X size={13} />
                </button>
              </div>
              {/* EVERY row, not only the ones that did not go through. It used
                  to list failures and skips alone, which is right for "record
                  these" — a recorded line is visibly gone from the queue — and
                  wrong for a CODING action: the whole question a CA has after
                  Apply suggestions is which ledger landed on which line, and
                  the answer was nowhere on screen. Rows that named a ledger
                  say so; the rest read as before. */}
              {batchOutcome.results.length > 0 && (
                <div className="divide-y divide-[#F8FAFC] max-h-48 overflow-y-auto">
                  {batchOutcome.results
                    .filter((r) => r.status !== "applied" || r.account_id || r.category)
                    .map((r) => (
                    <p key={r.transaction_id} className="px-4 py-1.5 text-[10px] text-[#64748B]">
                      <span className={`font-medium ${
                        r.status === "failed" ? "text-red-700"
                          : r.status === "applied" ? "text-[#15803D]" : "text-amber-700"}`}>
                        {r.status}
                      </span>
                      {r.description ? <> — <span className="text-[#334155]">{r.description}</span></> : null}
                      {r.status === "applied" && r.account_id
                        ? <> → <span className="font-medium text-[#0F172A]">{accountLabel(r.account_id)}</span>
                            {r.source ? <span className="text-[#94A3B8]"> ({r.source})</span> : null}</>
                        : <>{" — "}{r.reason}</>}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* The SHARED table, so this screen gets search, column visibility,
              CSV export and a page-size control without a second
              implementation of any of them. `serverPaged` carries the search
              to the SERVER: the rows here are one page, and a box that
              filtered them would call a line on page four "no match". */}
          <DataTable
            data={rows}
            columns={visibleQueueColumns}
            getRowId={(t) => t.id}
            loading={loading}
            searchPlaceholder="Search narration, reference or payee…"
            // BUMPED from "bank.categorize". Hidden columns are persisted, and
            // a saved pref of "nothing hidden" wins over a column's own
            // defaultHidden on hydration — so anyone who had already used this
            // screen would keep the GST column and never see the change. The
            // cost is one reset of saved widths and page size, once.
            persistKey="bank.categorize.v2"
            emptyTitle="Nothing in this view"
            emptyDescription="Statement lines land here once a statement is imported."
            rowClassName={(t) => (readyRow(t) ? "bg-[#F0FDF4] hover:bg-[#DCFCE7]" : "")}
            // Clicking a line opens the detail MODAL rather than expanding the row.
            // The panel had grown to a dozen controls stacked under a table row,
            // which is what made the line itself look unpresentable. The row is one
            // control now, and everything needing thought lives in the modal.
            onRowClick={(t) => setDetailId(t.id)}
            rowActions={(t) => actionCell(t)}
            bulkActions={queueBulkActions}
            serverPaged={{
              total,
              offset: page * pageSize,
              pageSize,
              busy: loading,
              search,
              onSearchChange: setSearch,
              onChange: ({ offset, pageSize: size }) => {
                setPageSize(size);
                setPage(Math.floor(offset / size));
              },
            }}
          />
        </>
      )}
      <p className="text-[10px] text-[#94A3B8] text-center">
        Click a line to choose its ledger, split it, or read the bank&apos;s own narration.
        Match or Add posts it and settles its document; Undo puts it back.
      </p>
      {/* WHAT APPLY SUGGESTIONS IS ABOUT TO DO, before it does it. Every row
          here came from the server's dry run of the same function that will
          run on Apply, so this list cannot disagree with what lands. */}
      {preview && (() => {
        const willChange = preview.rows.filter((r) => r.status === "would_apply");
        const leftAlone = preview.rows.filter((r) => r.status !== "would_apply");
        return (
          <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4"
               onClick={() => !bulkBusy && setPreview(null)}>
            <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col"
                 onClick={(e) => e.stopPropagation()}>
              <div className="flex items-start justify-between px-5 py-4 border-b border-[#F1F5F9]">
                <div>
                  <h3 className="text-sm font-semibold text-[#0F172A]">
                    {willChange.length === 0
                      ? "Nothing to apply"
                      : `${willChange.length} line${willChange.length === 1 ? "" : "s"} would be coded`}
                  </h3>
                  <p className="text-xs text-[#64748B] mt-0.5">
                    From rules you wrote and how you coded these payees before.
                    Nothing is written until you apply.
                  </p>
                </div>
                <button onClick={() => setPreview(null)} disabled={bulkBusy} aria-label="Close"
                  className="text-[#94A3B8] hover:text-[#475569] shrink-0 disabled:opacity-40">
                  <X size={16} />
                </button>
              </div>

              <div className="overflow-y-auto flex-1">
                {willChange.length > 0 && (
                  <table className="w-full text-xs">
                    <thead className="bg-[#F8FAFC] text-[#64748B]">
                      <tr>
                        <th className="text-left font-medium px-5 py-2">Line</th>
                        <th className="text-left font-medium px-3 py-2">Ledger</th>
                        <th className="text-left font-medium px-5 py-2">From</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#F8FAFC]">
                      {willChange.map((r) => (
                        <tr key={r.transaction_id}>
                          <td className="px-5 py-2 text-[#1E293B] max-w-[18rem] truncate"
                              title={r.description ?? ""}>{r.description}</td>
                          <td className="px-3 py-2 font-medium text-[#0F172A]">
                            {r.account_id ? accountLabel(r.account_id) : (r.category ?? "—")}
                          </td>
                          {/* Whose authority. A rule the CA wrote reads
                              differently from a habit the machine noticed, and
                              they should not look the same. */}
                          <td className="px-5 py-2 text-[#64748B]">{r.source}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {leftAlone.length > 0 && (
                  <div className="px-5 py-3 border-t border-[#F1F5F9] bg-[#FCFCFD]">
                    <p className="text-[11px] font-medium text-[#475569] mb-1">
                      {leftAlone.length} left alone
                    </p>
                    {/* The refusals, named. "12 selected, 6 coded" leaves the
                        other six unaccounted for, and unaccounted-for lines are
                        what sit uncoded until year end. */}
                    <ul className="space-y-0.5">
                      {leftAlone.map((r) => (
                        <li key={r.transaction_id} className="text-[10px] text-[#64748B] truncate"
                            title={`${r.description ?? ""} — ${r.reason}`}>
                          {r.description} — {r.reason}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-[#F1F5F9]">
                <button onClick={() => setPreview(null)} disabled={bulkBusy}
                  className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg text-[#475569] hover:bg-[#F8FAFC] disabled:opacity-40">
                  Cancel
                </button>
                <button
                  onClick={async () => {
                    const ids = preview.ids;
                    setPreview(null);
                    await runBatchIds("accept", ids);
                  }}
                  disabled={bulkBusy || willChange.length === 0}
                  className="text-xs px-4 py-1.5 rounded-lg font-medium text-white bg-[#4338CA] hover:bg-[#3730A3] disabled:opacity-40 disabled:cursor-not-allowed">
                  {bulkBusy ? "Applying…" : `Apply to ${willChange.length} line${willChange.length === 1 ? "" : "s"}`}
                </button>
              </div>
            </div>
          </div>
        );
      })()}

      {/* BULK — the same two questions the detail modal asks, asked once for
          many lines. Same picker, same rate list, same words, so "set the
          ledger" means one thing on this screen whether it is one line or
          eight. What it replaced set a category and no ledger; see
          applyBulkLedger. */}
      {bulkRows && (() => {
        const picked = bulkRows;
        const eligible = bulkEligible(picked);
        const gstOffered = bulkGstOffered(eligible);
        const gross = eligible.reduce(
          (n, t) => n + (t.credit_paise > 0 ? t.credit_paise : t.debit_paise), 0);
        // The FIRST line that can never take a rate, whatever ledger is
        // chosen. Named in the modal so "no GST here" is a reason and not a
        // missing control.
        const blocker = eligible.find((t) => !t.gst_allowed && gstWhy(t) !== "pick a ledger");
        return (
          <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4"
               onClick={() => !bulkBusy && setBulkRows(null)}>
            <div className="bg-white rounded-xl shadow-xl w-full max-w-lg flex flex-col"
                 onClick={(e) => e.stopPropagation()}>
              <div className="flex items-start justify-between px-5 py-4 border-b border-[#F1F5F9]">
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-[#0F172A]">
                    Set the ledger on {eligible.length} line{eligible.length === 1 ? "" : "s"}
                  </h3>
                  <p className="text-xs text-[#64748B] mt-0.5">
                    <span className="font-mono">{fmt(gross)}</span> in total
                    {picked.length > eligible.length && (
                      <span className="text-[#94A3B8]">
                        {" · "}{picked.length - eligible.length} of the {picked.length} selected
                        {" "}left alone (already recorded, excluded, or split)
                      </span>
                    )}
                  </p>
                </div>
                <button onClick={() => setBulkRows(null)} disabled={bulkBusy} aria-label="Close"
                  className="text-[#94A3B8] hover:text-[#475569] shrink-0 disabled:opacity-40">
                  <X size={16} />
                </button>
              </div>

              <div className="px-5 py-4 space-y-3">
                <div>
                  <label className="block text-[11px] font-medium text-[#475569] mb-1">
                    Ledger
                  </label>
                  <AccountLookup
                    accounts={orderedAccounts}
                    value={bulkAccountId}
                    onChange={setBulkAccountId}
                    disabled={bulkBusy}
                    ariaLabel="Ledger for the selected lines"
                    placeholder="Choose a ledger…"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-[#475569] mb-1">
                    GST inside these amounts
                  </label>
                  {gstOffered ? (
                    <div className="flex items-center gap-3 flex-wrap">
                      <select
                        value={bulkGstRate}
                        disabled={bulkBusy}
                        onChange={(e) => setBulkGstRate(e.target.value)}
                        aria-label="GST rate for the selected lines"
                        className="px-2 py-1.5 text-xs border border-[#E2E8F0] rounded-lg bg-white">
                        <option value="">No GST split</option>
                        {GST_RATE_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>{o.label}</option>
                        ))}
                      </select>
                      {bulkGstRate !== "" && bulkGstRate !== "0" && (
                        <label className="flex items-center gap-1.5 text-xs text-[#475569]">
                          <input type="checkbox" disabled={bulkBusy}
                            checked={bulkGstInterstate}
                            onChange={(e) => setBulkGstInterstate(e.target.checked)}
                            className="h-3.5 w-3.5 rounded border-[#CBD5E1]" />
                          IGST (inter-state)
                        </label>
                      )}
                      <span className="text-[10px] text-[#94A3B8]">
                        One rate, applied to every line here
                      </span>
                    </div>
                  ) : (
                    <p className="text-[11px] text-[#94A3B8]">
                      {blocker
                        ? `Not for this selection — ${GST_WHY_LONG[gstWhy(blocker)] ?? "one of these lines cannot take a rate."} Set the ledger here and give that line its rate on its own.`
                        : "Nothing here can take a rate."}
                    </p>
                  )}
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-[#F1F5F9]">
                <button onClick={() => setBulkRows(null)} disabled={bulkBusy}
                  className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg text-[#475569] hover:bg-[#F8FAFC] disabled:opacity-40">
                  Cancel
                </button>
                <button
                  onClick={applyBulkLedger}
                  disabled={bulkBusy || !bulkAccountId || eligible.length === 0}
                  // Says what it does. Add on the row posts straight away, and
                  // a bulk button that only half-did the same thing would leave
                  // eight lines still needing a second pass.
                  className="text-xs px-4 py-1.5 rounded-lg font-medium text-white bg-[#4338CA] hover:bg-[#3730A3] disabled:opacity-40 disabled:cursor-not-allowed">
                  {bulkBusy ? "Recording…"
                    : `Set ledger & record ${eligible.length} line${eligible.length === 1 ? "" : "s"}`}
                </button>
              </div>
            </div>
          </div>
        );
      })()}
      {/* The detail modal: everything about ONE line that the row deliberately
          does not carry. The row asks one question — which ledger — and this is
          where the answers that need thought live: the rate, the note, the
          routes to a document or a split, and what history and the rules
          propose. */}
      {(() => {
        const t = rows.find((r) => r.id === detailId);
        if (!t) return null;
        const posted = t.match_status === "posted";
        const excluded = t.match_status === "ignored";
        const amount = t.credit_paise > 0 ? t.credit_paise : t.debit_paise;
        const rate = gstRate[t.id] ?? (t.suggested_gst_rate_bps != null
          ? String(t.suggested_gst_rate_bps) : "");
        return (
          <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4"
               onClick={() => setDetailId(null)}>
            <div className="bg-white rounded-xl shadow-xl w-full max-w-xl max-h-[85vh] flex flex-col"
                 onClick={(e) => e.stopPropagation()}>
              <div className="flex items-start justify-between px-5 py-4 border-b border-[#F1F5F9]">
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-[#0F172A] truncate"
                      title={t.description}>{t.description}</h3>
                  <p className="text-xs text-[#64748B] mt-0.5">
                    {t.transaction_date} · <span className="font-mono">{fmt(amount)}</span>{" "}
                    {t.credit_paise > 0 ? "received" : "spent"}
                    {t.category ? <span className="text-[#94A3B8]"> · {t.category}</span> : null}
                  </p>
                </div>
                <button onClick={() => setDetailId(null)} aria-label="Close"
                  className="text-[#94A3B8] hover:text-[#475569] shrink-0"><X size={16} /></button>
              </div>

              <div className="px-5 py-4 space-y-3 overflow-y-auto flex-1">
                {/* The two fields that decide the journal, given room to be
                    read. On the row the ledger picker and a GST select fought
                    for one line; here each gets a label. */}
                {!posted && !excluded && !t.is_split && (
                  <div className="space-y-2">
                    <div>
                      <label className="block text-[11px] font-medium text-[#475569] mb-1">
                        Ledger
                      </label>
                      <AccountLookup
                        accounts={orderedAccounts}
                        value={t.account_id ?? ""}
                        onChange={(id) => codeToAccount(t, id)}
                        disabled={busy[t.id]}
                        ariaLabel="Ledger"
                        placeholder={t.suggested_account_id
                          ? `Suggested: ${accountLabel(t.suggested_account_id)}`
                          : "Choose a ledger…"}
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] font-medium text-[#475569] mb-1">
                        GST inside this amount
                      </label>
                      {t.gst_allowed ? (
                        <div className="flex items-center gap-3 flex-wrap">
                          <select
                            value={rate}
                            disabled={busy[t.id]}
                            onChange={(e) => setGstRate((g) => ({ ...g, [t.id]: e.target.value }))}
                            aria-label={t.credit_paise > 0
                              ? "Output GST on this receipt" : "Input GST on this payment"}
                            className="px-2 py-1.5 text-xs border border-[#E2E8F0] rounded-lg bg-white">
                            <option value="">No GST split</option>
                            {GST_RATE_OPTIONS.map((o) => (
                              <option key={o.value} value={o.value}>{o.label}</option>
                            ))}
                          </select>
                          {rate !== "" && rate !== "0" && (
                            <label className="flex items-center gap-1.5 text-xs text-[#475569]">
                              <input type="checkbox" disabled={busy[t.id]}
                                checked={gstInterstate[t.id] ?? !!t.suggested_is_interstate}
                                onChange={(e) => setGstInterstate((g) => ({ ...g, [t.id]: e.target.checked }))}
                                className="h-3.5 w-3.5 rounded border-[#CBD5E1]" />
                              IGST (inter-state)
                            </label>
                          )}
                          <span className="text-[10px] text-[#94A3B8]">
                            {t.credit_paise > 0
                              ? "Output tax owed — CGST Act s.9"
                              : "Input credit claimed — CGST Act s.16"}
                          </span>
                        </div>
                      ) : (
                        <p className="text-[11px] text-[#94A3B8]">
                          {GST_WHY_LONG[gstWhy(t)] ?? "Not available on this line."}
                        </p>
                      )}
                    </div>
                  </div>
                )}

                {rowError[t.id] && (
                  <p className="text-[10px] text-red-600 mb-1">{rowError[t.id]}</p>
                )}
    <div className="space-y-2 border-l-2 border-[#E2E8F0] pl-3">

    {/* What the bank actually sent. Selectable and wrapped rather
        than truncated — a UTR you cannot copy is no use when you are
        ringing the bank about it. */}
    <div>
      <p className="text-[10px] text-[#475569] break-words select-text font-mono leading-relaxed">
        {t.description}
      </p>
      {(t.parsed?.utr || t.reference_no || t.parsed?.vpa || t.parsed?.ifsc) && (
        <p className="text-[10px] text-[#94A3B8] break-words select-text mt-0.5">
          {[t.parsed?.utr ? `UTR ${t.parsed.utr}` : null,
            t.reference_no && t.reference_no !== t.parsed?.utr ? t.reference_no : null,
            t.parsed?.vpa, t.parsed?.ifsc].filter(Boolean).join(" · ")}
        </p>
      )}
    </div>

    {/* A firing rule proposes a category AND often the ledger. The
        picker on the line carries only the ledger — and applying a
        rule is accepting BOTH of its answers, including the finer
        category word the derivation deliberately will not guess — so
        taking the whole rule lives here. Not offered on a split line:
        the allocation already answers where the money goes. */}
    {!posted && !excluded && !t.is_split && !t.category && t.suggested_category && t.suggested_by_rule && (
      <div className="flex items-center gap-2">
        <p className="text-[10px] text-[#94A3B8] min-w-0 truncate">
          Rule <span className="text-[#334155]">{t.suggested_by_rule}</span> proposes{" "}
          <span className="text-[#334155]">{t.suggested_category}</span>
          {t.suggested_account_id ? ` · ${accountLabel(t.suggested_account_id)}` : ""}
        </p>
        <button onClick={() => applyRule(t)} disabled={busy[t.id]}
          className="text-[10px] px-2 py-0.5 border border-[#C7D2FE] bg-[#EEF2FF] text-[#4338CA] rounded hover:bg-[#E0E7FF] shrink-0">
          Use the rule
        </button>
      </div>
    )}

    {/* Tier 1.2 — the ledgers this one line was allocated across. Shown as the
        allocation itself, not a count: "split 3 ways" tells a reviewer nothing
        they can check. */}
    {t.is_split && (
      <div className="flex items-start gap-2 flex-wrap">
        <p className="text-[10px] text-[#64748B] min-w-0">
          Split across{" "}
          <span className="text-[#334155]">
            {(t.splits ?? []).map((s) => `${accountLabel(s.account_id)} ${fmt(s.amount_paise)}`).join(" · ")}
          </span>
        </p>
        {!posted && (
          <button onClick={() => openSplit(t)} disabled={busy[t.id]}
            className="text-[10px] px-2 py-0.5 border border-[#E2E8F0] rounded hover:bg-white text-[#475569] shrink-0">
            Edit the split
          </button>
        )}
      </div>
    )}

    {/* THE two ways out of a line the row itself cannot answer: find the
        document, or split it across several. They used to be 10px links among
        a dozen other 10px things and went unnoticed — which left a reader
        believing the row offered nothing but a category dropdown. They are the
        largest controls in this panel now, deliberately. */}
    {!posted && !excluded && (
      <div className="flex items-center gap-2 flex-wrap">
        {t.matched_entity_id ? (
          <button onClick={() => reject(t.id)} disabled={busy[t.id]}
            className="text-xs px-3 py-1.5 border border-red-200 text-red-600 rounded-lg hover:bg-red-50 font-medium disabled:opacity-50">
            Unmatch
          </button>
        ) : (
          <>
            <button onClick={() => setFindTxn(t)} disabled={busy[t.id]}
              className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 border border-[#CBD5E1] bg-white rounded-lg hover:bg-[#F1F5F9] text-[#334155] font-medium disabled:opacity-50">
              <Search size={13} /> Find the {t.credit_paise > 0 ? "invoice" : "bill"}
            </button>
            <button onClick={() => openSplit(t)} disabled={busy[t.id]}
              className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 border border-[#CBD5E1] bg-white rounded-lg hover:bg-[#F1F5F9] text-[#334155] font-medium disabled:opacity-50"
              title={`Allocate this line across several ledgers, across several ${t.credit_paise > 0 ? "invoices" : "bills"}, or record TDS withheld on it`}>
              <Split size={13} /> Split across several
            </button>
          </>
        )}
        <button onClick={() => setIgnored(t.id, true)} disabled={busy[t.id]}
          className="text-[11px] text-[#94A3B8] hover:text-[#64748B] hover:underline ml-auto disabled:opacity-50">
          Exclude
        </button>
      </div>
    )}

    {/* A confirmed transfer: the answer to "why has this row no
        button of its own". */}
    {t.transfer_pair_id && !posted && (
      <div className="flex items-center gap-2">
        <p className="text-[10px] text-[#64748B] min-w-0">
          {t.transfer_is_primary
            ? "Paying side — this one posts the journal"
            : "Receiving side — the same money; the paying side posts it"}
        </p>
        <button onClick={() => undoTransfer(t)} disabled={busy[t.id]}
          className="text-[10px] px-2 py-0.5 border border-[#E2E8F0] rounded hover:bg-white text-[#475569] shrink-0">
          Not a transfer
        </button>
      </div>
    )}

    {/* A confirmed payee has to be removable: it feeds the history
        that codes future rows, so a wrong one keeps proposing
        itself until someone can take it off. */}
    {t.payee_name && !posted && !excluded && (
      <div className="flex items-center gap-2">
        <p className="text-[10px] text-[#94A3B8] min-w-0 truncate">
          Payee <span className="text-[#334155]">{t.payee_name}</span>
          {t.payee_type ? <span className="text-[#CBD5E1]"> ({t.payee_type})</span> : null}
        </p>
        <button onClick={() => clearPayee(t)} disabled={busy[t.id]}
          className="text-[10px] text-[#94A3B8] hover:text-red-600 hover:underline shrink-0">
          Clear payee
        </button>
      </div>
    )}

    {/* Tier 1.3 — who the money went to, proposed from the narration
        or the matched party. Written only on a click. */}
    {!t.payee_name && t.suggested_payee && !posted && !excluded && (
      <div className="flex items-center gap-2">
        <p className="text-[10px] text-[#94A3B8] min-w-0 truncate">
          Payee looks like{" "}
          <span className="text-[#334155] font-medium">{t.suggested_payee.payee_name}</span>
          <span className="text-[#CBD5E1]">
            {" "}({t.suggested_payee.source === "narration" ? "from the narration" : "from the matched party"})
          </span>
        </p>
        <button onClick={() => acceptPayee(t)} disabled={busy[t.id]}
          className="text-[10px] px-2 py-0.5 border border-[#E2E8F0] rounded hover:bg-white text-[#475569] shrink-0">
          Confirm payee
        </button>
      </div>
    )}

    {/* Tier 1.4 — what was done with this payee before. Stated as
        evidence rather than a score, and applied only on a click. */}
    {t.history && !t.category && !t.is_split && !excluded && (
      <div className="flex items-center gap-2">
        <p className="text-[10px] text-[#94A3B8] min-w-0 truncate">
          <span className={t.history.is_unanimous ? "text-emerald-700" : "text-amber-700"}>
            {t.history.summary}
          </span>
          {t.history.category ? ` → ${t.history.category}` : ""}
          {t.history.account_id ? ` · ${accountLabel(t.history.account_id)}` : ""}
          {t.history.alternatives.length > 0 && (
            <span className="text-[#CBD5E1]">
              {" "}(also {t.history.alternatives
                .map((a) => `${accountLabel(a.account_id)} ×${a.times}`).join(", ")})
            </span>
          )}
        </p>
        <button onClick={() => applyHistory(t)} disabled={busy[t.id]}
          className="text-[10px] px-2 py-0.5 border border-[#BBF7D0] bg-[#F0FDF4] text-[#15803D] rounded hover:bg-[#DCFCE7] shrink-0">
          Use last time&apos;s
        </button>
      </div>
    )}

    </div>
              </div>

              <div className="px-5 py-3 border-t border-[#F1F5F9] flex items-center justify-end gap-2">
                <button onClick={() => setDetailId(null)}
                  className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569]">
                  Close
                </button>
                {!posted && !excluded && (
                  <button
                    onClick={async () => { await postRow(t); setDetailId(null); }}
                    disabled={busy[t.id] || !readyToAdd(t)}
                    title={readyToAdd(t) ? "Record this line" : "Choose a ledger first"}
                    className="text-xs px-3 py-1.5 rounded-lg font-medium text-white bg-[#4338CA] hover:bg-[#3730A3] disabled:opacity-40 disabled:cursor-not-allowed">
                    {busy[t.id] ? "…" : "Add"}
                  </button>
                )}
              </div>
            </div>
          </div>
        );
      })()}

      {/* ONE button, two kinds of split, chosen INSIDE the editor. Two
          similarly-named buttons on the row is how the ledger split stayed
          invisible for as long as it did. */}
      {splitTxn && splitMode === "ledgers" && (
        <SplitAcrossLedgersModal
          txnId={splitTxn.id}
          description={splitTxn.description}
          amountPaise={splitTxn.credit_paise > 0 ? splitTxn.credit_paise : splitTxn.debit_paise}
          isCredit={splitTxn.credit_paise > 0}
          accounts={accounts}
          modeSwitch={splitModeSwitch}
          onClose={() => { setSplitTxn(null); setPrefill(null); }}
          onDone={() => { setSplitTxn(null); setPrefill(null); load(); }}
        />
      )}
      {splitTxn && splitMode === "documents" && (
        <MultiInvoiceMatchModal
          txn={splitTxn}
          clientId={clientId}
          prefill={prefill}
          modeSwitch={splitModeSwitch}
          onClose={() => { setSplitTxn(null); setPrefill(null); }}
          onDone={() => { setSplitTxn(null); setPrefill(null); load(); }}
        />
      )}
      {findTxn && (
        <FindMatchModal
          txn={findTxn}
          onClose={() => setFindTxn(null)}
          onPicked={async (r) => {
            try {
              await api.banking.matchEntity(findTxn.id, {
                matched_entity_type: r.matched_entity_type,
                matched_entity_id: r.matched_entity_id,
              });
            } catch (e) {
              alert(e instanceof Error ? e.message : "Couldn't link this document.");
              return;   // leave the picker open so the CA can try another row
            }
            setFindTxn(null);
            await load();
          }}
          // A short match goes to the settlement modal for the same reason it
          // does from the suggestion list: linking it whole would under-settle
          // the document by whatever the customer withheld.
          onSettle={(r) => { const t = findTxn; setFindTxn(null); openSettle(t, r); }}
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

function MultiInvoiceMatchModal({ txn, clientId, prefill, onClose, onDone, modeSwitch }: {
  txn: QueueTxn; clientId: string; prefill?: SettlePrefill | null;
  onClose: () => void; onDone: () => void;
  /** The across-ledgers / across-documents switch, owned by the caller so both
   *  split editors show the same one in the same place. */
  modeSwitch?: ReactNode;
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
      if (!res.success) { setError(res.error ?? `Could not settle these ${docLabel}s.`); return; }
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : `Could not settle these ${docLabel}s.`);
    } finally {
      // One release covering all three exits. The success path never lowered
      // it at all, which was harmless only because onDone() unmounts this
      // modal — a fact this function should not have to rely on.
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
        {modeSwitch && <div className="px-5 pt-3">{modeSwitch}</div>}
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

// ── "Find other matches" (B.1.6) ───────────────────────────────────────────
// "Suggest matches" ranks the best five WITHIN an amount band, which is right
// most of the time and useless the rest: a part-payment, an unusual shortfall,
// or a document from four months back is simply not in the band, and until now
// a CA who KNEW the invoice number had no way to type it in.
//
// Every filter here is a query parameter. The browser does no filtering,
// ranking or matching of its own — it renders what the API returned and sends
// the chosen row to the existing /match endpoint.

interface CandidateResult {
  matched_entity_type: string; matched_entity_id: string; label: string;
  amount_paise: number; entity_date: string | null;
  party_name: string | null; party_id: string | null;
  outstanding_paise: number | null;
  // candidate − bank. Positive = the bank line is SHORT of the document (the
  // TDS shape); negative = the bank line is LARGER, which the band used to hide.
  difference_paise: number;
  tds_rate_bps: number | null;
  is_exact: boolean;
  summary: string;
}
interface CandidateSearchPayload {
  transaction_id: string; amount_paise: number; direction: "credit" | "debit";
  allowed_types: string[]; results: CandidateResult[];
  total: number; limit: number; offset: number; truncated: boolean;
}

const CANDIDATE_TYPE_LABELS: Record<string, string> = {
  sales_invoice: "Sales invoices", purchase_bill: "Purchase bills",
  receipt: "Receipts", purchase_payment: "Payments", journal_entry: "Journal entries",
};

interface CandidateFilters {
  q: string; dateFrom: string; dateTo: string;
  minRs: string; maxRs: string; entityType: string;
}
const NO_CANDIDATE_FILTERS: CandidateFilters = {
  q: "", dateFrom: "", dateTo: "", minRs: "", maxRs: "", entityType: "",
};
const PER_PAGE = 25;

function FindMatchModal({ txn, onClose, onPicked, onSettle }: {
  txn: QueueTxn;
  onClose: () => void;
  onPicked: (r: CandidateResult) => Promise<void>;
  onSettle: (r: CandidateResult) => void;
}) {
  const isCredit = txn.credit_paise > 0;
  const txnAmount = isCredit ? txn.credit_paise : txn.debit_paise;

  const [q, setQ] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [minRs, setMinRs] = useState("");
  const [maxRs, setMaxRs] = useState("");
  const [entityType, setEntityType] = useState("");
  const [page, setPage] = useState(0);
  const [data, setData] = useState<CandidateSearchPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picking, setPicking] = useState<string | null>(null);

  // The filters are passed to run() rather than closed over, so run() changes
  // identity only when the transaction does — which is what lets the first-open
  // effect below fire once instead of on every keystroke.
  const run = useCallback(async (offset: number, f: CandidateFilters) => {
    setLoading(true); setError(null);
    const params: Record<string, string> = { limit: String(PER_PAGE), offset: String(offset) };
    if (f.q.trim()) params.q = f.q.trim();
    if (f.dateFrom) params.date_from = f.dateFrom;
    if (f.dateTo) params.date_to = f.dateTo;
    if (f.minRs !== "") params.min_amount_paise = String(rsToP(parseFloat(f.minRs) || 0));
    if (f.maxRs !== "") params.max_amount_paise = String(rsToP(parseFloat(f.maxRs) || 0));
    if (f.entityType) params.entity_type = f.entityType;
    try {
      const res = (await api.banking.candidateSearch(txn.id, params)) as
        { success: boolean; data: CandidateSearchPayload; error?: string | null };
      if (!res.success) throw new Error(res.error ?? "Couldn't search for matches.");
      setData(res.data);
    } catch (e) {
      setData(null);
      setError(e instanceof Error ? e.message : "Couldn't search for matches.");
    } finally {
      setLoading(false);
    }
  }, [txn.id]);

  // First open shows everything in reach, so the modal is useful before a single
  // character is typed. Re-running is explicit after that — a query per keystroke
  // over a client's whole document history is a lot of load for little gain.
  useEffect(() => { setPage(0); run(0, NO_CANDIDATE_FILTERS); }, [run]);

  const filters: CandidateFilters = { q, dateFrom, dateTo, minRs, maxRs, entityType };

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setPage(0);
    run(0, filters);
  }
  function goTo(next: number) {
    setPage(next);
    run(next * PER_PAGE, filters);
  }

  async function pick(r: CandidateResult) {
    setPicking(r.matched_entity_id);
    try { await onPicked(r); }
    finally { setPicking(null); }
  }

  const shown = data?.results ?? [];
  const total = data?.total ?? 0;
  const lastPage = Math.max(0, Math.ceil(total / PER_PAGE) - 1);

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#F1F5F9]">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-[#0F172A]">Find other matches</h3>
            <p className="text-xs text-[#64748B] mt-0.5 truncate">
              {txn.description} · {txn.transaction_date} · {fmt(txnAmount)} {isCredit ? "credit" : "debit"}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>

        <form onSubmit={submit} className="px-5 py-3 border-b border-[#F1F5F9] space-y-2">
          <div className="flex gap-2">
            <input
              value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="Invoice number, party name…"
              aria-label="Search documents"
              className="flex-1 px-2 py-1.5 text-xs border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500" />
            <button type="submit" disabled={loading}
              className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
              {loading ? "Searching…" : "Search"}
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            <select value={entityType} onChange={(e) => setEntityType(e.target.value)}
              aria-label="Document type"
              className="px-2 py-1 text-[11px] border border-[#E2E8F0] rounded text-[#475569]">
              {/* Only what money moving THIS way can settle. The backend applies
                  the same rule and refuses anything else outright, so this list
                  narrows the request rather than deciding it. */}
              <option value="">All types</option>
              {(data?.allowed_types ?? []).map((t) => (
                <option key={t} value={t}>{CANDIDATE_TYPE_LABELS[t] ?? t}</option>
              ))}
            </select>
            <label className="flex items-center gap-1 text-[10px] text-[#94A3B8]">
              From
              <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                aria-label="Dated from"
                className="px-1.5 py-1 text-[11px] border border-[#E2E8F0] rounded text-[#475569]" />
            </label>
            <label className="flex items-center gap-1 text-[10px] text-[#94A3B8]">
              To
              <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                aria-label="Dated to"
                className="px-1.5 py-1 text-[11px] border border-[#E2E8F0] rounded text-[#475569]" />
            </label>
            <label className="flex items-center gap-1 text-[10px] text-[#94A3B8]">
              ₹ min
              <input type="number" step="0.01" min="0" value={minRs} onChange={(e) => setMinRs(e.target.value)}
                aria-label="Minimum amount in rupees"
                className="w-24 px-1.5 py-1 text-[11px] border border-[#E2E8F0] rounded text-[#475569]" />
            </label>
            <label className="flex items-center gap-1 text-[10px] text-[#94A3B8]">
              ₹ max
              <input type="number" step="0.01" min="0" value={maxRs} onChange={(e) => setMaxRs(e.target.value)}
                aria-label="Maximum amount in rupees"
                className="w-24 px-1.5 py-1 text-[11px] border border-[#E2E8F0] rounded text-[#475569]" />
            </label>
          </div>
        </form>

        <div className="px-5 py-3 overflow-y-auto flex-1 space-y-1.5">
          {error && <p className="text-xs text-red-600">{error}</p>}
          {!error && !loading && shown.length === 0 && (
            <p className="text-xs text-[#94A3B8]">
              Nothing here matches. Widen the dates or clear a filter — this search already
              looks past the amount, so a document of any size is reachable.
            </p>
          )}
          {data?.truncated && (
            <p className="text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
              There were more documents than this search reads at once. Narrow the dates or
              the amount to be sure you are seeing everything.
            </p>
          )}
          {shown.map((r) => (
            <div key={`${r.matched_entity_type}:${r.matched_entity_id}`}
              className="flex items-center justify-between gap-3 border border-[#F1F5F9] rounded px-2.5 py-1.5">
              <div className="min-w-0">
                <p className="text-[11px] text-[#334155] truncate">{r.label}</p>
                <p className="text-[10px] text-[#94A3B8]">
                  {r.entity_date ?? "—"} · {fmt(r.amount_paise)}
                  {r.outstanding_paise !== null && r.outstanding_paise !== r.amount_paise
                    ? ` · ${fmt(r.outstanding_paise)} open` : ""}
                  {" · "}{r.summary}
                </p>
              </div>
              <div className="shrink-0">
                {/* Same rule as the suggestion list: a SHORT match settles only
                    what arrived and leaves the document partly open, which is
                    wrong when the shortfall is withheld TDS. Route it to the
                    settlement modal rather than let one click under-settle. */}
                {r.difference_paise > 0 ? (
                  <button onClick={() => onSettle(r)}
                    className="text-[10px] px-2 py-0.5 bg-amber-600 text-white rounded hover:bg-amber-700"
                    title={`Bank line is ${fmt(r.difference_paise)} short of this document`}>
                    {r.tds_rate_bps ? "Settle with TDS" : "Settle difference"}
                  </button>
                ) : (
                  <button onClick={() => pick(r)} disabled={picking !== null}
                    className="text-[10px] px-2 py-0.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
                    {picking === r.matched_entity_id ? "Matching…" : "Match"}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between px-5 py-3 border-t border-[#F1F5F9]">
          <p className="text-[10px] text-[#94A3B8]">
            {total === 0 ? "No documents" :
              `${page * PER_PAGE + 1}–${Math.min((page + 1) * PER_PAGE, total)} of ${total}`}
          </p>
          <div className="flex gap-2">
            <button onClick={() => goTo(page - 1)} disabled={page === 0 || loading}
              className="text-[11px] px-2 py-1 border border-[#E2E8F0] rounded text-[#475569] disabled:opacity-40">
              Previous
            </button>
            <button onClick={() => goTo(page + 1)} disabled={page >= lastPage || loading}
              className="text-[11px] px-2 py-1 border border-[#E2E8F0] rounded text-[#475569] disabled:opacity-40">
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// Label only — the split itself is computed server-side (CLAUDE.md: no business
// logic in the frontend). 0% is a real, deliberate answer; the absence of a
// rate is a different one, and posts the gross as one line.
//
// Deliberately neutral about direction and about banking: the same list now
// offers input credit on a payment (CGST Act s.16) and output tax on a receipt
// (s.9), so a label that said "standard for banking services" would be wrong
// half the time. Short, because this is a column now, not a drawer.
/** Which of the server's refusals applies to this line, in the order
 *  posting_map.gst_split_allowed checks them. One function so the row's short
 *  label and the modal's sentence are always the same answer. */
function gstWhy(t: QueueTxn): string {
  if (t.matched_entity_id) return "on the invoice";
  if (t.is_split) return "per split";
  if (t.category === "Transfer") return "not a supply";
  if (!t.account_id) return "pick a ledger";
  return "control account";
}

/** The short reason in the cell → the sentence behind it on hover. Mirrors
 *  posting_map.gst_split_allowed, which is the authority; these are words for
 *  its answers, never a second copy of the rule. */
const GST_WHY_LONG: Record<string, string> = {
  "on the invoice": "This line settles an invoice or bill, and that document already carries its own GST. Taxing the bank line too would count the same tax twice.",
  "per split": "This line is allocated across several ledgers. A GST rate would need one rate per leg, which is not built yet.",
  "not a supply": "Moving money between your own accounts is not a supply, so no GST arises.",
  "pick a ledger": "Choose a ledger first — the split books the amount excluding tax there, so there is nowhere to put it yet.",
  "control account": "This posts to a control account like Trade Receivables or Trade Payables. Tax does not belong on one.",
};

const GST_RATE_OPTIONS: { value: number; label: string }[] = [
  { value: 0, label: "0% — no GST" },
  { value: 500, label: "5%" },
  { value: 1200, label: "12%" },
  { value: 1800, label: "18%" },
  { value: 2800, label: "28%" },
];

interface BankAccount {
  id: string;
  bank_name: string;
  account_no: string;
  ifsc: string | null;
  account_type: string;
  opening_balance_paise: number;
  opening_balance_date: string | null;
  coa_account_id: string | null;
  /** Resolved server-side so the row can name the ledger it posts to, not just
   *  claim it is "Linked" — which is the balance-sheet line this account is. */
  ledger_account_code?: string | null;
  ledger_account_name?: string | null;
  currency: string;
  is_active: boolean;
}

function BankAccounts({ clientId }: { clientId: string }) {
  const [statements, setStatements] = useState<BankStatement[]>([]);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  // {id: {deletable, blocked_by}} — decides whether Delete is offered at all,
  // and what the disabled one says when it is not.
  const [deletability, setDeletability] = useState<Record<string, { deletable: boolean; blocked_by: string[] }>>({});
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
      const [stmts, accRes, delRes] = await Promise.all([
        getBankStatements(clientId),
        // include_inactive: this table is the only place a deactivated account can
        // be seen or reactivated, and its opening balance stays in the GL, so
        // hiding it left money on the balance sheet with no account to explain it.
        // The pickers below filter to activeAccounts themselves.
        api.banking.listBankAccounts({ client_id: clientId, include_inactive: "true" }) as Promise<{ success: boolean; data: BankAccount[] }>,
        (api.banking.bankAccountsDeletable({ client_id: clientId }) as Promise<{ success: boolean; data: Record<string, { deletable: boolean; blocked_by: string[] }> }>)
          .catch(() => ({ success: false, data: {} })),
      ]);
      setStatements(stmts);
      setAccounts(accRes.success ? (accRes.data ?? []) : []);
      setDeletability(delRes.success ? (delRes.data ?? {}) : {});
    } catch (e) {
      // Was a bare `/* skip */`, which read as "an empty statement list" — the
      // same screen a client with nothing imported yet gets. Say which it is.
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not load statements." });
    } finally {
      setLoading(false);
    }
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

  async function reactivateAccount(a: BankAccount) {
    try {
      const res = await api.banking.updateBankAccount(a.id, { is_active: true }) as { success: boolean; error: string | null };
      if (!res.success) { setMsg({ type: "err", text: res.error ?? "Could not reactivate the account." }); return; }
      setMsg({ type: "ok", text: `${a.bank_name} reactivated.` });
      loadStatements();
    } catch (e) { setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not reactivate the account." }); }
  }

  async function deleteAccount(a: BankAccount) {
    if (!confirm(`Permanently delete ${a.bank_name} (····${a.account_no.slice(-4)})?\n\n`
      + `This account has no statements, no reconciliations and nothing posted to its `
      + `ledger, so there is no history to keep. Its ledger account goes with it if `
      + `nothing else uses it. This cannot be undone.`)) return;
    try {
      const res = await api.banking.deleteBankAccount(a.id) as { success: boolean; error: string | null };
      if (!res.success) { setMsg({ type: "err", text: res.error ?? "Could not delete the account." }); return; }
      setMsg({ type: "ok", text: `${a.bank_name} deleted.` });
      loadStatements();
    } catch (e) { setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not delete the account." }); }
  }

  const activeAccounts = accounts.filter((a) => a.is_active);

  async function openStatement(id: string) {
    setSelectedStmt(id); setTxnsLoading(true);
    try {
      setStmtTxns(await getBankTransactions(id));
    } catch (e) {
      setStmtTxns([]);
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not load this statement." });
    } finally {
      setTxnsLoading(false);
    }
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
                  <td className="px-3 py-2.5 text-[#64748B]">
                    {a.coa_account_id
                      ? (a.ledger_account_code
                          ? <span className="font-mono text-[11px]">{a.ledger_account_code} · {a.ledger_account_name}</span>
                          : "Linked")
                      : <span className="text-amber-600">Not linked</span>}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[#334155]">{fmt(a.opening_balance_paise)}</td>
                  <td className="px-4 py-2.5 text-right whitespace-nowrap">
                    <button onClick={() => setAccountModal(a)} className="text-[#4338CA] hover:text-[#3730A3] inline-flex items-center gap-1"><Pencil size={11} /> Edit</button>
                    {a.is_active
                      ? <button onClick={() => deactivateAccount(a)} className="ml-3 text-red-600 hover:text-red-800">Deactivate</button>
                      : <button onClick={() => reactivateAccount(a)} className="ml-3 text-[#059669] hover:text-[#047857]">Reactivate</button>}
                    {/* Delete is offered only for an account with no footprint.
                        When it is blocked the button stays, disabled, carrying the
                        reason — "why can't I delete this?" is the question a
                        missing button leaves unanswered. */}
                    {deletability[a.id]?.deletable ? (
                      <button onClick={() => deleteAccount(a)} className="ml-3 text-red-600 hover:text-red-800">Delete</button>
                    ) : deletability[a.id] ? (
                      <span className="ml-3 text-[#CBD5E1] cursor-not-allowed"
                            title={`Cannot be deleted because ${deletability[a.id].blocked_by.join("; ")}. Deactivate it instead — that keeps its history.`}>Delete</span>
                    ) : null}
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
    // An opening balance read wrong is wrong for the life of the account: every
    // reconciliation after it starts from this number.
    const openingPaise = paiseFromRupeeInput(openingBal || "0");
    if (openingPaise === null) {
      setError("Opening balance must be an amount in rupees, e.g. 125000 or "
               + "125000.50 — without commas.");
      return;
    }
    setSaving(true); setError(null);
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
      if (!res.success) { setError(res.error ?? "Could not save the bank account."); return; }
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the bank account.");
    } finally {
      setSaving(false);
    }
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
            {/* Plain text, no datalist. The ten-bank suggestion list rendered a
                dropdown arrow that read as a closed picker, and India has some
                1,500 banks — co-operative and regional ones especially are what a
                CA's smaller clients actually bank with. */}
            <input value={bankName} onChange={(e) => setBankName(e.target.value)} className={inputCls} placeholder="e.g. Saraswat Co-operative Bank" />
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

// ── Statement column mapping (audit Tier 3.2) ──────────────────────────────
// The six auto-detected layouts cover HDFC, SBI, ICICI, Axis and two generic
// shapes. Everything else used to stop dead at "Unsupported bank statement
// format". These types are the shape of the way past it.

type StatementMapping = Record<string, number | null>;

interface StatementInspection {
  headers: string[];
  sample_rows: string[][];
  total_rows: number;
  detected_format: string;
  detected_fits: boolean;
  proposed_mapping: StatementMapping | null;
  saved_mapping: StatementMapping | null;
  header_fingerprint: string;
}

interface BalanceCheck {
  checked: boolean;
  agrees?: boolean;
  order?: string;
  note?: string;
  reason?: string;
  rows_checked?: number;
  disagreeing_rows?: number;
}

interface StatementPreview {
  headers: string[];
  total_rows: number;
  parsed_count: number;
  skipped_count: number;
  rows: {
    transaction_date: string; description: string; reference_no: string | null;
    debit_paise: number; credit_paise: number; balance_paise: number;
  }[];
  balance_check: BalanceCheck;
}

/** The fields a statement row can carry. Order is the order they are asked for. */
const MAPPING_FIELDS: { key: string; label: string; hint: string; required?: boolean }[] = [
  { key: "date",    label: "Date",        hint: "the transaction date", required: true },
  { key: "desc",    label: "Description", hint: "narration / particulars", required: true },
  { key: "ref",     label: "Reference",   hint: "cheque or UTR number" },
  { key: "debit",   label: "Debit",       hint: "money out (withdrawals)" },
  { key: "credit",  label: "Credit",      hint: "money in (deposits)" },
  { key: "amount",  label: "Amount",      hint: "one column for both directions" },
  { key: "drcr",    label: "Dr/Cr",       hint: "which way the Amount goes" },
  { key: "balance", label: "Balance",     hint: "running balance after the row" },
];

const EMPTY_MAPPING: StatementMapping = {
  date: null, desc: null, ref: null, debit: null,
  credit: null, amount: null, drcr: null, balance: null,
};

/** Drop the unmapped fields — the server reads an absent key as "not present". */
function cleanMapping(m: StatementMapping): StatementMapping {
  return Object.fromEntries(Object.entries(m).filter(([, v]) => v !== null && v !== undefined));
}

/** Is this the dead end the mapper exists for, rather than a network fault?
 *
 *  The backend raises two different sentences for it — "Unsupported bank
 *  statement format" when nothing matches, and "layout doesn't match the
 *  detected 'x' format" when an adapter is picked and then fails to fit. Both
 *  are the same problem to a CA, and both list the banks we do support, which
 *  is the phrase they reliably share. */
function looksLikeAFormatProblem(message: string): boolean {
  const m = message.toLowerCase();
  return m.includes("unsupported bank statement format")
    || m.includes("layout doesn't match")
    || m.includes("could not identify")
    || m.includes("no transactions found");
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

  // ── Column mapping (audit Tier 3.2) ──────────────────────────────────────
  // Six statement layouts are auto-detected. Every other bank — Kotak, IDFC
  // First, PNB, Canara, and every co-operative bank — used to stop at
  // "Unsupported bank statement format" with nothing the CA could do. Now that
  // error opens this: say where the columns are, once, and it is remembered
  // for the account.
  const [mapping, setMapping] = useState<StatementMapping | null>(null);
  const [inspected, setInspected] = useState<StatementInspection | null>(null);
  const [preview, setPreview] = useState<StatementPreview | null>(null);
  const [checking, setChecking] = useState(false);
  const [remember, setRemember] = useState(true);
  const [overrideBalance, setOverrideBalance] = useState(false);

  const account = accounts.find((a) => a.id === accountId);

  function resetMapping() {
    setMapping(null); setInspected(null); setPreview(null); setOverrideBalance(false);
  }

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) { setFile(f); setError(null); setResult(null); resetMapping(); }
  }

  function baseForm(): FormData {
    const form = new FormData();
    if (file) form.append("file", file);
    form.append("client_id", clientId);
    return form;
  }

  /** Open the mapper: read the file's header row and pre-fill what we can. */
  async function startMapping() {
    if (!file || !account) return;
    setChecking(true); setError(null);
    try {
      const form = baseForm();
      form.append("bank_account_id", account.id);
      const res = (await api.banking.inspectStatement(form)) as { success: boolean; data: StatementInspection };
      const info = res.data;
      setInspected(info);
      // A saved mapping for this exact layout wins; then the detected adapter,
      // but ONLY when it actually fits — prefilling a layout the server has
      // just rejected would hand the CA the error to confirm.
      setMapping({ ...EMPTY_MAPPING, ...(info.saved_mapping ?? info.proposed_mapping ?? {}) });
      setPreview(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read the file.");
    } finally {
      setChecking(false);
    }
  }

  /** Parse with the mapping and show what it produces — nothing is imported. */
  async function runPreview() {
    if (!file || !mapping) return;
    setChecking(true); setError(null); setOverrideBalance(false);
    try {
      const form = baseForm();
      form.append("column_mapping", JSON.stringify(cleanMapping(mapping)));
      const res = (await api.banking.previewStatement(form)) as { success: boolean; data: StatementPreview };
      setPreview(res.data);
    } catch (err) {
      setPreview(null);
      setError(err instanceof Error ? err.message : "Could not read the file with that mapping.");
    } finally {
      setChecking(false);
    }
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
      if (mapping) {
        form.append("column_mapping", JSON.stringify(cleanMapping(mapping)));
        form.append("save_mapping", remember ? "true" : "false");
      }
      const res = (await api.banking.uploadStatement(form)) as {
        success: boolean; data: { imported: number; duplicates_skipped: number; total_rows: number }; error?: string;
      };
      if (!res.success) { setError(res.error ?? "Import failed."); setImporting(false); return; }
      setResult(res.data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Import failed";
      setError(message);
      // The format errors are the ones the mapper exists for, so go straight
      // there rather than leaving the CA at a dead end with an explanation.
      if (!mapping && looksLikeAFormatProblem(message)) void startMapping();
    } finally {
      setImporting(false);
    }
  }

  const inputCls = "w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500";

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className={`bg-white rounded-xl shadow-xl w-full p-6 space-y-4 ${inspected ? "max-w-3xl max-h-[90vh] overflow-y-auto" : "max-w-md"}`}>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">
            {inspected ? "Map the statement columns" : "Import Bank Statement"}
          </h3>
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
                <p className="text-[10px] text-[#94A3B8] mt-1">The file is parsed on the server — HDFC / SBI / ICICI / Axis are auto-detected. Any other bank: use <span className="font-medium">Map columns</span> once and we&apos;ll remember it. Amounts stay exact.</p>
              </div>
            </div>

            {inspected && mapping && (
              <div className="space-y-3 border-t border-[#E2E8F0] pt-3">
                <p className="text-xs text-[#475569]">
                  This bank&apos;s layout isn&apos;t one we recognise. Tell us which column holds
                  what — once. {account ? <>We&apos;ll remember it for <span className="font-medium">{account.bank_name}</span> and use it next time.</> : null}
                </p>

                <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                  {MAPPING_FIELDS.map((f) => (
                    <div key={f.key}>
                      <label className="block text-[11px] font-medium text-[#475569]">
                        {f.label}{f.required && <span className="text-red-500"> *</span>}
                        <span className="font-normal text-[#94A3B8]"> — {f.hint}</span>
                      </label>
                      <select
                        value={mapping[f.key] ?? ""}
                        onChange={(e) => {
                          const v = e.target.value === "" ? null : Number(e.target.value);
                          setMapping({ ...mapping, [f.key]: v });
                          setPreview(null);          // the mapping changed; the old check no longer describes it
                          setOverrideBalance(false);
                        }}
                        className="w-full px-2 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="">— not in this file —</option>
                        {inspected.headers.map((h, i) => (
                          <option key={i} value={i}>{i + 1}. {h || `(column ${i + 1})`}</option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>

                <p className="text-[10px] text-[#94A3B8]">
                  Use either <span className="font-medium">Debit + Credit</span>, or a single{" "}
                  <span className="font-medium">Amount</span> with a <span className="font-medium">Dr/Cr</span> column — not both.
                </p>

                <div className="flex items-center gap-3">
                  <button onClick={runPreview} disabled={checking}
                          className="text-xs px-3 py-1.5 border border-blue-200 text-blue-700 bg-blue-50 rounded-lg hover:bg-blue-100 disabled:opacity-40">
                    {checking ? "Checking…" : "Check this mapping"}
                  </button>
                  <label className="flex items-center gap-1.5 text-[11px] text-[#475569]">
                    <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
                    Remember this layout for this account
                  </label>
                </div>

                {preview && (
                  <div className="space-y-2">
                    {/* The bank's own running balance is what verifies the mapping.
                        A swapped Debit/Credit parses perfectly and inverts the
                        client's cash — no column-label check could catch it. */}
                    {preview.balance_check.checked && preview.balance_check.agrees && (
                      <p className="text-xs text-green-700 bg-green-50 border border-green-100 rounded px-3 py-2">
                        ✓ Checked against the bank&apos;s own balance column across{" "}
                        {preview.balance_check.rows_checked} row{preview.balance_check.rows_checked === 1 ? "" : "s"} — every
                        movement agrees.{preview.balance_check.note ? ` ${preview.balance_check.note}` : ""}
                      </p>
                    )}
                    {preview.balance_check.checked && preview.balance_check.agrees === false && (
                      <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2 space-y-1.5">
                        <p className="font-medium">This mapping disagrees with the bank&apos;s own balances.</p>
                        <p>{preview.balance_check.reason}</p>
                        <label className="flex items-center gap-1.5">
                          <input type="checkbox" checked={overrideBalance} onChange={(e) => setOverrideBalance(e.target.checked)} />
                          Import anyway — I have checked the rows below and they are right
                        </label>
                      </div>
                    )}
                    {!preview.balance_check.checked && (
                      <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded px-3 py-2">
                        This statement has no balance column, so the mapping could not be
                        checked arithmetically. Read the rows below before importing.
                      </p>
                    )}

                    <p className="text-[11px] text-[#475569]">
                      {preview.parsed_count} of {preview.total_rows} rows read
                      {preview.skipped_count > 0 && <span className="text-amber-700"> · {preview.skipped_count} skipped</span>}
                    </p>
                    <div className="overflow-x-auto border border-[#E2E8F0] rounded-lg">
                      <table className="w-full text-[11px]">
                        <thead className="bg-[#F8FAFC] text-[#64748B]">
                          <tr>
                            <th className="text-left px-2 py-1.5">Date</th>
                            <th className="text-left px-2 py-1.5">Description</th>
                            <th className="text-right px-2 py-1.5">Debit</th>
                            <th className="text-right px-2 py-1.5">Credit</th>
                            <th className="text-right px-2 py-1.5">Balance</th>
                          </tr>
                        </thead>
                        <tbody>
                          {preview.rows.map((r, i) => (
                            <tr key={i} className="border-t border-[#F1F5F9]">
                              <td className="px-2 py-1.5 whitespace-nowrap">{r.transaction_date}</td>
                              <td className="px-2 py-1.5 max-w-[18rem] truncate" title={r.description}>{r.description}</td>
                              <td className="px-2 py-1.5 text-right">{r.debit_paise ? formatPaise(r.debit_paise) : ""}</td>
                              <td className="px-2 py-1.5 text-right">{r.credit_paise ? formatPaise(r.credit_paise) : ""}</td>
                              <td className="px-2 py-1.5 text-right text-[#64748B]">{r.balance_paise ? formatPaise(r.balance_paise) : ""}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}

            {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
            <div className="flex gap-3 justify-end">
              <button onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
              {!inspected && file && (
                <button onClick={startMapping} disabled={checking || !account}
                        className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] disabled:opacity-40">
                  {checking ? "Reading…" : "Map columns"}
                </button>
              )}
              <button
                onClick={handleImport}
                disabled={
                  importing || !file || accounts.length === 0
                  // With the mapper open, importing is gated on a check having
                  // been run: the preview IS the safety argument for skipping
                  // the column-label validation, so importing without it would
                  // give up the guard and gain nothing.
                  || (!!inspected && !preview)
                  || (!!preview && preview.balance_check.agrees === false && !overrideBalance)
                }
                className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40"
              >
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
  suggested_gst_rate_bps: number | null;
  suggested_is_interstate: boolean | null;
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
  // "" = the rule says nothing about GST. "0" = it says the charge carries none.
  // Two different answers, so they never share a value.
  suggested_gst_rate_bps: "",
  suggested_is_interstate: false,
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
      suggested_gst_rate_bps: r.suggested_gst_rate_bps == null ? "" : String(r.suggested_gst_rate_bps),
      suggested_is_interstate: !!r.suggested_is_interstate,
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
      // Explicit null (not omitted) so clearing a wrongly-stamped rate actually
      // sticks — the PATCH endpoint treats a sent null as "clear this".
      suggested_gst_rate_bps:
        form.suggested_gst_rate_bps === "" ? null : Number(form.suggested_gst_rate_bps),
      suggested_is_interstate: form.suggested_is_interstate,
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
    if (payload.suggested_gst_rate_bps !== null && !payload.suggested_account_id) {
      setFormError("A GST rate needs a counter account — the split books the ex-GST amount there.");
      return;
    }
    if (payload.suggested_gst_rate_bps !== null && payload.txn_type === "credit") {
      setFormError("A GST rate applies to bank charges — money out. Set this rule to money out, or either.");
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

  function gstSummary(r: BankRule) {
    if (r.suggested_gst_rate_bps == null) return null;
    if (r.suggested_gst_rate_bps === 0) return "no GST";
    return `${r.suggested_gst_rate_bps / 100}% ${r.suggested_is_interstate ? "IGST" : "CGST+SGST"}`;
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

          {/* GST on bank charges. Constant per bank, so it belongs on the rule
              rather than being re-entered on every ₹590 debit. */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">GST inside the amount</label>
              <select value={form.suggested_gst_rate_bps}
                onChange={(e) => setForm((f) => ({ ...f, suggested_gst_rate_bps: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm">
                <option value="">— Don&apos;t split —</option>
                {GST_RATE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <p className="text-[10px] text-[#94A3B8] mt-1">
                Amounts on a statement are inclusive of GST. On money going out the split
                claims the input tax credit (CGST Act s.16) instead of expensing it; on
                money coming in it books the output tax owed (s.9) instead of overstating
                income. 18% is the usual rate on bank charges.
              </p>
            </div>
            {form.suggested_gst_rate_bps !== "" && form.suggested_gst_rate_bps !== "0" && (
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Place of supply</label>
                <label className="flex items-start gap-2 pt-1.5">
                  <input type="checkbox" checked={form.suggested_is_interstate}
                    onChange={(e) => setForm((f) => ({ ...f, suggested_is_interstate: e.target.checked }))}
                    className="mt-0.5 h-3.5 w-3.5 rounded border-[#CBD5E1] text-blue-600 focus:ring-blue-500" />
                  <span className="text-xs text-[#475569]">Inter-state (IGST)</span>
                </label>
                <p className="text-[10px] text-[#94A3B8] mt-1">
                  Tick when this bank is registered outside the client&apos;s state. The place
                  of supply is the client&apos;s location (IGST Act s.12(12)).
                </p>
              </div>
            )}
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
                  {[r.suggested_category, accountName(r.suggested_account_id), r.suggested_narration,
                    gstSummary(r)].filter(Boolean).join(" · ")}
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

// ── Bank register (Tier 1.1) ───────────────────────────────────────────────
// The ledger view of one account. READ-ONLY by design: posted journals are
// immutable in this system, so an edit box here would promise something the
// ledger refuses — corrections are reversals, made in the journal.
//
// Every figure below comes from the server (CLAUDE.md: no business logic in the
// frontend). This component sorts nothing and sums nothing; `balance_paise` on
// each line is the running balance as computed in date order, which is the only
// order in which a running balance means anything.

interface RegisterLine {
  transaction_id: string;
  transaction_date: string | null;
  description: string;
  reference_no: string | null;
  debit_paise: number;
  credit_paise: number;
  amount_paise: number;
  balance_paise: number;
  cleared: "" | "C" | "R";
  category: string | null;
  match_status: string | null;
  posted_journal_id: string | null;
  statement_balance_paise: number | null;
  balance_delta_paise: number | null;
  precedes_opening: boolean;
}
interface RegisterDivergence {
  index: number; transaction_id: string; transaction_date: string | null;
  description: string; computed_balance_paise: number;
  statement_balance_paise: number | null; delta_paise: number;
}
interface RegisterSummary {
  opening_balance_paise: number; deposits_paise: number; withdrawals_paise: number;
  closing_balance_paise: number; line_count: number; uncleared_count: number;
  pending_count: number; reconciled_count: number; unposted_count: number;
  precedes_opening_count: number;
}
interface RegisterPayload {
  account: {
    id: string; bank_name: string; account_no: string; account_type: string;
    currency: string; opening_balance_paise: number; opening_balance_date: string | null;
  } | null;
  lines: RegisterLine[];
  summary: RegisterSummary;
  divergence: RegisterDivergence | null;
  view_opening_balance_paise: number;
  filtered_count: number;
  total_count: number;
  limit: number;
  offset: number;
}

type RegisterStatus = "all" | "uncleared" | "pending" | "reconciled" | "unposted" | "needs_review";
type RegisterSort = "date" | "amount" | "description" | "balance" | "cleared";

const REGISTER_STATUSES: { id: RegisterStatus; label: string }[] = [
  { id: "all", label: "All" },
  { id: "uncleared", label: "Uncleared" },
  { id: "pending", label: "Cleared (C)" },
  { id: "reconciled", label: "Reconciled (R)" },
  { id: "unposted", label: "Not posted" },
  { id: "needs_review", label: "Needs review" },
];

const PAGE_SIZE = 100;

function BankRegister({ clientId }: { clientId: string }) {
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [bankAccountId, setBankAccountId] = useState("");
  const [data, setData] = useState<RegisterPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [status, setStatus] = useState<RegisterStatus>("all");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<RegisterSort>("date");
  const [desc, setDesc] = useState(false);
  const [page, setPage] = useState(0);

  // Load the client's bank accounts, then default to the first active one.
  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    (async () => {
      try {
        const supabase = getSupabaseClient();
        const { data: rows } = await selectAll(() => supabase
          .from("bank_accounts")
          .select("id, bank_name, account_no, ifsc, account_type, opening_balance_paise, opening_balance_date, coa_account_id, currency, is_active")
          .eq("client_id", clientId)
          .order("bank_name")
          .order("id"));
        const list = ((rows as BankAccount[]) ?? []).filter((a) => a.is_active);
        setAccounts(list);
        setBankAccountId((prev) => prev || (list[0]?.id ?? ""));
      } catch {
        setAccounts([]);
      }
    })();
  }, [clientId]);

  const load = useCallback(async () => {
    if (!bankAccountId) { setData(null); return; }
    setLoading(true); setLoadError(null);
    try {
      const res = (await api.banking.register({
        bank_account_id: bankAccountId,
        client_id: clientId,
        ...(dateFrom ? { date_from: dateFrom } : {}),
        ...(dateTo ? { date_to: dateTo } : {}),
        ...(status !== "all" ? { status } : {}),
        ...(search.trim() ? { q: search.trim() } : {}),
        sort,
        desc: String(desc),
        limit: String(PAGE_SIZE),
        offset: String(page * PAGE_SIZE),
      })) as { success: boolean; data: RegisterPayload; error: string | null };
      if (!res.success) throw new Error(res.error ?? "Couldn't load the register.");
      setData(res.data);
    } catch (e) {
      setData(null);
      setLoadError(e instanceof Error ? e.message : "Couldn't load the register.");
    } finally {
      setLoading(false);
    }
  }, [bankAccountId, clientId, dateFrom, dateTo, status, search, sort, desc, page]);
  useEffect(() => { load(); }, [load]);

  // Changing what is being looked at returns to the first page; changing the
  // page must not.
  useEffect(() => { setPage(0); }, [bankAccountId, dateFrom, dateTo, status, search, sort, desc]);

  function toggleSort(col: RegisterSort) {
    if (sort === col) setDesc((d) => !d);
    else { setSort(col); setDesc(col === "date" ? false : true); }
  }

  function exportCsv() {
    if (!data) return;
    const rows = [
      ["Date", "Description", "Reference", "Category", "Withdrawal", "Deposit", "Balance", "Cleared", "Posted"],
      ...data.lines.map((l) => [
        l.transaction_date ?? "", l.description, l.reference_no ?? "", l.category ?? "",
        l.debit_paise ? (l.debit_paise / 100).toFixed(2) : "",
        l.credit_paise ? (l.credit_paise / 100).toFixed(2) : "",
        (l.balance_paise / 100).toFixed(2),
        l.cleared || "", l.posted_journal_id ? "Yes" : "No",
      ]),
    ];
    const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\r\n");
    // Leading BOM so Excel reads the ₹ and Indian names as UTF-8.
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `register-${data.account?.account_no ?? "account"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const filtersActive = !!(dateFrom || dateTo || status !== "all" || search.trim());
  const summary = data?.summary;
  const totalPages = data ? Math.max(1, Math.ceil(data.filtered_count / PAGE_SIZE)) : 1;

  // A plain function, not a component: declaring a component inside the render
  // gives it a new identity every keystroke, so React remounts these headers and
  // the search box loses focus mid-typing.
  //
  // The alignment classes are spelled out rather than built as `text-${align}` —
  // Tailwind scans source text, so an interpolated class name only survives by
  // accident (because some other line in this file happens to use it).
  const ALIGN = { left: "text-left", right: "text-right", center: "text-center" } as const;
  const sortHead = (col: RegisterSort, label: string, align: keyof typeof ALIGN = "left") => (
    <th key={col} className={`px-3 py-2 font-medium ${ALIGN[align]} whitespace-nowrap`}>
      <button onClick={() => toggleSort(col)} className="inline-flex items-center gap-1 hover:text-[#334155]">
        {label}{sort === col && <span className="text-[9px]">{desc ? "▼" : "▲"}</span>}
      </button>
    </th>
  );

  if (accounts.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-10 text-center max-w-3xl mx-auto">
        <Landmark size={24} className="mx-auto text-[#CBD5E1]" />
        <p className="text-sm text-[#94A3B8] mt-2">No bank account yet.</p>
        <p className="text-[11px] text-[#94A3B8] mt-1">
          Add one under <strong>Accounts</strong>, then import a statement — the register
          builds itself from what the bank sent.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Account + filters */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-3 flex flex-wrap items-end gap-3">
        <label className="block">
          <span className="text-[10px] font-medium text-[#64748B]">Account</span>
          <select value={bankAccountId} onChange={(e) => setBankAccountId(e.target.value)}
            className="mt-1 block border border-[#E2E8F0] rounded px-2 py-1.5 text-xs">
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>{a.bank_name} · ****{a.account_no.slice(-4)}</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-[10px] font-medium text-[#64748B]">From</span>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
            className="mt-1 block border border-[#E2E8F0] rounded px-2 py-1.5 text-xs" />
        </label>
        <label className="block">
          <span className="text-[10px] font-medium text-[#64748B]">To</span>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
            className="mt-1 block border border-[#E2E8F0] rounded px-2 py-1.5 text-xs" />
        </label>
        <label className="block">
          <span className="text-[10px] font-medium text-[#64748B]">Show</span>
          <select value={status} onChange={(e) => setStatus(e.target.value as RegisterStatus)}
            className="mt-1 block border border-[#E2E8F0] rounded px-2 py-1.5 text-xs">
            {REGISTER_STATUSES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </label>
        <label className="block flex-1 min-w-[160px]">
          <span className="text-[10px] font-medium text-[#64748B]">Search</span>
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Narration, reference or category"
            className="mt-1 block w-full border border-[#E2E8F0] rounded px-2 py-1.5 text-xs" />
        </label>
        <div className="flex items-center gap-2">
          {filtersActive && (
            <button onClick={() => { setDateFrom(""); setDateTo(""); setStatus("all"); setSearch(""); }}
              className="text-[11px] px-2 py-1.5 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569]">
              Clear
            </button>
          )}
          <button onClick={load} disabled={loading}
            className="text-[11px] px-2 py-1.5 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569] inline-flex items-center gap-1">
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
          <button onClick={exportCsv} disabled={!data || data.lines.length === 0}
            className="text-[11px] px-2 py-1.5 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#475569] inline-flex items-center gap-1 disabled:opacity-40">
            <Download size={11} /> CSV
          </button>
        </div>
      </div>

      {/* The self-check the bank makes possible: our running balance against the
          balance column the statement itself carried. */}
      {data?.divergence && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
          <p className="text-xs font-semibold text-amber-900">
            This register stops agreeing with the statement on {data.divergence.transaction_date}
          </p>
          <p className="text-[11px] text-amber-800 mt-1">
            After “{data.divergence.description}” the bank says the balance was{" "}
            <span className="font-mono">{fmt(data.divergence.statement_balance_paise ?? 0)}</span>;
            from the imported lines it works out to{" "}
            <span className="font-mono">{fmt(data.divergence.computed_balance_paise)}</span> — a
            difference of <span className="font-mono font-semibold">{fmt(Math.abs(data.divergence.delta_paise))}</span>.
          </p>
          <p className="text-[11px] text-amber-700 mt-1">
            Usually a missing, duplicated or misdated line, or an opening balance that needs
            correcting under Accounts. Only the first mismatch is shown — every balance after
            it inherits the same difference.
          </p>
        </div>
      )}

      {summary && summary.precedes_opening_count > 0 && (
        <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-2.5">
          <p className="text-[11px] text-blue-800">
            {summary.precedes_opening_count} transaction{summary.precedes_opening_count === 1 ? " is" : "s are"} dated
            before this account&apos;s opening balance
            {data?.account?.opening_balance_date ? ` (${data.account.opening_balance_date})` : ""} and{" "}
            {summary.precedes_opening_count === 1 ? "is" : "are"} shown but not added to the running
            balance — the opening figure already includes {summary.precedes_opening_count === 1 ? "it" : "them"}.
          </p>
        </div>
      )}

      {/* Totals for the WHOLE account, not the filtered page. */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: "Opening balance", value: fmt(summary.opening_balance_paise), tone: "text-[#0F172A]" },
            { label: "Deposits", value: fmt(summary.deposits_paise), tone: "text-green-700" },
            { label: "Withdrawals", value: fmt(summary.withdrawals_paise), tone: "text-red-700" },
            { label: "Closing balance", value: fmt(summary.closing_balance_paise), tone: "text-[#0F172A] font-semibold" },
          ].map((c) => (
            <div key={c.label} className="bg-white rounded-xl border border-[#F1F5F9] px-4 py-3">
              <p className="text-[10px] text-[#94A3B8] uppercase tracking-wide">{c.label}</p>
              <p className={`text-sm font-mono mt-0.5 ${c.tone}`}>{c.value}</p>
            </div>
          ))}
        </div>
      )}

      {loading ? <TableSkeleton cols={6} rows={8} /> : loadError ? (
        <div className="bg-white rounded-xl border border-red-200 p-10 text-center">
          <p className="text-sm text-red-600 font-medium mb-2">{loadError}</p>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      ) : !data || data.lines.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-10 text-center">
          <p className="text-sm text-[#94A3B8]">
            {filtersActive ? "Nothing matches these filters." : "No transactions on this account yet."}
          </p>
          {!filtersActive && (
            <p className="text-[11px] text-[#94A3B8] mt-1">Import a statement under <strong>Accounts</strong>.</p>
          )}
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-[#F8FAFC] text-[#64748B] border-b border-[#F1F5F9]">
                <tr>
                  {sortHead("date", "Date")}
                  {sortHead("description", "Description")}
                  <th className="px-3 py-2 font-medium text-left whitespace-nowrap">Category</th>
                  {sortHead("cleared", "✓", "center")}
                  {sortHead("amount", "Withdrawal", "right")}
                  <th className="px-3 py-2 font-medium text-right whitespace-nowrap">Deposit</th>
                  {sortHead("balance", "Balance", "right")}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {/* The balance immediately before the first row shown. Without it
                    a filtered register does not visibly add up. */}
                {page === 0 && (
                  <tr className="bg-[#FCFCFD] text-[#64748B]">
                    <td className="px-3 py-1.5 whitespace-nowrap">
                      {filtersActive || sort !== "date" || desc ? "Balance before this view" : "Opening balance"}
                    </td>
                    <td className="px-3 py-1.5" colSpan={5} />
                    <td className="px-3 py-1.5 text-right font-mono">{fmt(data.view_opening_balance_paise)}</td>
                  </tr>
                )}
                {data.lines.map((l) => (
                  <tr key={l.transaction_id}
                      className={`hover:bg-[#F8FAFC] ${l.precedes_opening ? "text-[#94A3B8]" : ""}`}>
                    <td className="px-3 py-1.5 whitespace-nowrap text-[#475569]">{l.transaction_date ?? "—"}</td>
                    <td className="px-3 py-1.5 min-w-[220px]">
                      <span className="text-[#1E293B]">{l.description}</span>
                      {l.reference_no && <span className="text-[10px] text-[#94A3B8] ml-1.5">{l.reference_no}</span>}
                      {!l.posted_journal_id && (
                        <span className="text-[9px] px-1 py-0.5 rounded bg-[#F1F5F9] text-[#64748B] ml-1.5">not posted</span>
                      )}
                      {l.precedes_opening && (
                        <span className="text-[9px] px-1 py-0.5 rounded bg-blue-50 text-blue-700 ml-1.5">before opening</span>
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-[#64748B] whitespace-nowrap">{l.category ?? "—"}</td>
                    <td className="px-3 py-1.5 text-center">
                      {l.cleared === "R" ? (
                        <span title="Reconciled — part of a completed reconciliation"
                              className="text-[10px] font-semibold text-green-700">R</span>
                      ) : l.cleared === "C" ? (
                        <span title="Cleared — claimed by a reconciliation still in progress"
                              className="text-[10px] font-semibold text-amber-600">C</span>
                      ) : <span className="text-[#CBD5E1]">—</span>}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-red-700 whitespace-nowrap">
                      {l.debit_paise ? fmt(l.debit_paise) : ""}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-green-700 whitespace-nowrap">
                      {l.credit_paise ? fmt(l.credit_paise) : ""}
                    </td>
                    <td className={`px-3 py-1.5 text-right font-mono whitespace-nowrap ${
                      l.balance_paise < 0 ? "text-red-700" : "text-[#0F172A]"}`}>
                      {fmt(l.balance_paise)}
                      {!!l.balance_delta_paise && (
                        <span title={`The statement said ${fmt(l.statement_balance_paise ?? 0)} here`}
                              className="ml-1 text-[9px] text-amber-600">≠</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="px-3 py-2 border-t border-[#F1F5F9] flex items-center justify-between text-[11px] text-[#64748B]">
            <span>
              {data.filtered_count === data.total_count
                ? `${data.total_count} transaction${data.total_count === 1 ? "" : "s"}`
                : `${data.filtered_count} of ${data.total_count}`}
              {summary && summary.unposted_count > 0 && ` · ${summary.unposted_count} not yet posted`}
            </span>
            {totalPages > 1 && (
              <span className="flex items-center gap-2">
                <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}
                  className="px-2 py-1 border border-[#E2E8F0] rounded disabled:opacity-40 hover:bg-[#F8FAFC]">Previous</button>
                <span>Page {page + 1} of {totalPages}</span>
                <button onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}
                  className="px-2 py-1 border border-[#E2E8F0] rounded disabled:opacity-40 hover:bg-[#F8FAFC]">Next</button>
              </span>
            )}
          </div>
        </div>
      )}

      <p className="text-[10px] text-[#94A3B8] text-center">
        The register is read-only. A posted journal cannot be edited — correct it with a
        reversal from the Accounting workspace, and the register will follow.
      </p>
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
      const firmId = await getFirmId();
      const { data, error } = await selectAll(() => supabase
        .from("chart_of_accounts")
        .select("id, account_code, account_name, account_type, account_subtype, is_active, client_id")
        // firm_id explicitly, not RLS alone. CLAUDE.md: the app-layer filter is
        // the primary isolation control and the policy is defence in depth —
        // this query had only the policy.
        .eq("firm_id", firmId)
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
        {tab === "register"   && <BankRegister clientId={clientId} />}
        {tab === "categorize" && <BankMatchQueue clientId={clientId} accounts={accounts} />}
        {tab === "reconcile"  && <BankReconciliation clientId={clientId} />}
        {tab === "rules"      && <BankRules clientId={clientId} accounts={accounts} />}
      </div>
    </div>
  );
}
