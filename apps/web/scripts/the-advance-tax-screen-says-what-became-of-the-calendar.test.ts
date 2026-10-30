// The Advance Tax screen says what saving the register did to the compliance calendar (POST-A-267, the advance-tax half).
//
// WHAT THE SCREEN DID
//   Saving the register stored the payments and said "Saved". The four advance-tax obligations on the compliance calendar were
//   left as they were, so a client whose four instalments were paid and recorded read Overdue on Deadlines, the Compliance tab
//   and the dashboard. The server now closes the instalments the register shows paid and answers, per instalment, what it left
//   open and why (`services/advance_tax_closes_obligation`). A screen that went back to saying only "Saved" would make that
//   care invisible: the person would not know an obligation was left open, or that one was closed on a date they should check.
//
// The backend half is `apps/api/tests/test_a_recorded_advance_tax_payment_closes_the_instalment_obligation_it_paid.py`. This is
// the other end.
//
// Run with: node --experimental-strip-types --test scripts/the-advance-tax-screen-says-what-became-of-the-calendar.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const PAGE = stripComments(fs.readFileSync(path.join(WEB, "app/income-tax/advance-tax/page.tsx"), "utf8"));
const DATA = stripComments(fs.readFileSync(path.join(WEB, "lib/data/income-tax.ts"), "utf8"));

test("the files are where this guard thinks they are", () => {
  assert.ok(PAGE.length > 15000, `the advance-tax page read as ${PAGE.length} chars`);
  assert.ok(DATA.includes("export async function saveAdvanceTaxPayments"), "lib/data/income-tax.ts lost the register save");
});

test("saving the register returns the instalments AND the calendar answer, and the type says so", () => {
  assert.ok(/saveAdvanceTaxPayments\(req: SaveAdvanceTaxRequest\): Promise<SaveAdvanceTaxResult>/.test(DATA),
    "the save no longer returns the object the server answers with");
  assert.ok(/return json\.data as SaveAdvanceTaxResult;/.test(DATA), "the save does not hand back the server's whole answer");
  assert.ok(/compliance_obligations:\s*AdvanceTaxObligationAnswer\[\]/.test(DATA), "the result does not carry the calendar answer");
  assert.ok(/installments:\s*AdvanceTaxRecord\[\]/.test(DATA), "the result does not carry the stored instalments");
  assert.ok(/needs_action\?: boolean;/.test(DATA), "an answer's needs_action is not typed");
});

test("the screen keeps the answer it was given and draws attention from the server's needs_action", () => {
  assert.ok(/setCalendarAnswers\(saved\.compliance_obligations \?\? null\)/.test(PAGE), "the answer to saving the register is dropped");
  assert.ok(/calendarAnswers\.some\(a => a\.needs_action\) \? "attention"/.test(PAGE), "the tone is not the server's needs_action");
  assert.ok(/<li key=\{`\$\{a\.instalment \?\? "all"\}-\$\{i\}`\}>\{a\.message\}<\/li>/.test(PAGE),
    "the server's sentence is not shown as written");
  // The screen does not read the server's state words to decide anything.
  assert.ok(!/a\.state\s*(===|!==)/.test(PAGE), "the screen reads the answer's state words instead of its needs_action");
});

test("an answer is announced from a live region that is always on the page, and nothing to say is nothing said", () => {
  assert.ok(/<div role="status" className="[^"]*">\s*\{calendarAnswers && calendarAnswers\.length > 0 && \(/.test(PAGE),
    "the answer is not put in an always-mounted live region, or an empty answer renders a panel");
});

test("an answer belongs to the client and year it was given for", () => {
  assert.ok(/useEffect\(\(\) => \{ setCalendarAnswers\(null\); \}, \[clientId, fy\]\);/.test(PAGE),
    "the answer is kept when the client or the year changes");
});
