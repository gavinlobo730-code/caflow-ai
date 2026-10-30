// The compliance calendar page saves the server's iCalendar file and builds none (POST-A-142, the export half).
//
// WHAT WAS MISSING
//   A CA who wanted client deadlines in Outlook, Google Calendar or a phone retyped them: nothing in the product made a VCALENDAR.
//   The file is built by the server (`GET /api/compliance/obligations/calendar.ics`, `domain/practice/ical.py`) from the same rows,
//   window and assignment scope as the screen's own read, so the browser holds no calendar format, no escaping and no due date.
//
// THE RULES HELD HERE, from the browser's side:
//   * the page offers the download and sends only the client chosen (the window, what is included and the format are the server's);
//   * the api method asks the .ics route and saves the answer, naming the file `compliance-calendar.ics`;
//   * nothing in apps/web writes a VCALENDAR: a second implementation of the format is how the screen and the file would disagree;
//   * a refusal is said in words and never swallowed.
//
// The backend half is `apps/api/tests/test_the_compliance_calendar_can_be_downloaded_as_an_ical_file.py`.
//
// Run with: node --experimental-strip-types --test scripts/the-calendar-saves-the-servers-ical-file.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const PAGE = stripComments(fs.readFileSync(path.join(WEB, "app/calendar/page.tsx"), "utf8"));
const API = stripComments(fs.readFileSync(path.join(WEB, "lib/api/index.ts"), "utf8"));

function* sources(dir: string): Generator<string> {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (["node_modules", ".next", "out", ".smoke"].includes(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* sources(full);
    else if (/\.(ts|tsx)$/.test(entry.name) && !entry.name.endsWith(".test.ts")) yield full;
  }
}

test("the files are where this guard thinks they are", () => {
  assert.ok(PAGE.length > 5000, `the calendar page read as ${PAGE.length} chars`);
  assert.ok(API.includes("complianceOps: {"), "lib/api lost the compliance namespace");
});

test("the api method asks the .ics route and saves what it answers", () => {
  assert.ok(/exportCalendar: \(params\?: \{[^}]*client_id\?: string;[^}]*\}\) => \{/.test(API), "exportCalendar is missing or lost its parameters");
  assert.ok(API.includes("downloadFile(`/api/compliance/obligations/calendar.ics"), "exportCalendar does not save the server's file");
  assert.ok(API.includes('"compliance-calendar.ics"'), "the saved file is not named compliance-calendar.ics");
});

test("the page offers the download, sends only the client chosen, and says a refusal in words", () => {
  assert.ok(/api\.complianceOps\.exportCalendar\(clientId \? \{ client_id: clientId \} : undefined\)/.test(PAGE),
    "the page sends more than the client chosen, or does not call the export");
  assert.ok(PAGE.includes("Download .ics"), "the page does not offer the download");
  assert.ok(PAGE.includes("Could not download the calendar file"), "a refusal is not said");
  assert.ok(/disabled=\{downloading\}/.test(PAGE), "a second click while the file is being prepared is not ignored");
});

test("nothing in the browser builds a calendar file", () => {
  const offenders = [...sources(WEB)].filter(f => /BEGIN:VCALENDAR|BEGIN:VEVENT/.test(fs.readFileSync(f, "utf8")));
  assert.deepEqual(offenders.map(f => path.relative(WEB, f)), [], "a VCALENDAR is written in the browser");
});
