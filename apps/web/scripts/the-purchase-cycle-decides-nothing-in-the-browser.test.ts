/**
 * PUR-25 — the browser must not decide what these documents mean.
 *
 * Two statutes turn on the goods receipt, and neither may be paraphrased
 * here: CGST s.16(2)(b) conditions the input tax credit on the goods having
 * been RECEIVED, and MSMED s.15 runs its fifteen days from the day of
 * ACCEPTANCE, which s.2(b)'s Explanation makes the day of actual delivery.
 * Both sentences are `domain/purchases/three_way_match.py`'s, served through
 * `GET /api/purchase-cycle/vocabulary`.
 *
 * And the match must not acquire a tolerance here. "Within 2%" is a firm's
 * procurement policy, not a rule; a tolerance in the browser would pass a
 * discrepancy the server reported and somebody has to look at.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const TAB = "components/purchases/PurchaseCycleTab.tsx";
const PAGE = "app/clients/[id]/purchases/page.tsx";
const API = "lib/api/index.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("both statutory sentences are the server's, rendered verbatim", () => {
  const src = code(TAB);
  assert.match(src, /\{vocab\.posts_nothing\}/);
  assert.match(src, /\{vocab\.msmed_acceptance\}/);
  // And neither is restated here.
  assert.doesNotMatch(src, /16\(2\)\(b\)/);
  assert.doesNotMatch(src, /fifteen days|15 days/i);
  assert.doesNotMatch(src, /appointed day/i);
});

test("the differences, the gaps and the caveats are rendered, never filtered", () => {
  /* A tolerance applied here would pass a discrepancy the server reported.
     Each list is mapped whole. */
  const src = code(TAB);
  assert.match(src, /matched\.differences\.map/);
  assert.match(src, /matched\.gaps\.map/);
  assert.match(src, /matched\.caveats\.map/);
  assert.doesNotMatch(src, /differences\.filter|gaps\.filter/);
  assert.doesNotMatch(src, /Math\.abs\([\s\S]{0,40}>\s*\d/);
});

test("the acceptance date and its reason are the server's", () => {
  const src = code(TAB);
  assert.match(src, /matched\.acceptance_date/);
  assert.match(src, /matched\.acceptance_source/);
  // Never derived here from a receipt list.
  assert.doesNotMatch(src, /Math\.max\([\s\S]{0,60}received_on/);
  assert.doesNotMatch(src, /receipts[\s\S]{0,40}\.sort\([\s\S]{0,60}received_on/);
});

test("the open statuses come from the server, not a literal list", () => {
  const src = code(TAB);
  assert.match(src, /vocab\?\.order_open_statuses \|\| \[\]/);
  assert.doesNotMatch(src, /"partially_received"/);
  assert.doesNotMatch(src, /"approved"/);
});

test("an open objection is surfaced, because the clock has not started", () => {
  const src = code(TAB);
  assert.match(src, /g\.objection_raised_on && !g\.objection_removed_on/);
  assert.match(src, /openObjections/);
});

test("no tax and no acceptance arithmetic happens in the browser", () => {
  const src = code(TAB);
  assert.doesNotMatch(src, /cgst_paise|sgst_paise|igst_paise/i);
  assert.doesNotMatch(src, /\*\s*0?\.18|18\s*\/\s*100|\/\s*10000/);
  assert.doesNotMatch(src, /setDate|setMonth|addDays/);
});

test("amounts and quantities go through the one parser", () => {
  const src = code(TAB);
  assert.match(src, /paiseFromRupeeInput\(/);
  assert.match(src, /parseQuantity\(/);
  assert.doesNotMatch(src, /parseFloat/);
  assert.doesNotMatch(src, /rate[\s\S]{0,30}\*\s*100/);
});

test("the tab is reachable from the client purchases screen", () => {
  const src = code(PAGE);
  assert.match(src, /\{ id: "purchase-cycle", label: "Orders & Goods Receipts" \}/);
  assert.match(src, /tab === "purchase-cycle" && <PurchaseCycleTab clientId=\{clientId\} \/>/);
});

test("the api layer carries shapes and no statute", () => {
  const src = code(API);
  const start = src.indexOf("purchaseCycle: {");
  assert.ok(start > 0, "the namespace exists");
  const ns = src.slice(start, start + 3000);
  assert.match(ns, /\/api\/purchase-cycle\/vocabulary/);
  assert.match(ns, /\/api\/purchase-cycle\/receipts/);
  assert.match(ns, /bills\/\$\{billId\}\/match/);
  assert.match(ns, /method: "PATCH"/);
  // The match is a READ. It posts nothing and blocks nothing.
  assert.doesNotMatch(ns, /match[\s\S]{0,140}method: "POST"/);
});

test("nothing here stores the CA's work in the browser", () => {
  const src = code(TAB);
  assert.doesNotMatch(src, /localStorage|sessionStorage/);
});
