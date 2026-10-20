// POST-A-267 — the MCA screens report what the server said about the compliance obligation when a filing was recorded as
// filed and it was not closed by the same click.
//
// Run with:
//   node --experimental-strip-types --test scripts/an-mca-filing-recorded-filed-says-whether-its-obligation-closed.test.ts
//
// WHAT WAS WRONG
//     Recording an AOC-4 or MGT-7 as filed left its obligation on the compliance calendar Not Started and overdue, and
//     nothing said so. The server closes the obligation now (`compliance_obligation` in the answer); where it did not (no
//     obligation on the calendar, no filing date, another company still to file, no Compliance access, a failure) every
//     screen that records a filing as filed must say so, from the server's own sentence, and decide nothing itself.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const CLIENT_TAB = path.join("app", "clients", "[id]", "compliance", "mca", "page.tsx");
const FIRM_PAGE = path.join("app", "mca", "page.tsx");

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the client's filings tab reads the answer through the one helper, shows it and lets the CA dismiss it", () => {
  const src = code(CLIENT_TAB);
  assert.match(src, /import \{ obligationNote \} from "@\/lib\/compliance\/obligationNote"/);
  assert.match(src, /setCalendarNote\(obligationNote\(res\.data\)\)/, "the server's sentence about the calendar is thrown away");
  assert.match(src, /\{calendarNote && \(/, "the note is never shown");
  assert.match(src, /setCalendarNote\(null\)/, "the note cannot be dismissed");
});

test("every call that records a filing as filed on the firm-level page reads the answer through the helper", () => {
  const src = code(FIRM_PAGE);
  assert.match(src, /import \{ obligationNote \} from "@\/lib\/compliance\/obligationNote"/);
  const calls = src.match(/api\.mca\.setFilingStatus\(/g) ?? [];
  assert.equal(calls.length, 3, "the page records a filing as filed in three places: add, mark one, mark a batch");
  assert.equal((src.match(/calendarSentence\(obligationNote\(res\.data\)\)/g) ?? []).length, 2, "the add and the single mark each say what the calendar did");
  assert.match(src, /note: obligationNote\(res\.data\)/, "the batch drops the note of each filing");
  assert.match(src, /\$\{r\.label\}: \$\{r\.note\}/, "the batch's notes do not say which filing each is about");
});

test("the sentence rides the success message and is never a toast of its own, because the toaster holds only one", () => {
  const toaster = fs.readFileSync(path.join(WEB, "components", "ui", "use-toast.ts"), "utf8");
  assert.match(toaster, /const TOAST_LIMIT = 1;/, "the toaster's limit changed: re-read this rule");
  const src = code(FIRM_PAGE);
  assert.doesNotMatch(src, /calendarToast|toast\(calendar\)/, "the sentence is raised as a toast that the next toast replaces");
  assert.match(src, /toast\(\{ title: "MCA filing added", description: calendar \}\)/, "the add flow's success toast does not carry the sentence");
  assert.match(src, /as filed`, description: calendar \}\)/, "the batch's success toast does not carry the sentence");
});

test("the page decides nothing about the state, and says it in the same words as the client tab's note", () => {
  const firm = code(FIRM_PAGE);
  const client = code(CLIENT_TAB);
  assert.match(firm, /const CALENDAR_NOT_MARKED = "The compliance calendar was not marked filed\.";/);
  assert.match(client, /title="Recorded as filed\. The compliance calendar was not marked filed\."/);
  for (const [rel, src] of [[CLIENT_TAB, client], [FIRM_PAGE, firm]] as const) {
    assert.doesNotMatch(src, /compliance_obligation/, `${rel} reads the block directly instead of through lib/compliance/obligationNote`);
  }
});
