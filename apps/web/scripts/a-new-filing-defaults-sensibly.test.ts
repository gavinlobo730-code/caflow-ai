// The New Filing modal on app/clients/[id]/tax/filing/page.tsx.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-new-filing-defaults-sensibly.test.ts
//
// TWO DEFAULTS FIXED:
//
// (1) `form` DEFAULTED TO "ITR-6" (the domestic-company form) FOR EVERY
//     CLIENT, whatever their entity type — a Proprietorship or Partnership
//     opening this modal saw the company's form pre-selected. The default
//     is now resolved from the client's own entity type via the SAME
//     GET /api/income-tax/assessee-kind call the sibling tax/computation
//     screen already makes — never a second entity-type mapping written
//     here (CLAUDE.md, "zero business logic in the frontend").
//
// (2) `fy` DEFAULTED TO FY_OPTIONS[0], the CURRENTLY RUNNING year —
//     `financialYearChoicesAround` sorts descending, so [0] is a year not
//     yet over and [1] is the one that just closed on 31 March, which is
//     the one a CA opening this screen to file a return is actually about
//     to file for.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/clients/[id]/tax/filing/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the default financial year is the one that just closed, not the one still running", () => {
  const src = code(PAGE);
  assert.match(src, /useState\(FY_OPTIONS\[1\] \?\? FY_OPTIONS\[0\]\)/,
    "fy must default to FY_OPTIONS[1] (the closed year), falling back to [0] only if the list is too short");
  // NEGATIVE CONTROL: the old default.
  assert.doesNotMatch(src, /useState\(FY_OPTIONS\[0\]\)/,
    "the currently-running year must no longer be the default");
});

test("the default ITR form is resolved from the client's own entity type via the server", () => {
  const src = code(PAGE);
  assert.match(src, /\/api\/income-tax\/assessee-kind\?entity_type=/,
    "the screen must ASK the server which assessee this client's entity type makes them, " +
    "the same endpoint the tax/computation screen already calls");
  assert.match(src, /useClientEntityType/, "and read the client's own entity type to ask it with");
  assert.match(src, /formDefaultApplied/,
    "a CA who has already picked a different form must never have it silently overwritten " +
    "once the server resolves late");
});
