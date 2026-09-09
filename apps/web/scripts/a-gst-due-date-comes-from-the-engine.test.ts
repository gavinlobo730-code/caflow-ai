// The browser never computes a GST due date. CLAUDE.md says it twice —
// "services/compliance_engine.py is the single source for every due date" and
// "Zero business logic in the frontend" — and this makes it testable for the
// one screen where a copy actually existed.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-gst-due-date-comes-from-the-engine.test.ts
//
// WHY THIS EXISTS
//     app/gst/page.tsx had its own getDueDate(). It was right for GSTR-1 and
//     GSTR-3B and WRONG for GSTR-9: it read the CALENDAR year off the period
//     and added one, but a financial year runs April to March. February 2026
//     falls in FY 2025-26 and its annual return is due 31-12-2026; the screen
//     said 31-12-2027. April through December agreed with the engine, so nine
//     months out of twelve looked correct — which is how a second copy of a
//     statutory rule survives.
//
//     GET /api/compliance/due-dates/calculate had existed the whole time, and
//     api.compliance.calculateDueDates was already in lib/api with no caller.
//     Exactly the shape Phase 3 deleted for TDS: the engine was right, and
//     nothing on the screen was asking it.
//
// WHAT THIS DOES NOT DO
//     It reads source, not behaviour. That the ENGINE is right is the Python
//     suite's job (tests/test_compliance_engine.py). What this pins is that the
//     browser asks it.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const GST_PAGE = "app/gst/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/\/\/.*$/gm, "");
}

test("the GST filing tracker asks the engine for its due dates", () => {
  assert.match(code(GST_PAGE), /api\.compliance\.calculateDueDates\s*\(/,
    `${GST_PAGE} must fetch due dates from ` +
    "GET /api/compliance/due-dates/calculate, not compute them.");
});

test("and does not build one itself", () => {
  const src = code(GST_PAGE);
  // 31 December, in any of the spellings a hand-rolled GSTR-9 date takes.
  assert.doesNotMatch(src, /-12-31|12-31`|"12"\s*,\s*"31"/,
    "a 31 December literal is a GSTR-9 due date being computed here. " +
    "CGST Act s.44 lives in services/compliance_engine.py.");
  // The 11th / 20th of the following month, s.37 and s.39.
  assert.doesNotMatch(src, /returnType\s*===\s*["']GSTR-1["']\s*\?\s*11\s*:\s*20/,
    "s.37 and s.39 due days are the engine's, not this screen's.");
});

test("the due date is left EMPTY when the engine cannot be reached", () => {
  // The alternative — falling back to a browser-computed guess — is how the
  // copy gets re-introduced, and a wrong date is indistinguishable from a right
  // one in a date box. The field is editable, so empty plus a message is the
  // honest state.
  const src = code(GST_PAGE);
  assert.match(src, /setDueDate\(""\)/,
    "on a failed lookup the field must be cleared, not filled with a guess.");
  assert.match(src, /dueDateErr/,
    "and the CA must be told the lookup failed rather than shown a blank box.");
});

test("lib/api still exposes the method the page depends on", () => {
  const api = code("lib/api/index.ts");
  assert.match(api, /calculateDueDates\s*:/);
  assert.match(api, /\/api\/compliance\/due-dates\/calculate/);
});
