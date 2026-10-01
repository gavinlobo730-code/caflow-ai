/**
 * The spreadsheet side of the fixed-asset register import (accounting-18).
 *
 * LIKE `openingDocumentImport` AND `voucherImport`, THIS CONVERTS AND DECIDES
 * NOTHING. Which category Schedule II holds, which basis an asset gets, whether
 * an accumulated depreciation is possible for its cost, whether a code is already
 * on the register and what a re-upload means are all
 * `domain/fixed_assets/opening_register`'s answers (CLAUDE.md: zero business
 * logic in the frontend). What is here is what only the browser can do: name the
 * template's columns, turn a typed amount into integer paise through the ONE
 * parser, and turn the server's per-row verdicts back into what `CsvImportModal`
 * reports.
 *
 * MONEY: a REQUIRED amount that is blank travels as null — never as a nil — so the
 * server refuses it by row number. "Blank is 0" is how every optional amount
 * column in this app reads (`paiseFromRupeeInput`), and it is exactly wrong here:
 * a column header that did not match would otherwise arrive as a hundred assets
 * that have never been depreciated, to be charged from scratch on top of the
 * balance the opening trial balance carries. The dialog also blocks a blank in a
 * required column, so this is the second line, not the only one.
 *
 * THE POSITION DATE IS CHOSEN, NEVER DEFAULTED. It decides which month the next
 * depreciation run starts at. The choices are derived from the clock — a year
 * picker is never listed (`a-financial-year-choice-comes-from-the-clock`) — and
 * the server refuses anything that is not a 31 March that has passed.
 */
import { paiseFromRupeeInput } from "../money/rupeeInput.ts";
import { financialYearChoices, fyRangeFor } from "../dates/periods.ts";

export interface OpeningRegisterColumn {
  key: string;
  label: string;
  required: boolean;
  hint?: string;
}

/** What the server answers for one row. */
export interface OpeningRegisterRowResult {
  row: number;
  asset_code: string;
  status: "new" | "would_create" | "already_recorded" | "rejected";
  problems: string[];
  warnings: string[];
  id: string | null;
}

export interface OpeningRegisterClassTotals {
  asset_category: string;
  assets: number;
  cost_paise: number;
  accumulated_paise: number;
  net_paise: number;
}

export interface OpeningRegisterResult {
  as_at: string;
  dry_run: boolean;
  received: number;
  created: number;
  would_create: number;
  already_recorded: number;
  rejected: number;
  cost_paise: number;
  accumulated_paise: number;
  net_paise: number;
  by_category: OpeningRegisterClassTotals[];
  gaps: string[];
  next_depreciation_month: string | null;
  ledger_note: string;
  rows: OpeningRegisterRowResult[];
}

/** One row as the server takes it. Money is paise or null; the rest is as typed. */
export interface OpeningRegisterRowOut {
  row: number;
  asset_code: string;
  asset_name: string;
  asset_category: string;
  purchase_date: string;
  put_to_use_date: string | null;
  cost_paise: number | null;
  accumulated_depreciation_paise: number | null;
  salvage_value_paise: number | null;
  depreciation_method: string | null;
  useful_life_years: string | null;
  wdv_rate_percent: string | null;
  it_block_key: string | null;
  location: string | null;
  notes: string | null;
}

/**
 * The template's columns. `categories` is what the SERVER holds
 * (`GET /api/fixed-assets/categories`), used only to word the hint — the browser
 * keeps no list of them, the Schedule III caption lesson.
 */
export function openingRegisterColumns(categories: string[] = []): OpeningRegisterColumn[] {
  return [
    { key: "asset_code", label: "Asset code", required: true,
      hint: "Your own tag — what a re-upload is recognised by. Not in the form FA-0001." },
    { key: "asset_name", label: "Asset name", required: true },
    { key: "asset_category", label: "Category", required: true,
      hint: categories.length
        ? `One of: ${categories.join(", ")}`
        : "A Schedule II category, as on Add Asset" },
    { key: "purchase_date", label: "Purchase date", required: true,
      hint: "dd-mm-yyyy or yyyy-mm-dd (not a two-digit year)" },
    { key: "cost", label: "Cost (₹)", required: true,
      hint: "What the asset stands at in the books, e.g. 12,50,000.00" },
    { key: "accumulated_depreciation", label: "Accumulated depreciation (₹)", required: true,
      hint: "As at the date you choose — write 0 if none, never leave it blank" },
    { key: "depreciation_method", label: "Method", required: false,
      hint: "WDV or SL — required except for Land" },
    { key: "put_to_use_date", label: "Put to use on", required: false,
      hint: "For the Income-tax Act s.32 working; never assumed to be the purchase date" },
    { key: "salvage_value", label: "Salvage value (₹)", required: false },
    { key: "useful_life_years", label: "Useful life (years)", required: false,
      hint: "Blank takes Schedule II's life for the category" },
    { key: "wdv_rate_percent", label: "WDV rate (%)", required: false,
      hint: "Blank takes the rate derived from the category's life" },
    { key: "it_block_key", label: "Income-tax block", required: false,
      hint: "Your own label for the s.32 block" },
    { key: "location", label: "Location", required: false },
    { key: "notes", label: "Notes", required: false },
  ];
}

const text = (v: string | undefined): string => (v ?? "").trim();
const orNull = (v: string | undefined): string | null => text(v) || null;

/** An amount cell, with the rupee sign and Indian commas taken off first. */
function cleaned(v: string | undefined): string {
  return text(v).replace(/[,\s₹]/g, "");
}

/** A REQUIRED amount: blank is null (unknown), never 0. */
function requiredPaise(v: string | undefined): number | null {
  const c = cleaned(v);
  return c === "" ? null : paiseFromRupeeInput(c);
}

/** An OPTIONAL amount: blank is nothing, which for a salvage value is 0. */
function optionalPaise(v: string | undefined): number | null {
  const c = cleaned(v);
  return c === "" ? 0 : paiseFromRupeeInput(c);
}

/**
 * Spreadsheet rows → the rows the server judges.
 *
 * `rowNumbers` are the preview's own numbers for the rows handed over — the
 * dialog passes only the rows that cleared ITS checks, so position is not number.
 */
export function buildOpeningRegisterRows(
  rows: Record<string, string>[], rowNumbers?: number[],
): OpeningRegisterRowOut[] {
  return rows.map((r, i) => ({
    row: rowNumbers?.[i] ?? i + 1,
    asset_code: text(r.asset_code),
    asset_name: text(r.asset_name),
    asset_category: text(r.asset_category),
    purchase_date: text(r.purchase_date),
    put_to_use_date: orNull(r.put_to_use_date),
    cost_paise: requiredPaise(r.cost),
    accumulated_depreciation_paise: requiredPaise(r.accumulated_depreciation),
    salvage_value_paise: optionalPaise(r.salvage_value),
    depreciation_method: orNull(r.depreciation_method),
    useful_life_years: orNull(r.useful_life_years),
    wdv_rate_percent: orNull(r.wdv_rate_percent),
    it_block_key: orNull(r.it_block_key),
    location: orNull(r.location),
    notes: orNull(r.notes),
  }));
}

export interface ImportOutcome {
  imported: number;
  errors: string[];
  skipped: number;
  skippedDetail: string[];
}

const who = (r: { row: number; asset_code: string }) =>
  `${r.asset_code ? `Asset ${r.asset_code}` : "Asset with no code"} (row ${r.row})`;

/** The server's verdicts as the dialog's counters and lists: an asset already on
 *  the register is SKIPPED (which is what a re-upload is), a refused one is an
 *  ERROR carrying its code, its row and ALL its problems. */
export function openingRegisterOutcome(result: OpeningRegisterResult): ImportOutcome {
  const rows = Array.isArray(result.rows) ? result.rows : [];
  return {
    imported: result.created,
    skipped: result.already_recorded,
    skippedDetail: rows
      .filter((r) => r.status === "already_recorded")
      .map((r) => `${who(r)}: already on the register — nothing added`),
    errors: rows
      .filter((r) => r.status === "rejected")
      .map((r) => `${who(r)}: ${(Array.isArray(r.problems) ? r.problems : []).join(" ")}`),
  };
}

/** What the screen says once the dialog closes. */
export function openingRegisterHeadline(
  result: OpeningRegisterResult, rupees: (p: number) => string,
): string {
  const n = result.created;
  const parts = [
    `${n} asset${n === 1 ? "" : "s"} brought over as at ${result.as_at}`
    + (n ? ` — cost ${rupees(result.cost_paise)}, accumulated depreciation `
      + `${rupees(result.accumulated_paise)}, net block ${rupees(result.net_paise)}` : ""),
  ];
  if (result.already_recorded) parts.push(`${result.already_recorded} already on the register`);
  if (result.rejected) parts.push(`${result.rejected} refused`);
  return `${parts.join("; ")}.`;
}

/** The warnings the server attached to rows that DID land, each with its asset. */
export function openingRegisterWarnings(result: OpeningRegisterResult): string[] {
  const rows = Array.isArray(result.rows) ? result.rows : [];
  return rows
    .filter((r) => r.status === "new" && Array.isArray(r.warnings) && r.warnings.length > 0)
    .flatMap((r) => r.warnings.map((w) => `${who(r)}: ${w}`));
}

export interface PositionChoice {
  /** ISO date, which the server reads. */
  value: string;
  label: string;
}

const MONTHS_END = "31 March";

/**
 * The 31 Marches a position can be stated as at, newest first, derived from the
 * clock. A year that has not ended is not offered: an accumulated depreciation
 * cannot be stated as at a date that has not happened (the server refuses it too).
 */
export function positionChoices(count: number = 4, today: Date = new Date()): PositionChoice[] {
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-`
    + String(today.getDate()).padStart(2, "0");
  return financialYearChoices(count + 1, today)
    .map((fy) => ({ fy, end: fyRangeFor(fy).end }))
    .filter(({ end }) => end <= todayIso)
    .slice(0, count)
    .map(({ fy, end }) => ({
      value: end,
      label: `${MONTHS_END} ${end.slice(0, 4)} — the end of FY ${fy}`,
    }));
}
