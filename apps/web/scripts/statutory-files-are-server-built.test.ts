// Statutory files are built by the SERVER, never in the browser. Run with:
//   node --experimental-strip-types --test scripts/statutory-files-are-server-built.test.ts
//
// WHY THIS EXISTS
//     Until 2026-09-04 the EPFO ECR and the ESIC return a CA downloaded were
//     computed HERE, in app/payroll/page.tsx, and the browser's rules were the
//     ones the backend had already fixed:
//
//       * NCP_DAYS was the literal 0 in every row, so every employee's
//         loss-of-pay days were remitted to EPFO as none;
//       * MEMBER_ID carried the employee's PAN, or a fabricated "EMP0001"
//         where there was no PAN — the field is the UAN, so this put an
//         invented member id in a statutory remittance file;
//       * EPF wages were basic ALONE, where EPF Act s.6 says basic + DA;
//       * ESI eligibility was `gross_paise <= 2100000` for the current month,
//         ignoring the Rule 50 contribution period that keeps a member in
//         past the ceiling until the period ends;
//       * ESI contributions were computed in floating point.
//
//     GET /runs/{id}/ecr and /runs/{id}/esic already existed, were correct,
//     and had NO caller in the web app. CLAUDE.md's "zero business logic in
//     the frontend" is not a style rule here: it is what stops a second
//     implementation of a statutory split drifting from the one that posts to
//     the ledger. This file is what stops the browser version coming back,
//     because "just generate it client-side, it's only a text file" is a
//     change nobody would flag in review.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAYROLL = path.join(ROOT, "app/payroll/page.tsx");
const API = path.join(ROOT, "lib/api/index.ts");

const api = () => fs.readFileSync(API, "utf8");

/** The page WITH ITS COMMENTS STRIPPED.
 *
 *  Every "must not contain" assertion below is about CODE. The note left where
 *  the browser generators used to be names the very things they got wrong —
 *  NCP_DAYS, the 0.75% rate — and a test that read comments would fail on the
 *  documentation of its own fix, which is the opposite of what it is for. */
function payrollCode(): string {
  return fs.readFileSync(PAYROLL, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}
const payroll = () => fs.readFileSync(PAYROLL, "utf8");

test("the browser does not build the EPFO ECR", () => {
  const s = payrollCode();
  assert.doesNotMatch(s, /function\s+generatePfEcr/,
    "the browser ECR generator must not come back");
  // The header line is the giveaway: only something building the file itself
  // needs to name EPFO's columns.
  assert.doesNotMatch(s, /MEMBER_ID~MEMBER_NAME~GROSS_WAGES/,
    "the ECR's tilde-separated header belongs to the server, not to a page");
  assert.doesNotMatch(s, /NCP_DAYS/,
    "NCP days are loss-of-pay days; the browser hardcoded them to 0");
});

test("the browser does not build the ESIC return", () => {
  const s = payrollCode();
  assert.doesNotMatch(s, /function\s+generateEsiStatement/,
    "the browser ESIC generator must not come back");
  // 0.75% and 3.25% are the ESI contribution rates. A page that names them is
  // computing a statutory deduction — domain/payroll/esic.py owns that, and it
  // reads the STORED split rather than recomputing it.
  assert.doesNotMatch(s, /Employee Contribution \(0\.75%\)/,
    "ESI rates in the browser are a second implementation of a statutory split");
  assert.doesNotMatch(s, /gross_paise <= 2100000/,
    "ESI eligibility is a Rule 50 contribution-period question, not a monthly gross test");
});

test("both files come from the server, through the API client", () => {
  const a = api();
  assert.match(a, /runEcr:\s*\(runId: string\) =>\s*request\(`\/api\/payroll\/runs\/\$\{runId\}\/ecr`\)/,
    "the ECR must be fetched from its endpoint");
  assert.match(a, /runEsic:\s*\(runId: string\) =>\s*request\(`\/api\/payroll\/runs\/\$\{runId\}\/esic`\)/,
    "the ESIC return must be fetched from its endpoint");

  const s = payroll();
  assert.match(s, /api\.payroll\.runEcr\(run\.id\)/, "the page must call the ECR endpoint");
  assert.match(s, /api\.payroll\.runEsic\(run\.id\)/, "the page must call the ESIC endpoint");
});

test("the server's refusal reaches the CA instead of a broken file", () => {
  const s = payroll();
  // `filable` is the server's own verdict. Downloading a file it called
  // unfilable would hand the CA something the portal rejects, with no clue why.
  assert.match(s, /if \(!d\.filable\)/,
    "an unfilable return must not be downloaded as though it were fine");
  assert.match(s, /problems/,
    "the members the file cannot carry must be shown; they are fixed before the upload");
  // A run that is not finalised is a 409 from the server, because both returns
  // report contributions actually made. Say so on the button.
  assert.match(s, /const isFiled = \(run: PayrollRun\) => run\.status === "finalized" \|\| run\.status === "paid"/,
    "a draft run cannot produce a statutory return");
  assert.match(s, /disabled=\{pfCount === 0 \|\| !isFiled\(run\)/,
    "the ECR button must be gated on the run being finalised");
  assert.match(s, /disabled=\{esiCount === 0 \|\| !isFiled\(run\)/,
    "the ESIC button must be gated on the run being finalised");
});
