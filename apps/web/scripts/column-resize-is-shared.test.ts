// Column resize lives in the SHARED table, so every screen gets it.
//
// Asked for as "for all these kind of data like sales and purchase invoices
// like any kind" — which is the argument for putting it in DataTable rather
// than on the screen that prompted it. Twenty screens render DataTable; a
// resize handle built into the bank queue would have reached one.
//
// Source-level assertions, like the other scripts here: there is no DOM in
// this suite, and what these defend is structural — where the behaviour lives,
// that it is persisted, and that a drag cannot make a column vanish.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const TABLE = path.join(ROOT, "components/ui/data-table.tsx");
const HOOK = path.join(ROOT, "lib/table/useDataTable.ts");
const PREFS = path.join(ROOT, "lib/table/useTablePreferences.ts");

test("the resizer is in the shared table, not in one screen", () => {
  const src = fs.readFileSync(TABLE, "utf8");
  assert.match(src, /function ColumnResizer\(/,
    "the handle belongs to DataTable so all twenty screens inherit it");
  assert.match(src, /<ColumnResizer\b/, "and is actually rendered in the header");

  // A screen that grew its own would defeat the point.
  const pages = fs.readFileSync(path.join(ROOT, "app/clients/[id]/bank/page.tsx"), "utf8");
  assert.doesNotMatch(pages, /cursor-col-resize/,
    "a screen is growing its own resize handle — it belongs in the shared table");
});

test("a drag cannot take a column below a floor", () => {
  const hook = fs.readFileSync(HOOK, "utf8");
  assert.match(hook, /export const MIN_COLUMN_PX = \d+;/,
    "there has to be a floor — 'resized very small' must never become " +
    "'silently gone', which is the one thing the CA asked to prevent");
  assert.match(hook, /Math\.max\(MIN_COLUMN_PX,/,
    "and setColumnWidth has to enforce it, not merely declare it");
});

test("widths are persisted with the rest of the table's preferences", () => {
  const prefs = fs.readFileSync(PREFS, "utf8");
  assert.match(prefs, /columnWidths: Record<string, number>/,
    "widths join hiddenColumns/sort/pageSize in the persisted slice, so a " +
    "layout someone set survives a reload like everything else does");
  // Hydration spreads saved JSON over the defaults, which is what makes adding
  // a key safe for anyone with prefs saved before it existed.
  assert.match(prefs, /\.\.\.p, \.\.\.\(JSON\.parse\(raw\) as Partial<TablePrefs>\)/,
    "hydration must keep spreading over defaults, or older saved prefs would " +
    "arrive with no columnWidths at all");
});

test("a saved width actually reaches the header cell", () => {
  const src = fs.readFileSync(TABLE, "utf8");
  assert.match(src, /style=\{t\.state\.columnWidths\[c\.key\]/,
    "the header's style has to read the stored width — a resizer that stores a " +
    "number nothing renders is the likeliest way for this to look done and not be");
  assert.match(src, /minWidth: `\$\{t\.state\.columnWidths\[c\.key\]\}px`/,
    "width alone is a suggestion to the table layout; minWidth is what makes " +
    "a narrowed column stay narrowed");
});

test("resizing does not sort the column it is dragging", () => {
  const src = fs.readFileSync(TABLE, "utf8");
  const fn = src.slice(src.indexOf("function ColumnResizer("));
  const body = fn.slice(0, fn.indexOf("\n}\n"));
  const down = body.slice(body.indexOf("const onPointerDown"));
  assert.match(down.slice(0, down.indexOf("};")), /e\.stopPropagation\(\)/,
    "POINTER-DOWN is where it matters: the header is a sort control, and " +
    "without stopping it there every drag also re-sorts the table underneath");
  assert.match(body, /onDoubleClick=\{\(e\) => \{ e\.stopPropagation\(\); onReset/,
    "double-click restores the default — the way out of a layout dragged into " +
    "a mess, and it must not sort either");
});
