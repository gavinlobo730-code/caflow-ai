// The tax computation screen asks WHO is being assessed. Run with:
//   node --experimental-strip-types --test scripts/a-company-is-not-taxed-on-individual-slabs.test.ts
//
// WHY THIS EXISTS
//     apps/api's entity_rates.py and minimum_tax.py were complete and tested
//     and imported by nothing. POST /api/income-tax/compute ran INDIVIDUAL
//     slabs for every client, so a Private Limited company's profit was taxed
//     nil to Rs 4 lakh, 5% to Rs 8 lakh, with a Rs 60,000 s.87A rebate — where
//     a company pays 22%/25%/30% from the first rupee and gets no rebate.
//     Measured on Rs 50,00,000 for FY 2025-26: Rs 11,23,200 shown against
//     Rs 15,60,000 owed.
//
//     The engine fix is not enough on its own. This screen has to SEND the
//     client's entity type and OFFER the right questions — a s.115BAC new/old
//     election is an individual's, a company's is s.115BAA/s.115BAB, and a
//     firm has none. A correct engine behind a form that asks the wrong
//     questions is a correct engine nobody reaches.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/clients/[id]/tax/computation/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the computation sends the client's entity type", () => {
  const src = code(PAGE);
  assert.match(src, /entity_type: entityType/,
    "the endpoint cannot know which assessee it is computing unless the screen says");
  assert.match(src, /from\("clients"\)\s*\.select\("entity_type"\)/,
    "and the screen has to read it off the client record");
});

test("the entity type is mapped by the server, never on this screen", () => {
  // CLAUDE.md: zero business logic in the frontend. That a PROPRIETORSHIP is
  // an individual, and that a trust is refused, is statutory knowledge.
  const src = code(PAGE);
  assert.match(src, /\/api\/income-tax\/assessee-kind/,
    "the screen must ASK which assessee this is");
  assert.doesNotMatch(src, /"Private Limited"|'Private Limited'/,
    "the mapping from entity type to assessee must not be written here");
  assert.doesNotMatch(src, /Proprietorship/,
    "nor the proprietorship special case, which is the one that is easy to get wrong");
});

test("a company is offered its own regime election, not the individual's", () => {
  const src = code(PAGE);
  assert.match(src, /115BAA/, "s.115BAA is a company's election");
  assert.match(src, /115BAB/);
  assert.match(src, /isCompany \?/,
    "and it replaces the new/old dropdown rather than sitting beside it");
});

test("the s.115JB / s.115JC inputs exist and say what they are", () => {
  const src = code(PAGE);
  assert.match(src, /115JB/, "book profit drives MAT");
  assert.match(src, /115JC/, "adjusted total income drives AMT");
  assert.match(src, /claimedSpecifiedDeduction/,
    "s.115JC applies only where a s.10AA / s.35AD / VI-A Part C deduction was CLAIMED");
  assert.match(src, /credit_paise/,
    "the CREDIT is the point — s.115JAA and s.115JD carry the excess for fifteen years");
});

test("a refused assessee is shown before the CA types a figure", () => {
  const src = code(PAGE);
  assert.match(src, /assesseeRefusal/,
    "a trust or a co-operative society is refused, and the reason names the sections");
  assert.match(src, /assesseeRefusal !== null/,
    "and Compute is not offered while it stands — a dead control is worse than none");
});

test("a refused INPUT does not render as a zero tax", () => {
  const src = code(PAGE);
  assert.match(src, /validation_errors/,
    "the engine returns the reasons with every figure at zero; showing the zero " +
    "beside them would be worse than showing nothing");
});

test("the snapshot records the regime the server applied", () => {
  const src = code(PAGE);
  assert.match(src, /regime: \(computeRes\.data\?\.regime as string\)/,
    "sending the local new/old dropdown stamped a s.115BAC election on a " +
    "company snapshot that could not have made one");
  assert.match(src, /function regimeLabel/,
    'and `regime === "new" ? "New" : "Old"` labelled every entity "Old Regime"');
  assert.doesNotMatch(src, /regime === "new" \? "New/,
    "the two-way label must be gone, not just wrapped");
});
