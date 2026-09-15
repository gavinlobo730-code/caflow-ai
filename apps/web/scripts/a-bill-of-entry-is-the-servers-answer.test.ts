/**
 * PUR-18 — the browser must not learn which part of an import is credit.
 *
 * CGST Act s.2(62)(a) makes the integrated tax on an import INPUT TAX; AS-2
 * paragraph 6 makes a duty recoverable from nobody part of the COST. That
 * split is the whole feature, and `domain/gst/bill_of_entry.py` is where it
 * lives. A copy of it in the browser is a second place for it to be wrong —
 * and the browser's copy is the one the CA reads.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const TAB = "components/purchases/BillsOfEntryTab.tsx";
const PAGE = "app/clients/[id]/purchases/page.tsx";
const API = "lib/api/index.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the tab computes neither the credit nor the cost", () => {
  /* Stated as the RULE rather than as two spellings of it. The first version
     of this test named `igst_paise - ineligible…` and `basic_customs_duty +`,
     and a negative control walked straight past the first by writing
     `r.igst_paise - r.ineligible_igst_paise` — the `r.` the regex did not
     allow. So: no arithmetic on ANY raw tax or duty column in this file. The
     derived figures are the server's and are read, never rebuilt. */
  const src = code(TAB);
  const RAW = [
    "igst_paise", "cess_paise", "basic_customs_duty_paise",
    "social_welfare_surcharge_paise", "other_duty_paise",
    "ineligible_igst_paise", "ineligible_cess_paise",
  ];
  for (const col of RAW) {
    // `x.col +`, `x.col -`, `+ x.col`, `- x.col` — any of them is the split
    // being re-derived. A column name inside a payload literal (`igst_paise:`)
    // or a type is untouched by this.
    assert.doesNotMatch(src, new RegExp(`\\.${col}\\s*[-+*]`),
      `${col} is the server's to combine, not the browser's`);
    assert.doesNotMatch(src, new RegExp(`[-+*]\\s*[\\w.]*\\.${col}\\b`),
      `${col} is the server's to combine, not the browser's`);
  }
  // It may READ the derived figures; it must not build them.
  assert.match(src, /r\.creditable_igst_paise/);
  assert.match(src, /r\.non_creditable_duty_paise/);
});

test("the two citations come off the wire, never spelled here", () => {
  const src = code(TAB);
  assert.match(src, /authorities\.credit_authority/);
  assert.match(src, /authorities\.cost_authority/);
  assert.match(src, /authorities\.table_4a_row/);
  assert.doesNotMatch(src, /"CGST Act s\.2\(62\)/);
  assert.doesNotMatch(src, /"AS-2 paragraph 6"/);
});

test("a refusal and a caveat are rendered as different things", () => {
  /* A refusal stops a posting; a caveat is true and stops nothing. Rendering
     the two the same way turns a note into a block — the same distinction the
     s.31(3)(f) panel draws between `reasons` and `gaps`. */
  const src = code(TAB);
  assert.match(src, /r\.refusals\.map/);
  assert.match(src, /r\.caveats\.map/);
  const post = src.match(/<button onClick=\{\(\) => handlePost\(r\)\}[\s\S]*?<\/button>/);
  assert.ok(post, "the post control exists");
  assert.match(post![0], /!r\.can_post/,
    "the server decides whether it can post, not a re-test of the refusals");
});

test("what the document cannot say is rendered", () => {
  const src = code(TAB);
  assert.match(src, /not_modelled\.map/,
    "deferred duty, a s.27 refund and the INV-05 apportionment are named");
});

test("every typed amount goes through the one money parser", () => {
  const src = code(TAB);
  assert.match(src, /paiseFromRupeeInput/);
  assert.doesNotMatch(src, /parseFloat/);
  assert.doesNotMatch(src, /Number\([^)]*\)\s*\*\s*100/);
});

test("posting is confirmed and cannot be double-fired", () => {
  /* The confirmation has to be asserted INSIDE handlePost. Asserting that the
     file calls confirmDialog somewhere passes on the withdraw handler's call —
     a negative control that removed the posting one stayed green. */
  const src = code(TAB);
  const handler = src.match(/async function handlePost\(r: BillOfEntry\)[\s\S]*?\n  \}/);
  assert.ok(handler, "handlePost exists");
  assert.match(handler![0], /await confirmDialog\(/,
    "posting writes a journal, so it is an explicit confirmation");
  assert.match(handler![0], /if \(!ok\) return;/,
    "and declining it must stop the write");
  const post = src.match(/<button onClick=\{\(\) => handlePost\(r\)\}[\s\S]*?<\/button>/);
  assert.match(post![0], /disabled=\{busy/);
});

test("the tab is reachable from the purchases screen", () => {
  const src = code(PAGE);
  assert.match(src, /\{ id: "bills-of-entry", label: "Bills of Entry" \}/);
  assert.match(src, /tab === "bills-of-entry" && <BillsOfEntryTab/);
});

test("the api layer carries shapes and no statute", () => {
  const src = code(API);
  const start = src.indexOf("billsOfEntry: {");
  assert.ok(start > 0, "the namespace exists");
  const ns = src.slice(start, start + 1600);
  assert.match(ns, /\/api\/bills-of-entry\/authorities/);
  // Posting is a write and must be one.
  assert.match(ns, /\/post[\s\S]{0,120}method: "POST"/);
});
