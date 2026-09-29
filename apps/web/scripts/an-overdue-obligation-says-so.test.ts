// lib/data/compliance.ts's toEntry() derives whether a compliance record is
// overdue, rather than trusting a status column the backend never writes.
//
// Run with:
//   node --experimental-strip-types --test scripts/an-overdue-obligation-says-so.test.ts
//
// WHAT WAS WRONG
//     STATUS_TO_FILING_STATUS maps "Overdue" -> "overdue", but nothing in
//     apps/api ever writes `status = "Overdue"` on a compliance_calendar row
//     — services/compliance_record_service.py's escalate() records
//     escalation-tier bookkeeping only and VALID_TRANSITIONS has no
//     automatic path there. So a genuinely overdue obligation (due_date in
//     the past, status still "Not Started") mapped to "pending" for ever,
//     disagreeing with the due-date text these same screens separately
//     colour red by comparing against today.
//
// THE FIX
//     `filing_status` is now derived once, in toEntry(): a non-terminal
//     status whose due_date is in the past (compared against the SAME
//     browser-local "today" the due-date colouring already uses) reads as
//     "overdue" regardless of what the stored status column says.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const FILE = "lib/data/compliance.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("toEntry derives overdue from the due date, not only the stored status", () => {
  const src = code(FILE);
  assert.match(src, /TERMINAL_FILING_STATUSES/,
    "a filed record must never be reported overdue no matter its due date");
  assert.match(src, /isOverdue\s*=\s*!TERMINAL_FILING_STATUSES\.has\(mapped\)\s*&&\s*!!raw\.due_date\s*&&\s*raw\.due_date\s*<\s*todayLocalISO\(\)/,
    "overdue must be computed from due_date < today, not read off the status column alone");
  assert.match(src, /filing_status:\s*isOverdue\s*\?\s*"overdue"\s*:\s*mapped/,
    "the derived flag must actually override the mapped status");
});

test("uses the same local-today the due-date colouring elsewhere on this product already uses", () => {
  const src = code(FILE);
  assert.match(src, /import \{ todayLocalISO \} from "@\/lib\/dateMath"/,
    "the existing helper must be reused rather than a second 'today' computed here");
});
