"use client";
// Shared bank types and helpers
//
// Moved verbatim out of app/clients/[id]/bank/page.tsx on 2026-09-03, when
// the bank module was rebuilt around ENTRIES (docs/architecture/09-bank-entries.md).
// The 4,964-line page was the reason small changes went unreviewed; each tab
// is its own file now. Behaviour here is unchanged by the move.

import { formatPaise } from "@/lib/services/formatting";

// ── Shared types & helpers ─────────────────────────────────────────────────
// Kept local rather than imported from the Accounting page: this route must not
// depend on that module, or the extraction buys nothing.

export interface Account {
  id: string;
  account_code: string;
  account_name: string;
  account_type: "Asset" | "Liability" | "Equity" | "Revenue" | "Expense";
  account_subtype: string | null;
  is_active: boolean;
  client_id: string | null;
}

export function fmt(paise: number): string {
  return paise === 0 ? "\u2014" : formatPaise(paise);
}

export function rsToP(rs: number): number {
  return Math.round(rs * 100);
}


export const BANK_CATEGORIES = [
  "Sales Receipt", "Customer Payment", "Vendor Payment", "Expense", "GST Payment",
  "Salary", "Loan", "Capital", "Transfer", "Interest", "Other",
];

export interface QueueTxn {
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
export interface MatchSuggestion {
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

export const AUTO_COUNTER_CATEGORIES = new Set(["Customer Payment", "Vendor Payment", "GST Payment"]);

/** Which of the server's refusals applies to this line, in the order
 *  posting_map.gst_split_allowed checks them. One function so the row's short
 *  label and the modal's sentence are always the same answer. */
export function gstWhy(t: QueueTxn): string {
  if (t.matched_entity_id) return "on the invoice";
  if (t.is_split) return "per split";
  if (t.category === "Transfer") return "not a supply";
  if (!t.account_id) return "pick a ledger";
  return "control account";
}

/** The short reason in the cell → the sentence behind it on hover. Mirrors
 *  posting_map.gst_split_allowed, which is the authority; these are words for
 *  its answers, never a second copy of the rule. */
export const GST_WHY_LONG: Record<string, string> = {
  "on the invoice": "This line settles an invoice or bill, and that document already carries its own GST. Taxing the bank line too would count the same tax twice.",
  "per split": "This line is allocated across several ledgers. A GST rate would need one rate per leg, which is not built yet.",
  "not a supply": "Moving money between your own accounts is not a supply, so no GST arises.",
  "pick a ledger": "Choose a ledger first — the split books the amount excluding tax there, so there is nowhere to put it yet.",
  "control account": "This posts to a control account like Trade Receivables or Trade Payables. Tax does not belong on one.",
};

export const GST_RATE_OPTIONS: { value: number; label: string }[] = [
  { value: 0, label: "0% — no GST" },
  { value: 500, label: "5%" },
  { value: 1200, label: "12%" },
  { value: 1800, label: "18%" },
  { value: 2800, label: "28%" },
];

export interface BankAccount {
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

