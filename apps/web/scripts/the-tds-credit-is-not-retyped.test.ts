// IT-31, the frontend half. The reconciliation could know exactly which
// credits 26AS supports and the CA would still retype the total into this box
// by hand, on a different tab, with no check that the two agreed.
//
// Narrow on purpose — the panel's copy will change with the design pass. What
// must not change: the claim is READ, an EMPTY field is prefilled and a TYPED
// one never overwritten, the variance is stated rather than resolved, and an
// absent 26AS says so instead of prefilling a zero.
//
// Run with: node --experimental-strip-types --test scripts/the-tds-credit-is-not-retyped.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(__dirname, "..", "app", "clients", "[id]", "tax", "computation", "page.tsx");
const code = stripComments(fs.readFileSync(PAGE, "utf8"));

test("the screen asks the server what 26AS supports", () => {
  assert.match(code, /\/api\/form-26as\/claimable\?client_id=/,
    "the CA is still retyping a figure the server can compute");
  // Scoped to the client AND the year — a claim off another year's statement
  // would prefill a plausible wrong number.
  assert.match(code, /financial_year=\$\{encodeURIComponent\(fy\)\}/);
});

test("an empty field is prefilled and a typed one is never overwritten", () => {
  const eff = code.slice(code.indexOf("/api/form-26as/claimable"));
  assert.match(eff, /setTds\(\(prev\) => \(prev\.trim\(\) === ""/,
    "the prefill must be conditional on the box being empty — silently " +
    "replacing a CA's own figure is worse than not helping at all");
  assert.match(eff, /setAdvanceTax\(\(prev\) => \(prev\.trim\(\) === ""/);
});

test("the four figures stay four, because the return has four lines", () => {
  // TDS is Schedule TDS; Part C is the client's own advance tax and its own
  // input. Folding them together would put advance tax on Schedule TDS.
  assert.match(code, /tds_claimable_paise/);
  assert.match(code, /tax_paid_by_client_paise/);
  assert.doesNotMatch(
    code,
    /tds_claimable_paise[^;\n]*\+[^;\n]*(tcs_claimable_paise|tax_paid_by_client_paise)/,
    "two of the four credit lines are being summed into one box",
  );
});

test("a variance against the 26AS figure is stated, not resolved", () => {
  assert.match(code, /tdsTouched/,
    "nothing distinguishes a prefilled figure from one the CA changed");
  assert.match(code, /143\(1\)/,
    "the consequence of over-claiming is what makes the variance worth reading");
});

test("no 26AS on file says so rather than prefilling a zero", () => {
  // Nobody having uploaded the statement and the client having no credit are
  // opposite facts. A prefilled 0 would quietly become a filed 0.
  assert.match(code, /!claim\.available/);
  assert.match(code, /\{claim\.reason\}/);
});

test("the caveats the server wrote reach the CA", () => {
  assert.match(code, /claim\.caveats \?\? \[\]\)\.map/,
    "the provisional-credit and TCS sentences are computed and dropped");
});
