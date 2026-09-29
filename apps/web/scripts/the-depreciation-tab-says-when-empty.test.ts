/**
 * apex-bank-assets-inventory-12b.
 *
 * WHAT WAS WRONG
 *     The Depreciation tab's hand-rolled `<table>` had no branch for
 *     `rows.length === 0` — the `loading ? … : loadFailed ? … : (<table>…)`
 *     ternary fell straight to the table, so a client with no assets (or none
 *     eligible for depreciation) saw a bare header row over a fully empty
 *     body with no explanatory text at all. The sibling Asset Register tab on
 *     the very same page already handles this correctly.
 *
 * THE FIX
 *     A `rows.length === 0` branch between the `loadFailed` branch and the
 *     table, matching the wording the fixed-assets Reports tab's own
 *     empty-register message already uses ("No assets in the register for
 *     this client.").
 *
 * Run with:
 *   node --experimental-strip-types --test scripts/the-depreciation-tab-says-when-empty.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = path.join(WEB, "app", "clients", "[id]", "fixed-assets", "page.tsx");

function depreciationTabSource(): string {
  const src = fs.readFileSync(PAGE, "utf8");
  const start = src.indexOf("// ── Depreciation Tab ");
  const end = src.indexOf("// ── Disposal Tab ");
  assert.ok(start >= 0, "the Depreciation Tab section marker is missing");
  assert.ok(end > start, "the Disposal Tab section marker is missing");
  const section = src.slice(start, end);
  assert.ok(section.length > 3_000, "the extracted Depreciation Tab section looks too short");
  return section;
}

test("the Depreciation tab has an empty-register branch before the table", () => {
  const s = depreciationTabSource();
  // The exact ternary shape: loading, then loadFailed, then an explicit
  // rows.length === 0 check, and only then the table.
  assert.match(s, /loadFailed \? \(/, "the loadFailed branch must still be there");
  const afterFailed = s.slice(s.indexOf("loadFailed ? ("));
  assert.match(afterFailed, /rows\.length === 0 \? \(/,
    "no explicit empty-register branch between the failure state and the table");
  const emptyBranch = afterFailed.slice(afterFailed.indexOf("rows.length === 0 ? ("));
  const tableAt = emptyBranch.indexOf("<table");
  assert.ok(tableAt >= 0, "the table must still exist after the empty branch");
  const emptyBody = emptyBranch.slice(0, tableAt);
  assert.match(emptyBody, /No assets in the register for this client\./,
    "the empty state must say plainly that there is nothing to show, the same " +
    "wording the Reports tab already uses for an empty register");
  assert.doesNotMatch(emptyBody, /<thead/, "the empty branch must not render the table header");
});

test("a client with rows still sees the real table, unaffected by the new branch", () => {
  const s = depreciationTabSource();
  assert.match(s, /rows\.map\(\(r\) => \(/, "the populated table must still map over rows");
  assert.match(s, /<th className="px-4 py-3 text-left font-semibold">Asset<\/th>/,
    "the table header must be untouched");
});
