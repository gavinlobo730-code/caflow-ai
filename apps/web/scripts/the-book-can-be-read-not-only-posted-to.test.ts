/**
 * FOUR READING SURFACES THE ENGINE ALREADY HAD ANSWERS FOR.
 *
 * The 12 September probe pass named two shapes that recur across every slice:
 * "an engine that is finished, correct and reachable from no screen", and "a
 * figure the server computes and the response drops". These four are those two
 * shapes in the accounting and inventory modules.
 *
 *   ACC-13 — the DAY BOOK. The Journal tab shows manual entries only, and its
 *   own comment already described the missing half: "QuickBooks, Xero and Zoho
 *   Books … split it the same way: a Manual Journals list of what a human
 *   wrote, and a separate Journal/General Ledger REPORT carrying every
 *   posting." The report did not exist, so "everything that hit the books on
 *   14 August" meant opening each account's ledger in turn. The data was
 *   already on the client — loadEntries fetches every entry in the window and
 *   the browser discarded the non-manual ones.
 *
 *   ACC-23 — `closing_entry_dates`. Computed by year_end_financial_service,
 *   declared in lib/api/yearEnd.ts, rendered nowhere. It exists because a CA
 *   who posts their own closing entry dates it at the year end, so it lands
 *   INSIDE the P&L window and cancels what it closes: the statement reads nil
 *   and nothing says why.
 *
 *   ACC-24 — the account-group tree. Two columns nothing writes at seeding
 *   time, so a normally-onboarded firm opened Account Groups to one
 *   "Ungrouped → General" block holding all 57 accounts.
 *
 *   INV-04 — `last_movement_date` and `movements`. public.stock_position_as_at
 *   has returned both per item since migration 363 and the screen dropped them
 *   in its map, so "which stock has not moved" was computed, shipped and
 *   thrown away on every dated register.
 *
 * Plus INV-10, which is not a surfacing bug but the same complaint: the two
 * actions a CA takes on a stock row lived only inside the drill-down.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function code(file: string): string {
  return fs.readFileSync(path.join(WEB, file), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

const ACCOUNTING = "app/clients/[id]/accounting/page.tsx";
const INVENTORY = "app/clients/[id]/inventory/page.tsx";
const GROUPS = "app/accounting/account-groups/page.tsx";
const STATEMENTS = "app/clients/[id]/year-end/[engagementId]/financial-statements/_page.tsx";

// ── ACC-13: the day book ─────────────────────────────────────────────────────

test("the accounting workspace offers a day book", () => {
  const page = code(ACCOUNTING);
  assert.match(page, /id:\s*"day-book"/,
    "no Day Book tab — a CA still cannot ask what hit the books on a given day");
  assert.match(page, /mode="day_book"/,
    "the tab must render JournalList in day-book mode, off the same fetch");
});

test("the day book shows every posting, not the manual ones", () => {
  const page = code(ACCOUNTING);
  // The filter must be conditional. If `source_type === "manual"` is applied
  // unconditionally the day book is the Journal tab with a different heading.
  assert.match(
    page,
    /dayBook\s*\?\s*entries\s*:\s*entries\.filter\(\(e\)\s*=>\s*e\.source_type === "manual"\)/,
    "the day book must take the unfiltered entries; the manual filter belongs to the Journal tab alone");
});

test("the day book is read-only, because nothing on this screen may act on an auto-posted entry", () => {
  const page = code(ACCOUNTING);
  assert.match(page, /bulkActions=\{dayBook \? undefined : journalBulkActions\}/,
    "approve, reverse and delete are all manual-entry actions and the server "
    + "refuses each of them for anything else — offering them over a mostly "
    + "document-sourced list offers a refusal in bulk");
  assert.match(page, /!dayBook && \(\s*<button/,
    "New Journal Entry belongs on the Journal tab; the day book is a report");
});

test("the day book names where each voucher came from, and derives the name", () => {
  const page = code(ACCOUNTING);
  assert.match(page, /function sourceLabel/,
    "the Source column must derive its label from the value");
  assert.doesNotMatch(page, /SOURCE_LABELS/,
    "a hardcoded label map is a second copy of ALL_SOURCES (apps/api/domain/"
    + "accounting/journal_source.py) and drifts the first time a source is added");
  assert.match(page, /key: "source_type", header: "Source"/,
    "no Source column — the point of the day book is telling an invoice's "
    + "posting apart from something somebody typed");
});

test("the two tables do not share their stored column preferences", () => {
  const page = code(ACCOUNTING);
  assert.match(page, /persistKey=\{dayBook \? "accounting\.dayBook" : "accounting\.journal"\}/,
    "one key across two column sets carries the day book's Source preference "
    + "back to a tab that has no such column");
});

// ── ACC-23: the closing entry ────────────────────────────────────────────────

test("the P&L says when a closing entry is why it reads nil", () => {
  const page = code(STATEMENTS);
  assert.match(page, /closing_entry_dates/,
    "closing_entry_dates is computed and typed and must be rendered — a nil "
    + "P&L with no explanation reads as a bug in the software rather than an "
    + "entry in the books");
  // On the P&L tab specifically: the balance sheet is unaffected by a close
  // and a warning there would be wrong.
  const plTab = page.slice(page.indexOf('tab === "profit_loss"'));
  assert.match(plTab.slice(0, 2500), /closing_entry_dates/,
    "the notice belongs on the Profit & Loss tab — the Balance Sheet is "
    + "self-correcting across a close and needs no warning");
});

// ── ACC-24: the group tree ───────────────────────────────────────────────────

test("account groups fall back to the account's own type rather than Ungrouped", () => {
  const page = code(GROUPS);
  assert.match(page, /acc\.parent_group \?\? acc\.account_type/,
    "a seeded firm has no parent_group on any of its 57 accounts, so the "
    + "screen showed one Ungrouped block; derive from the account's own type");
  assert.match(page, /acc\.sub_group \?\? acc\.account_subtype/,
    "same for the second level");
});

test("a derived group says it is derived", () => {
  const page = code(GROUPS);
  assert.match(page, /derived\.has\(pg\)/,
    "a CA must be able to tell the groups they filed from the ones the screen "
    + "worked out, or the tree looks like a decision nobody made");
});

// ── INV-04: what has not moved ───────────────────────────────────────────────

test("the dated stock register keeps the two fields the SQL function returns", () => {
  const page = code(INVENTORY);
  assert.match(page, /last_movement_date: r\.last_movement_date/,
    "the map into StockItem dropped it — migration 363 has returned "
    + "MAX(movement_date) per item all along");
  assert.match(page, /movements: r\.movements/, "and the movement count");
  assert.match(page, /header: "Last Moved"/, "no column renders it");
  assert.match(page, /header: "Days Idle"/, "nor the figure a CA actually sorts by");
});

test("days idle is measured against the register's own date, not today", () => {
  const page = code(INVENTORY);
  assert.match(page, /function daysIdle\(lastMoved[^)]*asAt: string\)/,
    "daysIdle must take the as-at date — a register as at 31 March that "
    + "measured idleness against today describes a different year");
  assert.match(page, /if \(!lastMoved \|\| !asAt\) return null/,
    "and refuse rather than substituting today, which would be a silently "
    + "different question");
});

test("the current-position register does NOT claim to know when stock last moved", () => {
  const page = code(INVENTORY);
  // The deliberate half. api.inventory.items() reads each item's CHAIN HEAD,
  // which is insertion-ordered, so its movement_date is the date most recently
  // ENTERED — not the latest date stock moved. A backdated purchase separates
  // them, and "days idle" off the wrong one is exactly the figure a CA acts on.
  assert.match(page, /asAtColumns/,
    "the idleness columns must be added only in as-at mode");
  assert.match(page, /const columns = asAt\s*\?\s*\[\.\.\.allColumns\.filter/,
    "and the current-position register must not carry them");
});

// ── INV-10: acting from the register ─────────────────────────────────────────

test("the stock register offers its two actions on the row", () => {
  const page = code(INVENTORY);
  assert.match(page, /key: "actions"/,
    "Adjust and Write Down lived only inside the drill-down, so acting on a "
    + "row meant opening it first");
  assert.match(page, /setRowAction\(\{ item: i, kind: "adjust" \}\)/);
  assert.match(page, /setRowAction\(\{ item: i, kind: "writedown" \}\)/);
  assert.match(page, /e\.stopPropagation\(\)/,
    "the row itself opens the drill-down; a click must not do both");
});

test("the as-at register offers no actions, because both modals say 'currently'", () => {
  const page = code(INVENTORY);
  assert.match(page, /c\.key !== "is_active" && c\.key !== "actions"/,
    "AdjustStockModal prints 'Currently N on hand' and NrvWritedownModal "
    + "'Current average cost is ₹X/unit', both off item.stock_qty_units / "
    + "item.avg_cost_paise — which in as-at mode are the figures as at that "
    + "date. Offering the action there states a historical position as the "
    + "current one and takes an entry against it.");
});
