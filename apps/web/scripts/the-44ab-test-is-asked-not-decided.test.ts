// The Tax Audit tracker asks the backend whether §44AB applies. It used to
// decide, and it decided wrongly.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-44ab-test-is-asked-not-decided.test.ts
//
// WHY THIS EXISTS (IT-11)
//     app/income-tax/tax-audit/page.tsx carried the two statutory thresholds
//     as constants and this badge under the turnover box:
//
//         turnover >= THRESHOLD_BUSINESS   -> "mandatory (business)"
//         turnover >= THRESHOLD_PROFESSION -> "mandatory (profession)"
//         otherwise                        -> "below threshold"
//
//     which reads the NATURE OF THE ACTIVITY off the AMOUNT. §44AB(a) reaches
//     a person carrying on business and §44AB(b) a person carrying on a
//     profession; which applies is a fact about the client. So a trader with
//     ₹60 lakh of turnover, whom clause (a) does not reach at all, was told an
//     audit was mandatory — and §271B is 0.5% of turnover, capped at
//     ₹1,50,000, on the obligation the badge got wrong.
//
//     It also never applied the proviso to §44AB(a): its own module comment
//     said "that cash-percentage test is not modeled here".
//
// WHAT THIS DOES NOT DO
//     It reads source, not behaviour. That the ENGINE is right is
//     apps/api/tests/test_whether_a_tax_audit_applies.py's job. What this pins
//     is that the browser asks it, and that the copy it replaced is gone.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = path.join(WEB, "app/income-tax/tax-audit/page.tsx");
const SRC = fs.readFileSync(PAGE, "utf8");

test("the browser copy of the §44AB thresholds is deleted", () => {
  for (const f of ["lib/income-tax/taxAuditThresholds.ts",
                   "lib/income-tax/taxAuditThresholds.test.ts"]) {
    assert.equal(fs.existsSync(path.join(WEB, f)), false,
      `${f} still exists — the thresholds live in apps/api/domain/income_tax/tax_audit.py`);
  }
});

test("nothing imports it any more", () => {
  const hits: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.(ts|tsx)$/.test(e.name) && fs.readFileSync(p, "utf8").includes("taxAuditThresholds")) {
        // lib/api/index.ts names the deleted file in a comment explaining
        // WHY it is deleted. A comment is not an import.
        const body = fs.readFileSync(p, "utf8");
        if (/^\s*import[^;]*taxAuditThresholds/m.test(body)) hits.push(path.relative(WEB, p));
      }
    }
  };
  walk(WEB);
  assert.deepEqual(hits, []);
});

/** The page with every comment stripped — what a CA actually reads.
 *
 *  The distinction is load-bearing. A comment naming the old ₹1 crore badge
 *  is the RECORD of the defect and must survive; a threshold RENDERED on the
 *  screen is a second copy of the registry that goes stale in April with
 *  nothing to catch it. Two of these assertions failed on the first pass and
 *  both were real: the amber notice restated both thresholds as fact for
 *  every client, and the proviso disclosure spelled out ₹10 crore, ₹1 crore
 *  and 5%. */
function rendered(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, " ")   // block comments, JSX {/* … */} included
    .replace(/^\s*\/\/.*$/gm, " ");        // line comments
}

test("no §44AB threshold figure is RENDERED in the page", () => {
  const ui = rendered(SRC);
  // 1_000_000_000 paise (₹1 crore), 500_000_000 (₹50 lakh), 10 crore — in any
  // spelling. The answer is served now; a figure reappearing here is a second
  // registry, which is what was just deleted.
  const digits = ui.replace(/_/g, "");
  for (const n of ["1000000000", "500000000", "100000000000"]) {
    assert.equal(digits.includes(n), false,
      `${n} appears in rendered markup — the figures belong to the engine`);
  }
  assert.equal(/\d+\s*crore|\d+\s*lakh/i.test(ui), false,
    "a threshold is spelled out in prose the CA reads");
  assert.equal(/within\s*5\s*%|5\s*per\s*cent/i.test(ui), false,
    "the proviso's percentage is spelled out; the served caveat states it");
});

test("the badge is the served answer, and the nature is an input", () => {
  assert.match(SRC, /api\.incomeTax\.taxAuditApplicability/,
    "the page must ask the endpoint");
  assert.match(SRC, /nature:\s*form\.nature/,
    "the nature must be sent as stated, never derived from the amount");
  // The select the CA answers with.
  assert.match(SRC, /value="business">Business — §44AB\(a\)/);
  assert.match(SRC, /value="profession">Profession — §44AB\(b\)/);
});

test("a refusal is shown rather than replaced by a guess", () => {
  // The old badge could not fail, so it always said something — which is how
  // it came to say something wrong.
  //
  // MISSED ON THE FIRST PASS. This asserted only that `applicabilityError`
  // and `setApplicability(null)` appear SOMEWHERE, and both do — in the
  // .catch() and in the early return for an empty box. So emptying the
  // `else` branch that handles `success: false` passed everything, which is
  // exactly the refusal that matters: the GST workspace pattern CLAUDE.md
  // records, where a declined request comes back as HTTP 200. Both halves
  // are pinned now — the server's OWN sentence is carried, and it is
  // rendered.
  assert.match(SRC, /setApplicabilityError\(r\.error/,
    "the server's own refusal must be carried, not replaced by a generic one");
  assert.match(rendered(SRC), /\{applicabilityError\}/,
    "the refusal must be rendered, not merely stored");
  assert.match(SRC, /setApplicability\(null\);\s*setApplicabilityError\(r\.error/,
    "a refused check must clear the answer AND say why, in the same branch");
});

test("the limbs §44AB(a) and (b) do not reach are always rendered", () => {
  // Including on a "not required" answer. §44AB is not exhausted by (a) and
  // (b), and an answer that reads as if it were is the one a CA relies on.
  assert.match(SRC, /limbs_not_tested/);
  const panel = SRC.slice(SRC.indexOf("{applicability && ("));
  assert.match(panel.slice(0, 3000), /Limbs not tested here/);
});

test("the proviso's three figures are asked for together", () => {
  // Both sides of the cash test, plus the payments denominator turnover
  // cannot supply. Sending two of the three applies the base figure, which
  // is what the engine does and why the boxes sit in one disclosure.
  //
  // MISSED ON THE FIRST PASS: this matched the bare identifier, which still
  // appears in the form-state type and in BLANK. Unbinding an input from its
  // state left the box on screen doing nothing, and the engine then applied
  // the base ₹1 crore figure with a caveat blaming the CA for not stating
  // what they had in fact typed. Each box is now pinned to BOTH halves — the
  // value it reads and the setter it writes.
  for (const f of ["cashReceiptsRs", "cashPaymentsRs", "totalPaymentsRs"]) {
    assert.match(SRC, new RegExp(`value=\\{form\\.${f}\\}`),
      `the ${f} input does not read its own state`);
    assert.match(SRC, new RegExp(`upd\\(\\{\\s*${f}:\\s*e\\.target\\.value\\s*\\}\\)`),
      `the ${f} input does not write its own state`);
    assert.match(SRC, new RegExp(`${f.replace("Rs", "")
      .replace(/([A-Z])/g, "_$1").toLowerCase()}_paise`),
      `${f} is never sent to the engine`);
  }
  assert.match(SRC, /proviso to §44AB\(a\)/,
    "the disclosure must name the proviso it is for");
});

test("the report and return dates come from the answer, not from the page", () => {
  assert.match(SRC, /applicability\.report_due_date/);
  assert.match(SRC, /applicability\.return_due_date/);
  // Explanation (ii) to §44AB is compliance_engine's arithmetic; a date
  // literal RENDERED here is the IT-12 defect returning. The comment that
  // records IT-12 quotes the old string and must survive.
  assert.equal(/30 November|30 September|31 October/.test(rendered(SRC)), false);
});
