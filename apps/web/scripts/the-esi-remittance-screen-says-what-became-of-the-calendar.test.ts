// Recording an ESI remittance says what became of the month's ESI deposit obligation on the compliance calendar (POST-A-267, the ESI half).
//
// WHAT THE SCREEN DID
//   Recording a remittance on the payroll handoff stored it and said "Recorded". The wage month's ESI obligation on the compliance
//   calendar was left as it was, so a month paid and recorded read Overdue on Deadlines, the Compliance tab and the dashboard. The
//   server now closes the obligation when the payment was on time and covered what payroll computed
//   (`services/esi_deposit_closes_obligation`) and answers in a sentence what it did or why it left the month open. A screen that
//   went back to saying only "Recorded" would hide that care: the person would not know a month was left open, or that one was
//   closed on a date they should check.
//
// The backend half is `apps/api/tests/test_a_paid_esi_remittance_on_time_and_in_full_closes_the_deposit_obligation_it_paid.py`.
// This is the other end: the browser shows the server's sentence as written and decides nothing about whether a month was paid.
//
// Run with: node --experimental-strip-types --test scripts/the-esi-remittance-screen-says-what-became-of-the-calendar.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const HANDOFF = stripComments(fs.readFileSync(path.join(WEB, "components/payroll/StatutoryHandoff.tsx"), "utf8"));
const API = stripComments(fs.readFileSync(path.join(WEB, "lib/api/index.ts"), "utf8"));

test("the files are where this guard thinks they are", () => {
  assert.ok(HANDOFF.length > 8000, `the handoff read as ${HANDOFF.length} chars`);
  assert.ok(API.includes("recordRemittance: (clientId: string"), "lib/api lost the remittance call");
});

test("recording a remittance is typed to carry the calendar answer", () => {
  const call = API.slice(API.indexOf("recordRemittance: (clientId: string"));
  const typed = call.slice(0, call.indexOf("`/api/payroll/clients/${clientId}/remittances`"));
  assert.ok(/compliance_obligations\?: \{ message: string; needs_action\?: boolean;/.test(typed),
    "the remittance call does not type the calendar answer the server sends");
});

test("the screen shows the server's sentences as written and reads none of its state words", () => {
  assert.ok(/calendarNote = \(res\.data\?\.compliance_obligations \?\? \[\]\)\.map\(\(a\) => a\.message\)\.join\(" "\)/.test(HANDOFF),
    "the sentences the server answers are not collected as written");
  assert.ok(/\(calendarNote \? ` \$\{calendarNote\}` : ""\)/.test(HANDOFF), "the sentences are not added to what the person is told");
  assert.ok(!/\.state\s*(===|!==)/.test(HANDOFF), "the screen reads the answer's state words instead of showing its sentence");
  assert.ok(!/needs_action/.test(HANDOFF), "the screen draws its own conclusion from needs_action; it only shows the sentence");
});

test("the screen holds no rule for when a month is paid: no amount is compared and no due date is computed in the handoff's record step", () => {
  const record = HANDOFF.slice(HANDOFF.indexOf("async function submit()"), HANDOFF.indexOf("return (\n    <div className=\"mt-3 rounded-xl"));
  assert.ok(record.length > 500, "the record step could not be found");
  assert.ok(!/owed|esi_deposit|dueDate|due_date/.test(record), "the record step decides something about what was due");
});
