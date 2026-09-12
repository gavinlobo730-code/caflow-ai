// IT-05 and IT-16 — the client tax computation screen sends every input the
// endpoint accepts. Run with:
//   node --experimental-strip-types --test scripts/the-computation-screen-sends-what-the-engine-accepts.test.ts
//
// WHY THIS EXISTS
//     `ComputeITRRequest` has accepted HRA, §80G, both halves of §80CCD,
//     residence and a presumptive figure since the engine was built. The
//     screen sent none of them, so an old-regime salaried client paying rent
//     had §10(13A) omitted entirely — the largest single relief on that form —
//     a non-resident individual was silently granted a basic-exemption
//     absorption the provisos to §111A(1)/§112(1)(a)(ii)/§112A(2) do not
//     reach, and a §44AD client's deemed income had to be worked out somewhere
//     else and typed in as business income.
//
//     This is the defect class the audit kept finding: the engine is right and
//     no screen reaches it. A field the request model accepts and the form
//     omits produces a confident, well-formatted, wrong number.
//
// THE RULE, NOT THE SPELLING
//     Every amount the form collects must be in the pre-compute validation
//     list, because toP() casts the parser's answer `as number` — a field
//     outside that list reaches the server as null the moment somebody types
//     an Indian-grouped amount.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = fs.readFileSync(
  path.join(ROOT, "app/clients/[id]/tax/computation/page.tsx"), "utf8");

/** The compute call's own body, so a field named only in a comment or in the
 *  snapshot save cannot make this pass. */
function computeBody(): string {
  const from = PAGE.indexOf('apiFetch("/api/income-tax/compute"');
  assert.ok(from > 0, "the compute call moved — this guard has to follow it");
  const to = PAGE.indexOf("if (!computeRes.success)", from);
  assert.ok(to > from);
  return PAGE.slice(from, to);
}

test("every field the endpoint accepts is in the payload", () => {
  const body = computeBody();
  for (const field of [
    "is_resident",                    // IT-08's residual: the CG absorption gate
    "hra:",                           // §10(13A) with Rule 2A
    "nps_80ccd1b_paise",              // the assessee's own NPS
    "employer_nps_80ccd2_paise",      // and the employer's — allowed on BOTH regimes
    "is_government_employee",
    "salary_for_80ccd2_paise",
    "donations_80g",                  // §80G
    "presumptive_income_paise",       // IT-16
  ]) {
    assert.match(body, new RegExp(field.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
      `${field} is accepted by ComputeITRRequest and the form does not send it`);
  }
});

test("every amount the form collects is validated before anything is computed", () => {
  const from = PAGE.indexOf("const fields: [string, string][]");
  const to = PAGE.indexOf("const bad = fields.find", from);
  assert.ok(from > 0 && to > from);
  const list = PAGE.slice(from, to);
  for (const state of ["hraBasic", "hraReceived", "hraRent",
                       "nps80ccd1b", "employerNps", "nps80ccd2Salary"]) {
    assert.match(list, new RegExp(`\\b${state}\\b`),
      `${state} is a typed amount and must be parsed-checked with the rest — ` +
      "toP() turns a refusal into NaN and JSON.stringify sends that as null");
  }
  assert.match(list, /donations\.map/,
    "a donation amount is typed too, and there can be several");
});

test("the presumptive figure is the server's answer, never a typed one", () => {
  const body = computeBody();
  assert.match(body, /presResult\?\.eligible/,
    "an ineligible scheme must not feed the computation");
  assert.doesNotMatch(body, /presumptive_income_paise:\s*toP\(/,
    "§44AD/§44ADA/§44AE deem the income from the turnover — a box a CA types " +
    "into is a second implementation of domain/income_tax/presumptive.py");
});

test("the presumptive request names the assessee the section decides on", () => {
  const from = PAGE.indexOf("async function handlePresumptive");
  const to = PAGE.indexOf("async function handleCompute", from);
  assert.ok(from > 0 && to > from);
  const fn = PAGE.slice(from, to);
  assert.match(fn, /assessee_kind:\s*assesseeKind/,
    "§44AD's Explanation (a) and §44ADA(1) name who they reach, and the " +
    "server decides it — the screen states the fact, it does not hold the list");
  assert.match(fn, /is_resident:\s*isResident/);
});

test("no eligible-assessee list lives in this screen", () => {
  // The moment one does, it is a second copy of §44AD's Explanation (a) and
  // will drift from domain/income_tax/presumptive.ELIGIBLE_PRESUMPTIVE_ASSESSEES.
  const code = PAGE.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.doesNotMatch(code, /44ad[\s\S]{0,80}(assesseeKind|isEntity)\s*[=!]==/i,
    "eligibility for a presumptive scheme is the server's answer");
});
