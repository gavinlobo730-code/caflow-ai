// The four screens whose private money formatters floored the paise or wrote a negative as "₹-2" now write a figure through
// `lib/money/format`, and keep no formatter of their own (POST-A-347).
//   node --experimental-strip-types --test scripts/the-four-screens-write-money-through-the-one-module.test.ts
//
// WHAT WAS WRONG (found on 27-10-2026 by an independent read of the rupee-sentence sweep, which had only reached the API)
//   * `app/payroll/reports/page.tsx` `fmtPaise` split a paise value with Math.floor and `%`, so a negative net pay (statutory
//     deductions can exceed gross; the bank advice has a NEGATIVE_NET case for it) printed "₹-1,501.-50";
//   * `app/pipeline/page.tsx` `formatRupees` floored the paise, so a ₹15,000.50 estimated fee read ₹15,000, and
//     `paiseToDRupeeString` floored it again when the form was reopened, so saving the form wrote ₹15,000.00 over it: the paise
//     were lost from a stored figure the firm forecasts its pipeline on;
//   * `app/payroll/statutory/page.tsx` `fmtRs` and `app/executive-dashboard/page.tsx` `fmtRupees` printed "₹-2" for -150 paise.
//
// WHAT IS HELD
//   * (the rule) none of the four defines a function by any of the five old names, and none divides paise by 100 to build text:
//     each imports from `lib/money/format` (a display) or `lib/money/rupeeInput` (the text of an amount field);
//   * (the behaviour) the replacements say what the old ones got wrong: a negative reads "-₹1,501.50", the paise stay, a crore-lakh
//     tile carries its sign, and an amount field round-trips exactly through its text (₹15,000.50 reopens as 15000.50 and parses
//     back to 1500050 paise).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { formatCroreLakh, formatPaise } from "../lib/money/format.ts";
import { paiseFromRupeeInput, rupeeInputFromPaise } from "../lib/money/rupeeInput.ts";

const WEB = join(import.meta.dirname, "..");
const SCREENS = [
  "app/payroll/reports/page.tsx",
  "app/pipeline/page.tsx",
  "app/payroll/statutory/page.tsx",
  "app/executive-dashboard/page.tsx",
];
const OLD_NAMES = ["fmtPaise", "formatRupees", "fmtRs", "fmtRupees", "paiseToDRupeeString"];

/** The module's code with block and line comments blanked, so this file's prose and the screens' own explanations do not count. */
function code(rel: string): string {
  return readFileSync(join(WEB, rel), "utf8").replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");
}

for (const rel of SCREENS) {
  test(`${rel} keeps no private money formatter`, () => {
    const body = code(rel);
    for (const name of OLD_NAMES) {
      assert.doesNotMatch(
        body,
        new RegExp(`(?:function\\s+${name}\\b|(?:const|let)\\s+${name}\\s*=)`),
        `${rel} defines ${name} again; import from lib/money/format (a display) or lib/money/rupeeInput (an amount field)`,
      );
    }
    // A flooring or a remainder split of paise is the defect itself. A plain `(x / 100).toFixed(2)` is NOT forbidden here: it is
    // a CSV cell, which must carry neither the rupee sign nor a grouping comma (see a-money-figure-keeps-its-paise.test.ts).
    assert.doesNotMatch(body, /Math\.(?:floor|trunc)\(\s*[^)]*\/\s*100\s*\)|\b\w*[pP]aise\w*\s*%\s*100\b/, `${rel} splits paise into rupees and a remainder by hand`);
    assert.match(body, /lib\/money\/(format|rupeeInput)/, `${rel} no longer imports the money modules`);
  });
}

test("the guard is not vacuous: it sees each old spelling", () => {
  const old = "function fmtPaise(paise: number): string {\n  const rupees = Math.floor(paise / 100);\n}";
  assert.match(old, new RegExp("function\\s+fmtPaise\\b"));
  assert.match(old, /Math\.(?:floor|trunc)\(\s*[^)]*\/\s*100\s*\)/);
  assert.match("const p = paise % 100;", /\b\w*[pP]aise\w*\s*%\s*100\b/);
  assert.doesNotMatch("(r.basic_paise / 100).toFixed(2)", /Math\.(?:floor|trunc)\(\s*[^)]*\/\s*100\s*\)|\b\w*[pP]aise\w*\s*%\s*100\b/);
  assert.match("const fmtRs = (p: number) => p", new RegExp("(?:const|let)\\s+fmtRs\\s*="));
});

test("a negative net pay reads as a negative amount, not as '₹-1,501.-50'", () => {
  assert.equal(formatPaise(-150150), "-₹1,501.50");
  assert.equal(formatPaise(-1), "-₹0.01");
  assert.equal(formatPaise(150150), "₹1,501.50");
});

test("the pipeline keeps the paise on screen and through the form", () => {
  assert.equal(formatPaise(1500050), "₹15,000.50");
  assert.equal(rupeeInputFromPaise(1500050), "15000.50");
  assert.equal(paiseFromRupeeInput(rupeeInputFromPaise(1500050)), 1500050, "reopening and saving the form must not change the stored figure");
  assert.equal(paiseFromRupeeInput(rupeeInputFromPaise(1500000)), 1500000);
});

test("the dashboard's abbreviated tile carries its sign and Indian grouping", () => {
  assert.equal(formatCroreLakh(-150), "-₹1.50");
  assert.equal(formatCroreLakh(-5_00_00_000_00), "-₹5.00 Cr");
  assert.equal(formatCroreLakh(2_50_000_00), "₹2.50 L");
  assert.equal(formatCroreLakh(null), "—");
});
