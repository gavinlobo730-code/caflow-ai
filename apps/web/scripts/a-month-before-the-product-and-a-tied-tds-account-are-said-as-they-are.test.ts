// Two things the server knows and the screens used to say wrongly. Run with:
//   node --experimental-strip-types --test scripts/a-month-before-the-product-and-a-tied-tds-account-are-said-as-they-are.test.ts
//
// 1. A MONTH BEFORE THE PRODUCT RAN A CLIENT'S PAYROLL IS NOT A PAID NIL (POST-A-082).
//    The §192 projection marks every month before an employee's opening position's first month `opening`, with no figure of
//    its own (null): its pay and tax are the position's, in total. Both screens that draw the projection read only `actual`,
//    so those months showed as "Paid" / "Processed" with ₹0 against them, and the staff screen's Cumulative TDS left the
//    opening tax out while the card above it put it in, so every Remaining Tax cell was overstated by it.
//
// 2. TWO ACCOUNTS THAT COULD EACH BE THE SALARY TDS ACCOUNT ARE NOT "NONE WAS FOUND" (POST-A-083).
//    The 24Q tie-out refuses to choose between two and says so in `account_note`, naming both. Both TDS screens printed
//    "the control account was not found" whenever `account_found` was false, so the sentence naming the two never reached a CA.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.join(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");

test("the projection's type says a month may be an opening month with no figure of its own", () => {
  const api = read("lib/api/index.ts");
  const block = api.slice(api.indexOf("export interface PayrollTdsProjection"));
  const shape = block.slice(0, block.indexOf("\n}") + 2);
  assert.match(shape, /opening\?: boolean; gross_paise: number \| null; tds_paise: number \| null/);
  assert.match(shape, /opening_position\?: \{ first_month_here: string; months_paid: number; gross_paise: number; tds_paise: number \} \| null/);
});

test("the employee's own projection names an opening month and draws its figures as a dash", () => {
  const tab = read("components/portal/TdsProjectionTab.tsx");
  assert.match(tab, /\{m\.opening \? \(/, "the opening month is decided before `actual`, which it also carries");
  assert.ok(tab.indexOf("m.opening ?") < tab.indexOf("m.actual ?"), "asked first, or it reads as Paid");
  assert.match(tab, /const monthFigure = \(paise: number \| null \| undefined\) => \(paise == null \? "—" : formatPaise\(paise\)\)/);
  assert.doesNotMatch(tab, /formatPaise\(m\.(gross|tds)_paise\)/, "a month's figure goes through monthFigure, so null is a dash");
  assert.match(tab, /data\.opening_position &&/, "the position's totals are shown once");
});

test("the staff projection starts its running total at the opening tax and adds no opening month on top", () => {
  const page = read("app/payroll/reports/page.tsx");
  assert.match(page, /let running = proj\?\.opening_position\?\.tds_paise \?\? 0;/,
    "Cumulative TDS and Remaining Tax must agree with TDS Deducted So Far, which includes the opening tax");
  assert.match(page, /if \(m\.actual && !opening\) running \+= m\.tds_paise \?\? 0;/);
  assert.match(page, /hasActual: m\.actual && !opening,/, "an opening month is not a processed one");
  assert.match(page, /\{r\.opening \? \(\s*<span[^>]*>\s*Before this product \(opening position\)/);
  assert.match(page, /\{r\.opening \? "—" : formatPaise\(r\.projectedTds\)\}/);
});

test("both TDS screens say the server's sentence when the tie-out could not choose an account", () => {
  assert.match(read("lib/data/tds.ts"), /account_note\?: string \| null;/);
  assert.match(read("app/tds/returns/page.tsx"),
    /\? \(result\.reconciliation\.account_note \|\| "the TDS Payable control account was not found"\)/);
  assert.match(read("app/clients/[id]/compliance/tds/page.tsx"),
    /\? \(typeof rec\?\.account_note === "string" && rec\.account_note\s*\? `⚠ \$\{rec\.account_note\} Reconciliation skipped\.`/);
});
