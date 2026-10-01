/**
 * The spreadsheet side of the voucher import (accounting-17).
 *
 * LIKE `openingDocumentImport`, THIS CONVERTS AND DECIDES NOTHING. Whether a
 * voucher balances, which ledger a cell names, whether a date is open, whether a
 * number is already on the books and what a type may be are all
 * `domain/accounting/voucher_import`'s answers (CLAUDE.md: zero business logic in
 * the frontend). What is here is what only the browser can do: name the two
 * templates' columns, turn a typed amount into integer paise through the ONE
 * parser, expand a one-row-per-voucher sheet into the legs the server judges,
 * split a long file into requests small enough to finish, and turn the server's
 * per-voucher verdicts back into what `CsvImportModal` reports.
 *
 * TWO LAYOUTS, ONE SHAPE ON THE WIRE. A voucher is a set of legs sharing a
 * voucher number. Bookkeepers keep two kinds of sheet — a line per ledger entry
 * (the only way a journal of five lines can be written down) and a line per
 * voucher ("Dr account, Cr account, amount", which is how a payment book is). The
 * second is expanded to its two legs HERE, on the same row number, so the server
 * has exactly one thing to judge.
 *
 * AN UNREADABLE AMOUNT STILL TRAVELS, AS NULL — dropping the row would take it
 * out of the report — and a BLANK one travels as 0, which is what "the other
 * side of this line" means on a leg that carries only a debit.
 *
 * REQUESTS ARE BATCHES OF VOUCHERS, NEVER OF LINES. Each posted voucher is
 * several database round trips, and the browser abandons a request at 45 seconds
 * without retrying — so two hundred vouchers in one request would outlive their
 * own caller halfway through and leave the CA not knowing which half landed.
 * `chunkVouchers` keeps every leg of a voucher in one request (the server judges
 * a voucher whole) and the answers are added up. Because the server recognises a
 * voucher it already holds, a failed batch is recovered by uploading the file
 * again.
 */
import { paiseFromRupeeInput } from "../money/rupeeInput.ts";
import type { VoucherImportLeg, VoucherImportResult } from "../api/index.ts";

export type VoucherLayout = "lines" | "simple";
export type VoucherStatus = "draft" | "posted";

export interface VoucherColumn {
  key: string;
  label: string;
  required: boolean;
  hint?: string;
}

/** Vouchers per request. Each post is a handful of Singapore-to-Mumbai round
 *  trips; twenty keeps a request far inside the browser's 45 seconds. */
export const VOUCHERS_PER_REQUEST = 20;

export function voucherColumns(layout: VoucherLayout): VoucherColumn[] {
  const common: VoucherColumn[] = [
    { key: "voucher_no", label: "Voucher number", required: true,
      hint: layout === "lines"
        ? "Your number — every line of one voucher shares it, and a re-upload is recognised by it"
        : "Your number for this voucher; a re-upload is recognised by it" },
    { key: "date", label: "Date", required: true,
      hint: "dd-mm-yyyy or yyyy-mm-dd (not a two-digit year)" },
    { key: "voucher_type", label: "Type", required: true,
      hint: "Journal, Payment, Receipt or Contra" },
  ];
  if (layout === "lines") {
    return [
      ...common,
      { key: "account", label: "Ledger", required: true,
        hint: "The ledger's name or code, as in this client's chart" },
      { key: "debit", label: "Debit (₹)", required: false, hint: "Leave blank on a credit line" },
      { key: "credit", label: "Credit (₹)", required: false, hint: "Leave blank on a debit line" },
      { key: "narration", label: "Narration", required: false, hint: "For the voucher" },
      { key: "line_narration", label: "Line narration", required: false, hint: "Optional, for this line" },
    ];
  }
  return [
    ...common,
    { key: "debit_account", label: "Debit ledger", required: true,
      hint: "Name or code of the ledger debited" },
    { key: "credit_account", label: "Credit ledger", required: true,
      hint: "Name or code of the ledger credited" },
    { key: "amount", label: "Amount (₹)", required: true, hint: "e.g. 1,25,000.00" },
    { key: "narration", label: "Narration", required: false, hint: "Optional" },
  ];
}

const text = (v: string | undefined): string => (v ?? "").trim();

/** A rupee cell through the one parser: blank is 0, a cell that is not an
 *  amount is null. The currency symbol and Indian commas are taken off first. */
function cellPaise(v: string | undefined): number | null {
  const cleaned = text(v).replace(/[,\s₹]/g, "");
  return cleaned === "" ? 0 : paiseFromRupeeInput(cleaned);
}

/**
 * Spreadsheet rows → the legs the server judges.
 *
 * `rowNumbers` are the preview's own numbers for the rows handed over — the
 * dialog passes only the rows that cleared ITS checks, so position is not number.
 */
export function buildVoucherLegs(
  rows: Record<string, string>[], layout: VoucherLayout, rowNumbers?: number[],
): VoucherImportLeg[] {
  const out: VoucherImportLeg[] = [];
  rows.forEach((r, i) => {
    const row = rowNumbers?.[i] ?? i + 1;
    const head = {
      row,
      voucher_no: text(r.voucher_no),
      date: text(r.date),
      voucher_type: text(r.voucher_type),
    };
    if (layout === "lines") {
      out.push({
        ...head,
        account: text(r.account),
        debit_paise: cellPaise(r.debit),
        credit_paise: cellPaise(r.credit),
        narration: text(r.narration) || null,
        line_narration: text(r.line_narration) || null,
      });
      return;
    }
    const amount = cellPaise(r.amount);
    const narration = text(r.narration) || null;
    out.push(
      { ...head, account: text(r.debit_account), debit_paise: amount, credit_paise: 0, narration, line_narration: null },
      { ...head, account: text(r.credit_account), debit_paise: 0, credit_paise: amount, narration, line_narration: null },
    );
  });
  return out;
}

/**
 * Legs → batches of whole vouchers, in the order each voucher first appears.
 *
 * Grouped by voucher number rather than by adjacency: a journal sheet is
 * sometimes sorted by date, which scatters one voucher's lines, and the server
 * judges a voucher only when it sees every leg of it in one request. Vouchers
 * with a blank number share one group, so the server reports them together.
 */
export function chunkVouchers(
  legs: VoucherImportLeg[], size: number = VOUCHERS_PER_REQUEST,
): VoucherImportLeg[][] {
  const order: string[] = [];
  const groups = new Map<string, VoucherImportLeg[]>();
  for (const leg of legs) {
    const key = leg.voucher_no.trim();
    if (!groups.has(key)) { groups.set(key, []); order.push(key); }
    groups.get(key)!.push(leg);
  }
  const batches: VoucherImportLeg[][] = [];
  for (let i = 0; i < order.length; i += size) {
    batches.push(order.slice(i, i + size).flatMap((k) => groups.get(k)!));
  }
  return batches;
}

/** Several batches' answers, added up. */
export function mergeVoucherResults(parts: VoucherImportResult[]): VoucherImportResult {
  const base: VoucherImportResult = {
    status: parts[0]?.status ?? "posted", dry_run: false, vouchers: 0, created: 0,
    would_create: 0, already_recorded: 0, rejected: 0, created_paise: 0,
    would_create_paise: 0, results: [],
  };
  for (const p of parts) {
    base.vouchers += p.vouchers;
    base.created += p.created;
    base.would_create += p.would_create;
    base.already_recorded += p.already_recorded;
    base.rejected += p.rejected;
    base.created_paise += p.created_paise;
    base.would_create_paise += p.would_create_paise;
    base.results.push(...(Array.isArray(p.results) ? p.results : []));
  }
  return base;
}

export interface ImportOutcome {
  imported: number;
  errors: string[];
  skipped: number;
  skippedDetail: string[];
}

const rowsLabel = (rows: number[]): string =>
  `${rows.length === 1 ? "Row" : "Rows"} ${rows.join(", ")}`;

/** The server's verdicts as the dialog's counters and lists: a voucher already
 *  on the books is SKIPPED (which is what a re-upload is), a refused one is an
 *  ERROR carrying its number, its rows and ALL its problems. */
export function voucherOutcomeFrom(result: VoucherImportResult): ImportOutcome {
  const rows = Array.isArray(result.results) ? result.results : [];
  const who = (r: { voucher_no: string; rows: number[] }) =>
    `${r.voucher_no ? `Voucher ${r.voucher_no}` : "Voucher with no number"} (${rowsLabel(Array.isArray(r.rows) ? r.rows : [])})`;
  return {
    imported: result.created,
    skipped: result.already_recorded,
    skippedDetail: rows
      .filter((r) => r.status === "already_recorded")
      .map((r) => `${who(r)}: already on the books — nothing added`),
    errors: rows
      .filter((r) => r.status === "rejected")
      .map((r) => `${who(r)}: ${(Array.isArray(r.problems) ? r.problems : []).join(" ")}`),
  };
}

/** What the screen says once the dialog closes. */
export function voucherSummarySentence(
  result: VoucherImportResult, status: VoucherStatus, rupees: (p: number) => string,
): string {
  const where = status === "posted" ? "posted to the ledger" : "saved as drafts — off the books until posted";
  const parts = [`${result.created} voucher${result.created === 1 ? "" : "s"} ${where}`
    + (result.created ? ` (${rupees(result.created_paise)})` : "")];
  if (result.already_recorded) parts.push(`${result.already_recorded} already there`);
  if (result.rejected) parts.push(`${result.rejected} refused`);
  return `${parts.join(", ")}.`;
}
