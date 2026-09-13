// Rule 37's reversal states the §50 interest running on it.
//
// Run with:
//   node --experimental-strip-types --test scripts/rule-37-says-what-the-delay-costs.test.ts
//
// GST-28, the half that is buildable. CGST Rule 37(1) with the second proviso
// to §16(2) requires credit on a bill 180 days unpaid to be paid back "along
// with interest payable thereon under section 50". The GSTR-3B screen's Rule
// 37 panel stated the tax and stopped, so a CA saw the reversal and not the
// charge that had been running since.
//
// THE OTHER HALF IS DELIBERATELY NOT BUILT. The finding asks for a "Post this
// reversal" action that creates the journal and registers it in one step.
// services/itc_register_service.py records the opposite choice in its own
// docstring, with the reason: a journal crediting GST Input could be a Rule 37
// reversal, a Rule 42 apportionment or a §17(5) block, only the CA knows
// which, and a one-click poster would also have to choose the debit account.
// That is an owner decision to re-take, not a defect to fix.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
/** Source with comments stripped — what actually runs and renders. */
const code = (src: string) =>
  src.replace(/\{\/\*[\s\S]*?\*\/\}/g, " ")
     .replace(/\/\*[\s\S]*?\*\//g, " ")
     .replace(/^\s*\/\/.*$/gm, " ");

const GSTR3B = code(fs.readFileSync(path.join(WEB, "app/gst/gstr3b/page.tsx"), "utf8"));
const DATA = code(fs.readFileSync(path.join(WEB, "lib/data/gst.ts"), "utf8"));

test("the report's type carries both readings of the clock", () => {
  assert.match(DATA, /interest: \{ from_availment: Rule37Interest; from_expiry: Rule37Interest \}/);
  assert.match(DATA, /interest_totals: \{ from_availment_paise: number; from_expiry_paise: number \}/);
  assert.match(DATA, /interest_caveats: string\[\]/);
});



test("the Rule 37 panel states the §50 interest on what it reverses", () => {
  assert.match(GSTR3B, /Interest under §50\(1\) on that reversal/);
  assert.match(GSTR3B, /dueInterest\.availment/);
  assert.match(GSTR3B, /dueInterest\.expiry/);
});

test("the interest is summed over THIS return's bills, not every overdue one", () => {
  // Rule 37(1) puts each reversal in one specific return. An earlier bill's
  // interest belongs to a return already filed, and folding it in here would
  // charge this period for somebody else's lateness.
  assert.match(GSTR3B, /const dueInterest = due\.reduce/);
  assert.doesNotMatch(GSTR3B, /overdueEarlier\.reduce\(\(t, b\) => \(\{/);
});

test("neither clock is presented as the answer", () => {
  assert.match(GSTR3B, /From the date the credit was availed/);
  assert.match(GSTR3B, /From the day the 180 days expired/);
  assert.match(GSTR3B, /rule37!\.interest_caveats\.map/);
});

test("no 'post this reversal' button appeared with it", () => {
  // The finding asks for one; itc_register_service refuses it on purpose,
  // because a journal crediting GST Input could be Rule 37, Rule 42 or
  // §17(5), and the debit account is the judgement.
  assert.doesNotMatch(GSTR3B, /Post this reversal/i);
});
