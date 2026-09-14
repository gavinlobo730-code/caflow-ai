/**
 * SALES-21 — the browser must not decide what these documents are.
 *
 * Which of CGST Rule 55's movements a delivery challan covers, what it must
 * contain, whether its lines bear tax, and which deemed-supply clock runs —
 * CGST s.143's one or three years, s.31(7)'s six months, or none — are all
 * `domain/gst/delivery_challan.py`'s answers. A copy of any of them here is a
 * second place for the rule to be wrong, and this one is what the CA reads.
 *
 * The specific failure this guards against is not hypothetical: `/accounting/
 * retainer` rendered a document headed TAX INVOICE, numbered from a
 * browser-local counter, taxed at a hardcoded CGST 9% + SGST 9%, with a Print
 * button. Three of the four documents here are NOT tax invoices, and one of
 * them is called a proforma INVOICE.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const TAB = "components/sales/SalesCycleTab.tsx";
const PAGE = "app/clients/[id]/sales/page.tsx";
const API = "lib/api/index.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the screen holds no statute of its own", () => {
  const src = code(TAB);
  // Every statutory sentence is the server's, rendered verbatim.
  assert.match(src, /vocab\.not_a_tax_invoice/);
  // BOTH places, asserted separately. An alternation passes on a commit that
  // paraphrases either one — and the two are read at different moments: the
  // overdue banner the moment the tab opens, the detail panel when the CA
  // drills into a challan.
  assert.match(src, /\{c\.clock\.consequence\}/,
    "the overdue banner, the moment the tab opens");
  assert.match(src, /\{detail\.clock\.consequence\}/,
    "the detail panel, when the CA drills into one challan");
  assert.match(src, /detail\.itc_04\.refusal/);
  // And none of the periods or their arithmetic is restated here.
  assert.doesNotMatch(src, /\bs\.143\(3\)|one year|three years|six months/i);
  assert.doesNotMatch(src, /12\s*\*\s*30|365|addMonths|setMonth/);
});

test("the reasons and the kinds of goods come from the server", () => {
  const src = code(TAB);
  assert.match(src, /vocab\.challan_reasons\.map/);
  assert.match(src, /vocab\.goods_kinds\.map/);
  assert.match(src, /vocab\.quote_kinds\.map/);
  // Not a hardcoded list. `job_work` appears only as the value the form
  // defaults to and compares against for the goods-kind field.
  const occurrences = (src.match(/"liquid_gas_quantity_unknown"/g) || []).length;
  assert.equal(occurrences, 0,
    "Rule 55's vocabulary is the server's, not a literal here");
});

test("whether a movement is a supply is the server's answer", () => {
  /* Rule 55(1)(vii) requires tax on the challan only "where the transportation
     is for supply to the consignee", and which movements those are is the
     domain module's list. A copy here would drift from the one that decides
     what is actually charged. */
  const src = code(TAB);
  assert.match(src, /is_a_supply/);
  assert.doesNotMatch(src, /reason\s*===\s*"supply_invoice_to_follow"/);
});

test("the overdue and undecided counts are read off the server's clock", () => {
  const src = code(TAB);
  assert.match(src, /c\.clock\?\.overdue === true/);
  assert.match(src, /\(c\.clock\?\.gaps \|\| \[\]\)\.length > 0/);
  // A challan whose clock cannot be run is NOT counted as safe: s.143's
  // periods differ by a factor of three and the module refuses to pick one.
  assert.match(src, /undecided/);
});

test("no tax is computed in the browser", () => {
  /* The acronyms DO appear here, in labels citing the Act — "CGST Rule 55",
     "CGST s.143" — which is a citation and not a calculation. What must not
     appear is a tax FIGURE: no per-head paise, no rate arithmetic. */
  const src = code(TAB);
  assert.doesNotMatch(src, /cgst_paise|sgst_paise|igst_paise|cess_paise/i);
  assert.doesNotMatch(src, /\*\s*0?\.18|18\s*\/\s*100|\/\s*10000/);
  assert.doesNotMatch(src, /gst_rate_bps/);
  // And the sentence explaining why a non-supply carries none is the
  // server's, not a paraphrase of Rule 55(1)(vii) written here.
  assert.match(src, /vocab\.no_tax_on_a_non_supply/);
  assert.doesNotMatch(src, /Rule 55\(1\)\(vii\)/);
});

test("amounts and quantities go through the one parser", () => {
  /* CLAUDE.md: nothing whose name ends in _paise may be built with a numeric
     coercion or a multiplication by 100; a quantity is NUMERIC(10,3). */
  const src = code(TAB);
  assert.match(src, /paiseFromRupeeInput\(/);
  assert.match(src, /parseQuantity\(/);
  assert.doesNotMatch(src, /parseFloat/);
  assert.doesNotMatch(src, /rate[\s\S]{0,30}\*\s*100/);
});

test("the tab is reachable from the client sales screen", () => {
  const src = code(PAGE);
  assert.match(src, /\{ id: "sales-cycle", label: "Quotes, Orders & Challans" \}/);
  assert.match(src, /tab === "sales-cycle" && \(/);
  assert.match(src, /<SalesCycleTab clientId=\{clientId\} \/>/);
});

test("the api layer carries shapes and no statute", () => {
  const src = code(API);
  const start = src.indexOf("salesCycle: {");
  assert.ok(start > 0, "the namespace exists");
  const ns = src.slice(start, start + 3000);
  assert.match(ns, /\/api\/sales-cycle\/vocabulary/);
  assert.match(ns, /\/api\/sales-cycle\/challans/);
  assert.match(ns, /\/api\/sales-cycle\/orders\/\$\{id\}\/position/);
  assert.match(ns, /method: "PATCH"/);
  // Reading is a GET. A position is derived server-side and never posted.
  assert.doesNotMatch(ns, /position[\s\S]{0,120}method: "POST"/);
});

test("nothing here prints a document calling itself a tax invoice", () => {
  /* `/accounting/retainer` rendered exactly that, under the firm's own GSTIN,
     numbered from a browser-local counter — two devices collide, so Rule
     46(b)'s "unique for a financial year" cannot hold — and taxed at a
     hardcoded 9% + 9%. Three of these four documents are not tax invoices and
     one of them is called a proforma INVOICE, so the confusion is one edit
     away. */
  const src = code(TAB);
  assert.doesNotMatch(src, /TAX INVOICE/i);
  assert.doesNotMatch(src, /window\.print|Print/);
  assert.doesNotMatch(src, /localStorage|sessionStorage/);
});
