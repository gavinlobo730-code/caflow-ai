/**
 * The spreadsheet side of bringing a client's open bills over (ACC-05).
 *
 * THIS MODULE CONVERTS AND DECIDES NOTHING. Which party a name means, how a
 * date is read, whether a number is already recorded and whether the parties
 * foot to their opening balances are all `domain/accounting/opening_document_
 * import`'s answers (CLAUDE.md: zero business logic in the frontend). What lives
 * here is what only the browser can do: name the template's columns, turn a
 * typed amount into integer paise through the ONE parser, and turn the server's
 * per-row verdicts back into the shape `CsvImportModal` reports.
 *
 * DATES ARE SENT AS TYPED. Reading `4/1/26` is the server's rule — and its rule
 * is to refuse it, because it could be 4 January or 1 April — so a browser that
 * "helpfully" normalised dates first would hide the very cell the server is
 * about to ask about.
 *
 * AN UNREADABLE AMOUNT STILL TRAVELS, AS NULL. Dropping the row here would take
 * it out of the report: the person would be told nothing about a row they typed.
 * The server refuses it by NUMBER with the rest of the file's problems.
 */
import { paiseFromRupeeInput } from "../money/rupeeInput.ts";
import type {
  OpeningDocumentBulkResult, OpeningDocumentImportRow,
} from "../api/index.ts";

export type OpeningKind = "receivable" | "payable";

export interface OpeningColumn {
  key: string;
  label: string;
  required: boolean;
  hint?: string;
}

/**
 * The template's columns. The words depend on which side is being imported —
 * "Customer"/"Invoice number" or "Vendor"/"Bill number" — and nothing else does:
 * the keys are the same for both, so one mapper serves both.
 */
export function openingDocumentColumns(kind: OpeningKind): OpeningColumn[] {
  const party = kind === "receivable" ? "Customer" : "Vendor";
  const number = kind === "receivable" ? "Invoice number" : "Bill number";
  return [
    { key: "party", label: party, required: true,
      hint: `${party} name, as recorded for this client` },
    { key: "party_gstin", label: `${party} GSTIN`, required: false,
      hint: "Optional — settles two parties with the same name" },
    { key: "document_no", label: number, required: true,
      hint: "The number the old system issued" },
    { key: "document_date", label: "Document date", required: true,
      hint: "dd-mm-yyyy or yyyy-mm-dd (not a two-digit year)" },
    { key: "due_date", label: "Due date", required: false,
      hint: "Optional; ageing falls back to the document date" },
    { key: "outstanding", label: "Still outstanding (₹)", required: true,
      hint: "What is STILL OPEN at the opening date, e.g. 1,25,000.00" },
    { key: "notes", label: "Notes", required: false, hint: "Optional" },
  ];
}

const text = (v: string | undefined): string => (v ?? "").trim();

/** A rupee cell with the marks a person puts in one taken off — the currency
 *  symbol, Indian thousands commas, stray spaces — then through the one parser.
 *  Null for blank and for anything that is not an amount. */
function amountPaise(v: string | undefined): number | null {
  const cleaned = text(v).replace(/[,\s₹]/g, "");
  return cleaned === "" ? null : paiseFromRupeeInput(cleaned);
}

/**
 * Spreadsheet rows → the bulk request's rows.
 *
 * `rowNumbers` are the preview's own numbers for the rows handed over
 * (`CsvImportModal` passes only the rows that cleared ITS checks, so position is
 * not number). Without them the position is used, which is only right when
 * nothing was held back.
 */
export function buildOpeningDocumentRows(
  rows: Record<string, string>[], rowNumbers?: number[],
): OpeningDocumentImportRow[] {
  return rows.map((r, i) => ({
    row: rowNumbers?.[i] ?? i + 1,
    party: text(r.party),
    party_gstin: text(r.party_gstin) || null,
    document_no: text(r.document_no),
    document_date: text(r.document_date),
    due_date: text(r.due_date) || null,
    outstanding_paise: amountPaise(r.outstanding),
    notes: text(r.notes) || null,
  }));
}

/** What `CsvImportModal` reports when it is done. */
export interface ImportOutcome {
  imported: number;
  errors: string[];
  skipped: number;
  skippedDetail: string[];
}

/**
 * The server's verdicts as the modal's three counters and two lists.
 *
 * "Already recorded" is the modal's SKIPPED, which is what a re-upload is: not a
 * failure and not new. A refused row is an ERROR carrying its number, its
 * document number and ALL its problems in the server's own words.
 */
export function importOutcomeFrom(result: OpeningDocumentBulkResult): ImportOutcome {
  const rows = Array.isArray(result.rows) ? result.rows : [];
  const label = (r: { row: number; document_no: string }) =>
    `Row ${r.row}${r.document_no ? ` (${r.document_no})` : ""}`;
  return {
    imported: result.created,
    skipped: result.already_recorded,
    skippedDetail: rows
      .filter((r) => r.status === "already_recorded")
      .map((r) => `${label(r)}: already recorded — nothing added`),
    errors: rows
      .filter((r) => r.status === "rejected")
      .map((r) => `${label(r)}: ${(Array.isArray(r.problems) ? r.problems : []).join(" ")}`),
  };
}

/** The sentence the tab shows once the import dialog is closed: what landed, and
 *  how many parties do not yet foot to their opening balance — the second half
 *  is the point of the screen, so it is said and not left for the CA to find. */
export function importSummarySentence(result: OpeningDocumentBulkResult, rupees: (p: number) => string): string {
  const parts = [
    `${result.created} document${result.created === 1 ? "" : "s"} recorded`
      + (result.created ? ` (${rupees(result.created_paise)})` : ""),
  ];
  if (result.already_recorded) parts.push(`${result.already_recorded} already there`);
  if (result.rejected) parts.push(`${result.rejected} refused`);
  const unreconciled = result.unreconciled_parties;
  const tail = unreconciled > 0
    ? ` ${unreconciled} ${unreconciled === 1 ? "party does" : "parties do"} not add up to the opening balance on the record — each is named below.`
    : " Every party's documents add up to its opening balance.";
  return `${parts.join(", ")}.${tail}`;
}
