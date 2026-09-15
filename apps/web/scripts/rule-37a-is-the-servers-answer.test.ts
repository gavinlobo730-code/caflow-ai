/**
 * CGST Rule 37A — the browser must not decide it (GST-28, second half).
 *
 * The one fact this product cannot hold is whether the SUPPLIER furnished
 * their GSTR-3B: GSTR-2B is generated FROM filed GSTR-1s and carries no 3B
 * status at all. Guessing "filed" leaves a reversal undone with §50 interest
 * running; guessing "not filed" reverses credit the client is entitled to. So
 * the screen renders the server's sentence and never fills the field in.
 *
 * And Rule 37A is NOT Rule 37. They share a reason code and a box on Table
 * 4(B)(2) and nothing else: one is about what the RECIPIENT did (the supplier
 * went unpaid for 180 days), the other about what the SUPPLIER did. Folding
 * the two panels together would make the CA chase the wrong party.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = "app/gst/gstr3b/page.tsx";
const DATA = "lib/data/gst.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the screen never fills in whether the supplier filed", () => {
  const src = code(PAGE);
  assert.doesNotMatch(src, /supplier_filed_gstr3b\s*[=:]/,
    "the one fact nobody holds must not be written here");
  assert.doesNotMatch(src, /supplier_filed_on/,
    "that column is the GSTR-1's date, and reading it would report every "
    + "supplier as compliant");
});

test("both deadlines and every sentence are the server's", () => {
  const src = code(PAGE);
  assert.match(src, /rule37a\.supplier_deadline/);
  assert.match(src, /rule37a\.recipient_deadline/);
  assert.match(src, /rule37a\.caveats\.map/);
  assert.match(src, /rule37a\.gaps\.map/);
  assert.match(src, /\{rule37a\.rule\}/);
  // And neither date is computed here.
  assert.doesNotMatch(src, /30 September|30 November|setMonth|new Date\(.*9, 30/);
});

test("Rule 37A is its own panel and is asked for the FINANCIAL YEAR", () => {
  /* Both deadlines hang off the END of the availment year, so a month is the
     wrong question — Rule 37, beside it, IS asked as at a period end. */
  const src = code(PAGE);
  assert.match(src, /fetchRule37AReport\(\s*\n?\s*clientId, financialYearOfMonth\(yearMonth\)\)/);
  assert.match(src, /fetchRule37Report\(clientId, periodEndDate\(yearMonth\)\)/);
  // Two separate state slots, two separate panels.
  assert.match(src, /setRule37a\(/);
  assert.match(src, /setRule37aError\(/);
});

test("a Rule 37A failure does not fail the return", () => {
  /* The figures above stand on their own — the same posture Rule 37 and Rule
     43 already take. */
  const src = code(PAGE);
  assert.match(src, /setRule37aError\(\s*\n?\s*e instanceof Error/);
  assert.match(src, /Rule 37A not checked/);
  assert.match(src, /The figures above are unaffected/);
});

test("the fetcher carries shapes and no statute", () => {
  const src = code(DATA);
  const start = src.indexOf("export async function fetchRule37AReport");
  assert.ok(start > 0, "the fetcher exists");
  const fn = src.slice(start, start + 700);
  assert.match(fn, /\/api\/gst-workspace\/itc\/rule37a/);
  assert.match(fn, /financial_year=/);
  // A read. It posts nothing.
  assert.doesNotMatch(fn, /apiPost|method: "POST"/);
});

test("the type says the supplier-filed field is always null", () => {
  /* A `boolean | null` would invite a screen to set it. */
  const src = fs.readFileSync(path.join(WEB, DATA), "utf8");
  const start = src.indexOf("export interface Rule37ASupplier");
  assert.ok(start > 0);
  const iface = src.slice(start, src.indexOf("}", start));
  assert.match(iface, /supplier_filed_gstr3b: null;/);
  assert.doesNotMatch(iface, /supplier_filed_gstr3b: boolean/);
});
