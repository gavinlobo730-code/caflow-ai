// A physical stock count is one sheet, and the browser computes none of it
// (INV-08).
//
// Run with:
//   node --experimental-strip-types --test scripts/a-physical-count-is-one-sheet.test.ts
//
// WHAT WAS WRONG
//     Stock adjustment was one item per API call and one item per modal,
//     opened only from inside an item's ledger drill-down. Stock-taking at
//     31 March produces a sheet with a hundred variances, so the CA opened
//     each item's ledger a hundred times — and the hundred journals had no
//     common reference tying them to the count.
//
// THE RULE, WHICH IS THE DURABLE HALF
//     The variance, its direction, its reason, whether a line may post and
//     why not are all domain/inventory/count_session.py's answers, recomputed
//     on the server against the position AS AT THE COUNT DATE. This screen
//     renders them and derives nothing.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const SHEET = "components/inventory/StockCountSheet.tsx";
const PAGE = "app/clients/[id]/inventory/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the register can start a count, and reopens the one already open", () => {
  const src = code(PAGE);
  // Matched inside the BUTTON, not on the words: "Physical count — shortage
  // found" is one of the adjustment reasons and appears twice in this file,
  // so a bare search for the phrase would pass with no entry point at all.
  const button = src.match(/<button onClick=\{startCount\}[\s\S]*?<\/button>/);
  assert.ok(button, "the entry point exists on the register");
  assert.match(button![0], /"Physical count"/, "…and it says what it is");
  // Opening a sheet is a server WRITE. The label is allowed to change while
  // it is in flight — it must — so what is asserted is the disable.
  assert.match(button![0], /disabled=\{openingCount\}/,
    "…and cannot be clicked twice");
  assert.match(src, /api\.inventory\.openCountSession\(/);
  assert.match(src, /api\.inventory\.countSessions\(/,
    "an existing open sheet must be reopened, not collided with — migration "
    + "387 allows only one per client per date");
});

test("the variance comes off the wire and is never computed here", () => {
  const src = code(SHEET);
  assert.match(src, /l\.variance_qty_units/, "the figure is the server's");
  assert.match(src, /l\.will_post/, "and so is whether the line posts");
  // Subtracting the two quantities in the browser would give a DIFFERENT
  // answer from the server's the moment the books move under the sheet.
  assert.doesNotMatch(src, /counted[\w.]*\s*-\s*(system|current)/i,
    "no variance arithmetic here");
  assert.doesNotMatch(src, /"increase"\s*:\s*"decrease"/,
    "the direction is the server's answer, not a ternary here");
});

test("every refusal shown is a sentence that came off the wire", () => {
  const src = code(SHEET);
  assert.match(src, /l\.gaps\.map/, "why a line will not post");
  assert.match(src, /l\.caveats\.map/, "and what the server could not settle");
  assert.match(src, /sheet\?\.gaps\.map/, "and the sheet-level ones");
  assert.doesNotMatch(src, /Not counted yet/,
    "the server says why a line is blocked; a second wording here would drift");
});

test("blank is a third state on the count and on the s.17(5)(h) decision", () => {
  const src = code(SHEET);
  assert.match(src, /t\.trim\(\) === "" \? null : parseQuantity\(t\)/,
    "a blank count goes as null, never as zero — a zero writes the item's "
    + "stock off");
  assert.match(src, /decision === "" \? null : decision === "yes"/,
    "an undecided reversal goes as null, never as false");
});

test("the quantity is parsed once, by the one parser", () => {
  const src = code(SHEET);
  assert.match(src, /from "@\/lib\/money\/rupeeInput"/);
  assert.match(src, /parseQuantity\(/);
  assert.doesNotMatch(src, /parseFloat\(|Number\(\s*typed/,
    "lib/money/rupeeInput is the only parser; NUMERIC(10,3) is what the "
    + "ledger keeps");
});

test("a line that could not post is shown, not swallowed", () => {
  const src = code(SHEET);
  assert.match(src, /result\.failed\.map/,
    "the batch is not atomic — a line that failed leaves the books "
    + "disagreeing with the count and the CA has to be told which");
  assert.match(src, /result\.failed_count/);
});

test("the s.17(5)(h) question is asked only where the section reaches", () => {
  const src = code(SHEET);
  assert.match(src, /l\.direction === "decrease" && open \?/,
    "a surplus is stock FOUND, so there is no credit to reverse");
});
