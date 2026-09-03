// The gaps the server names must reach a CA. Run with:
//   node --experimental-strip-types --test scripts/payroll-gaps-reach-the-screen.test.ts
//
// WHY THIS EXISTS
//     create_run has ALWAYS returned statutory_gaps — the deductions it
//     refused to guess at, one sentence per employee — and this page threw
//     them away. `createRun` cast the response to `{success, error}` and never
//     read `res.data`, so a named gap existed only in a response body nobody
//     rendered. The payroll gap matrix found it in ZERO .tsx files.
//
//     A named gap that reaches nobody is an omitted statutory deduction with
//     extra steps. The whole refuse-rather-than-guess discipline in apps/api
//     is worth nothing if the refusal is silent by the time it reaches a CA.
//
//     attendance_gaps (migration 324) joins it: the employees for whom nobody
//     entered anything, who were paid a full month on the 26-day default.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const PAGE = path.join(import.meta.dirname, "..", "app/clients/[id]/payroll/page.tsx");
const page = () => fs.readFileSync(PAGE, "utf8");

test("the run's response is read, not discarded", () => {
  const s = page();
  assert.match(s, /data\?: \{ statutory_gaps\?: string\[\]; attendance_gaps\?: string\[\] \}/,
    "createRun must type the data it now reads");
  assert.match(s, /setRunGaps\(\[\.\.\.\(res\.data\?\.attendance_gaps \?\? \[\]\), \.\.\.\(res\.data\?\.statutory_gaps \?\? \[\]\)\]\)/,
    "both lists must be captured; attendance first, because it is the one that changes pay");
});

test("the gaps are rendered", () => {
  const s = page();
  assert.match(s, /runGaps\.length > 0 &&/, "the block must be conditional on there being gaps");
  assert.match(s, /runGaps\.map\(/, "every sentence must be shown, not a count");
  assert.match(s, /could not be established/, "and framed as what the run could not establish");
});

test("the sentences are the server's, not the browser's", () => {
  // CLAUDE.md: zero business logic in the frontend. The page must not compose
  // a gap of its own — deciding what counts as missing is a statutory
  // judgement that lives in apps/api, next to the rules it is judging against.
  const s = page();
  assert.doesNotMatch(s, /no attendance entered for this month/,
    "the sentence belongs to routers/payroll.py::_attendance_gap");
  assert.doesNotMatch(s, /26-day default/,
    "the browser must not restate the rule it is reporting");
});

test("a draft run is not presented as a failure", () => {
  // The gaps WARN; they do not block. A run is a draft — nothing posted,
  // nothing paid — so the copy must not read like a rejection, or a CA will
  // think the run did not happen.
  const s = page();
  assert.match(s, /The run is a draft — nothing is posted or paid/,
    "the CA must be told the run exists and what state it is in");
});
