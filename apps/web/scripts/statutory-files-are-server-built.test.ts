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

test("a government upload never gets a byte the server did not write", () => {
  // downloadFile prepends a BOM so Excel reads OUR csv exports properly. Both
  // of these files go to a PORTAL, not to Excel — and the ECR is a fixed-format
  // text upload where an extra byte breaks parsing.
  //
  // The rule used to be INFERRED from the mime type: csv got a BOM, text did
  // not. That was right only while every CSV on this page was ours. The moment
  // the server-built ESIC return was routed through the same helper it would
  // have been handed a byte apps/api never wrote, into a statutory filing.
  const s = payroll();
  assert.match(s, /\{ bom: false \}/,
    "the statutory download must opt out of the BOM explicitly");
  assert.match(s, /opts\?\.bom \?\? mimeType\.startsWith\("text\/csv"\)/,
    "the caller decides, because the caller is the one who knows where the file is going");
});

test("the two unfilable cases are told apart", () => {
  // is_filable is `bool(members) and not problems` on BOTH builders
  // (domain/payroll/ecr.py:111, esic.py:71). So a filable return NEVER carries
  // problems — a "downloaded, but N members had problems" path is unreachable —
  // and filable:false with an EMPTY problems list is its own real state,
  // meaning no member carried a contribution at all.
  const s = payroll();
  assert.match(s, /title: problems\.length \? `\$\{label\} blocked` : `Nothing to file`/,
    "no members and blocked members are different answers and need different words");
  assert.doesNotMatch(s, /Downloaded, with \$\{problems\.length\}/,
    "a filable return cannot carry problems; that branch was unreachable");
});

// ── EDLI and the EPF admin charge come from the RUN, not from the slips ──────
//
// Migration 329. Both are employer costs outside the 12%, and the admin charge
// carries a statutory MINIMUM of ₹500 per ESTABLISHMENT per month — so what is
// owed is a property of the run and cannot be reconstructed by adding up
// payslips. Three members at ₹60 each owe ₹500, not ₹180.
//
// Summing slips would under-state it for every small client, and the card would
// then disagree with both the EPFO challan and the ledger entry.

test("the statutory card reports the whole EPFO challan, not just the 12%", () => {
  // WHAT THIS USED TO ASSERT, AND WHY IT MOVED.
  //
  // The firm rail had a Statutory tab that summed EDLI and the admin charge in
  // the BROWSER, off the run rows, and this test pinned it to the run rather
  // than to the slips — because the admin charge is floored at Rs 500 per
  // ESTABLISHMENT, so three members at Rs 60 each owe Rs 500 and summing slips
  // under-states it.
  //
  // That tab is gone. It was a rival of the client month, which is where a
  // payroll month is actually completed, and the figure is no longer computed
  // in a browser at all: GET /api/payroll/reports/statutory-summary returns
  // pf_challan_total_paise, edli_paise and pf_admin_paise straight off the run
  // row, and apps/api's test_the_summary_reports_the_whole_challan owns the
  // arithmetic.
  //
  // What has to be true HERE is that the card SHOWS the challan rather than the
  // contributions, and names the two parts a CA reconciles against.
  const page = fs.readFileSync(
    path.join(ROOT, "app/clients/[id]/payroll/page.tsx"), "utf8");
  assert.match(page, /amount: data\.pf_challan_total_paise \?\? data\.pf_total_paise/,
    "the card must show the CHALLAN, not the 12% either side");
  assert.match(page, /EDLI \$\{fmt\(data\.edli_paise \?\? 0\)\}/,
    "EDLI must be named, so the total can be taken apart again");
  assert.match(page, /Admin \$\{fmt\(data\.pf_admin_paise \?\? 0\)\}/,
    "and so must the administrative charge");
});

test("no screen sums EDLI or the admin charge out of payslips", () => {
  // The floored charge is a property of the RUN. Summing slips under-states it,
  // silently, by up to the floor. This is the inverted half of the test above:
  // whatever screens exist, none of them may compute it.
  for (const rel of ["app/payroll/page.tsx",
                     "app/payroll/people/page.tsx",
                     "app/clients/[id]/payroll/page.tsx"]) {
    const src = fs.readFileSync(path.join(ROOT, rel), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
    assert.doesNotMatch(src, /sum\(s => s\.pf_admin_paise/, `${rel} must not sum the admin charge`);
    assert.doesNotMatch(src, /sum\(s => s\.edli_paise/, `${rel} must not sum EDLI`);
  }
});
