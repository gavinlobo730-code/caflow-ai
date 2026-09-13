// §43B(h) is derived from the purchase ledger, not typed in again.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-43bh-working-is-derived-not-retyped.test.ts
//
// PUR-15. /accounting/msme-tracker asked the CA to re-key every bill —
// supplier, invoice number, invoice date, amount, agreement type, payment date
// — into `msme_payments` over PostgREST, and then computed the whole statutory
// rule in TypeScript. Three defects in one screen:
//
//   * the figure was a RE-KEYING of data the books already hold, so it drifted
//     the moment a bill was corrected or a payment recorded the ordinary way;
//   * `rbac()` never runs on a direct PostgREST write;
//   * a §43B(h) disallowance — which changes taxable income — was being
//     decided in the browser.
//
// And the rule it carried was wrong in the direction that matters: it read the
// agreement type per INVOICE ROW off a dropdown, so a CA who picked "written"
// got 45 days on a supplier with no written agreement at all, where MSMED
// §2(b) gives 15.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");
/** Source with comments stripped — what actually runs and renders. */
const code = (src: string) =>
  src.replace(/\{\/\*[\s\S]*?\*\/\}/g, " ")
     .replace(/\/\*[\s\S]*?\*\//g, " ")
     .replace(/^\s*\/\/.*$/gm, " ");

const PAGE = code(read("app/accounting/msme-tracker/page.tsx"));

test("the screen no longer writes the hand-keyed side table", () => {
  assert.doesNotMatch(PAGE, /msme_payments/,
    "the re-keyed table is back, and with it the drift");
  assert.doesNotMatch(PAGE, /getSupabaseClient/,
    "a direct PostgREST call from this screen means rbac() never runs");
  assert.doesNotMatch(PAGE, /\.insert\(/);
});

test("it asks the server for the working", () => {
  assert.match(PAGE, /api\.incomeTax\.msme43bh\(clientId, fy\)/);
  assert.match(code(read("lib/api/index.ts")),
    /\/api\/income-tax\/msme-43bh\?client_id=/);
});

test("a refusal is shown, not swallowed", () => {
  assert.match(PAGE, /if \(!r\.success\)/,
    "the envelope's error must reach the screen");
});

test("the statutory rule is not computed in the browser", () => {
  // The three things the old page worked out for itself. Every one of them is
  // now a field on the response.
  assert.doesNotMatch(PAGE, /=== "written" \? 45 : 15/);
  assert.doesNotMatch(PAGE, /function computeStatus/);
  assert.doesNotMatch(PAGE, /function addDays/);
  assert.doesNotMatch(PAGE, /disallowed_paise = row\.amount_paise/);
  // …and nothing else adds days to a date or picks a limit here.
  assert.doesNotMatch(PAGE, /setDate\(/);
  assert.doesNotMatch(PAGE, /\b45\b/,
    "forty-five is the exception under the proviso to MSMED §15, not a number " +
    "this screen gets to choose");
});

test("it renders both directions of the clause", () => {
  // A disallowance this year and a release of an earlier year's disallowance
  // are different figures in different rows of the computation, and a screen
  // that shows only the first understates the deduction.
  assert.match(PAGE, /working\.disallowed_paise/);
  assert.match(PAGE, /working\.allowed_on_payment_paise/);
  assert.match(PAGE, /Added back to taxable income/);
  assert.match(PAGE, /Allowed back this year, on payment/);
});

test("the suppliers left OUT of the working are named", () => {
  // THE POINT. An unclassified vendor contributes nothing, so the figure above
  // is understated by whatever they are owed — and no number on the screen can
  // say so.
  assert.match(PAGE, /working\.gaps\.map/);
  assert.match(PAGE, /not\s+in this working, and should be/);
});

test("the caveats travel with the figure", () => {
  // That the first proviso to §43B does not reach clause (h), and that the
  // MSMED clock starts at acceptance rather than the bill date. A working
  // shown without those is one a CA would rely on.
  assert.match(PAGE, /working\.caveats\.map/);
});

test("the financial year comes from the clock", () => {
  assert.match(PAGE, /financialYearChoicesAround\(\)/);
  assert.doesNotMatch(PAGE, /const FY_OPTIONS/);
});

test("it is per client, and says why when none is picked", () => {
  assert.match(PAGE, /§43B\(h\) is a figure in one client&apos;s tax computation/);
});

test("the export carries the working, not a re-keyed list", () => {
  assert.match(PAGE, /working\.bills\.map/);
  assert.match(PAGE, /"MSMED s\.15 limit \(days\)"/);
});
