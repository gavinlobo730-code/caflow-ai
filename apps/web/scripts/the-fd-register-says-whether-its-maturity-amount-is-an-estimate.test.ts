// The fixed-deposit register does not present an estimate as the bank's figure. Run with:
//   node --experimental-strip-types --test scripts/the-fd-register-says-whether-its-maturity-amount-is-an-estimate.test.ts
//
// WHY THIS EXISTS
//     The register computed the maturity amount in the browser as annual compounding, inserted it as though it were the bank's
//     and showed it under "Total Maturity Value" and "Maturity Amt" with nothing to say it was an estimate (the form's own
//     preview was headed "Auto-calculated"). Banks usually compound a cumulative deposit quarterly and a payout deposit does
//     not compound, so it could differ from the receipt. The row carries a flag now (migration 521), the form takes the
//     receipt's amount, and every place that shows the figure says which it is. The arithmetic and the choice live in
//     lib/loans/fdMaturity.ts (unit-tested); this holds the page to using them.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const PAGE = path.join(import.meta.dirname, "..", "app/accounting/loans/page.tsx");
const src = fs.readFileSync(PAGE, "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/^\s*\/\/.*$/gm, "");

test("the page uses the shared helper and keeps no estimator of its own", () => {
  assert.match(src, /from "@\/lib\/loans\/fdMaturity"/);
  assert.doesNotMatch(src, /function calculateFDMaturityPaise|Math\.pow\(1 \+ annualRatePercent/,
    "a second copy of the estimate is the thing that drifts from the first");
});

test("the insert stores the flag the helper decided, and the amount the helper chose", () => {
  assert.match(src, /maturity_amount_paise: maturity\.paise,/);
  assert.match(src, /maturity_amount_is_estimate: maturity\.isEstimate,/);
  assert.match(src, /if \(!maturity\.ok\) \{ setFDError\(maturity\.error\); return; \}/,
    "a typed receipt amount that is not an amount, or is below the principal, is refused in words");
});

test("the form takes the receipt's amount through the one parser and a preview says it is an estimate", () => {
  assert.match(src, /Maturity amount per the deposit receipt/);
  assert.match(src, /Estimated maturity amount/);
  assert.doesNotMatch(src, /Auto-calculated (Maturity Amount)?/, "an estimate is not 'auto-calculated' into a fact");
});

test("the register marks an estimated row and the total says when it includes estimates", () => {
  assert.match(src, /isEstimate\(fd\) && \(/);
  assert.match(src, />\s*est\.\s*</);
  assert.match(src, /anyFDMaturityEstimated \? "includes estimates" : "per the deposit receipts"/);
});

test("the stored row's type carries the flag as optional, so an older database reads as an estimate", () => {
  assert.match(src, /maturity_amount_is_estimate\?: boolean;/);
});
