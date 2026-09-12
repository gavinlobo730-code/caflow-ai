// A financial-year dropdown is derived from the clock, never listed.
// Run with:
//   node --experimental-strip-types --test scripts/a-financial-year-choice-comes-from-the-clock.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT (TDS-18)
// ─────────────────────────────────────────────────────────────────────────────
// app/tds/returns/page.tsx seeded its state from `currentFinancialYear()` and
// offered three HARDCODED options ending at 2025-26. On 1 April 2026 those
// stopped agreeing: the state was "2026-27", the `<select>` had no such option
// so it rendered BLANK, the API returned the 2025-Act form number "140" for
// that year, and the save hit `tds_returns.return_type IN ('24Q','26Q','27Q',
// '27EQ')` — a CHECK violation the CA read as "Failed to save TDS return".
//
// Three things make this worth a guard rather than a fix:
//
//   1. It is the screen's OWN DEFAULT that the list cannot express, so it is
//      broken for every user on day one of the year, not in an edge case.
//   2. It breaks on a DATE, so no test that does not move the clock will ever
//      see it, and CI is green the day before.
//   3. Sweeping for the pattern found a SECOND one immediately —
//      app/accounting/budget/page.tsx listed two years and defaulted to the
//      first — which is what makes this a class and not an instance.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE, AND WHY IT IS SHAPED THIS WAY
// ─────────────────────────────────────────────────────────────────────────────
// Not "these two files must import the helper" — that names the instances and
// a third file added next month escapes it. The rule is about the LITERAL:
// nothing in a page or component may write a financial-year label as an
// `<option value=…>`. `lib/dates/periods.financialYearChoicesAround` derives
// them from the clock and is the one way to build the list.
//
// A financial-year literal elsewhere — a test fixture, a comment, a default in
// a data module — is not what this is about and is not matched: the failure is
// specifically a CONTROL offering a fixed set of years while something else
// decides the current one.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOTS = ["app", "components"];
const HELPER = "financialYearChoicesAround";
const AY_HELPER = "assessmentYearChoicesAround";

/** Every .tsx under the roots. */
function pages(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      if (entry === "node_modules" || entry === ".next") continue;
      pages(path, out);
    } else if (entry.endsWith(".tsx")) {
      out.push(path);
    }
  }
  return out;
}

/** `value="2025-26"` on an <option>, which is ONE shape that goes stale. */
const FY_OPTION = /<option\s[^>]*value=["'](\d{4}-\d{2})["']/g;

/** …and the one it missed: an ARRAY of year labels, which is how twelve more
 *  pages spelled the same defect.
 *
 *  THE RULE WAS WRITTEN AS A SPELLING AND SO IT CAUGHT ONE SPELLING. This file
 *  said "the rule is about the LITERAL" and then matched only
 *  `<option value="2025-26">`. Sweeping for the array form on 12 September
 *  2026 found TWELVE more — ten financial-year lists and two assessment-year
 *  ones — of which EIGHT ended at 2025-26, a year already past. So on the
 *  year-end screens, the XBRL screen, the tax-audit screen, the §32 screen,
 *  the Tally migration screen, the documents screen and the 26AS
 *  reconciliation, the current year simply could not be selected. Exactly the
 *  defect this guard was written for, in a spelling it did not know.
 *
 *  The same lesson as the money-parser guard in CLAUDE.md, which was re-made
 *  three times before it stopped naming spellings: state the rule, and if the
 *  rule cannot be stated, state EVERY spelling and expect to add more. */
const FY_ARRAY = /\[\s*"(\d{4}-\d{2})"(?:\s*,\s*"\d{4}-\d{2}")+\s*,?\s*\]/g;

test("no control offers a hardcoded financial year", () => {
  const offenders: string[] = [];
  for (const root of ROOTS) {
    for (const path of pages(root)) {
      // COMMENTS STRIPPED FIRST, because several of these files now EXPLAIN
      // the literal they removed by quoting it — and prose about a literal is
      // not the literal. The same trap `_strip_comments` exists for in
      // apps/api/tests/test_direct_write_tables_are_role_guarded.py.
      const src = readFileSync(path, "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/^\s*\/\/.*$/gm, "");
      for (const pattern of [FY_OPTION, FY_ARRAY]) {
        for (const m of src.matchAll(pattern)) {
          const year = Number(m[1].slice(0, 4));
          // A four-digit-dash-two-digit value that is not a plausible
          // financial year — a version, a code — is not this defect.
          if (year < 2000 || year > 2100) continue;
          const line = src.slice(0, m.index).split("\n").length;
          offenders.push(`${path}:${line}  ${m[0].slice(0, 60)}`);
        }
      }
    }
  }
  assert.deepEqual(offenders, [],
    "A financial year is written out as an <option> value here. It goes stale "
    + "on 1 April and the page's own default will not be in the list — which "
    + "is exactly how the TDS returns screen came to POST a year its dropdown "
    + `could not show. Build the list with ${HELPER}() from lib/dates/periods `
    + "instead:\n  " + offenders.join("\n  "));
});

test("every screen this was found on builds its list from a helper", () => {
  // The instances, pinned separately from the rule. The rule above would pass
  // if somebody deleted the dropdown entirely; these say the control still
  // exists and is derived. Twelve were added on 12 September 2026 when the
  // rule was widened to the array spelling and found them.
  const FY_SCREENS = [
    "app/tds/returns/page.tsx", "app/accounting/budget/page.tsx",
    "app/clients/[id]/tax/26as/page.tsx", "app/clients/[id]/tax/filing/page.tsx",
    "app/clients/[id]/year-end/page.tsx", "app/clients/[id]/year-end/xbrl/page.tsx",
    "app/migration/page.tsx", "app/tds/page.tsx", "app/income-tax/page.tsx",
    "app/income-tax/advance-tax/page.tsx", "app/income-tax/tax-audit/page.tsx",
    "app/income-tax/section-32/page.tsx", "app/documents/page.tsx",
  ];
  for (const path of FY_SCREENS) {
    const src = readFileSync(path, "utf8");
    assert.ok(src.includes(HELPER),
      `${path} no longer builds its financial-year list from ${HELPER}().`);
  }
  // An ASSESSMENT year is the financial year plus one (IT Act §2(9) with §3),
  // so it goes stale identically and is derived from the same place.
  for (const path of ["app/clients/[id]/tax/computation/page.tsx",
                      "app/clients/[id]/tax/filing/page.tsx",
                      "app/income-tax/notices/page.tsx"]) {
    const src = readFileSync(path, "utf8");
    assert.ok(src.includes(AY_HELPER),
      `${path} no longer builds its assessment-year list from ${AY_HELPER}().`);
  }
});

test("the assessment-year helper is derived from the financial-year one", () => {
  // Not a second parser. Two functions that each work out "the current year"
  // are two controls that can describe different periods, which is the bug
  // class this module exists to end.
  const src = readFileSync("lib/dates/periods.ts", "utf8");
  const fn = src.slice(src.indexOf(`export function ${AY_HELPER}`));
  const body = fn.slice(0, fn.indexOf("\n}"));
  assert.ok(body.includes(HELPER),
    `${AY_HELPER} does not derive from ${HELPER}().`);
  assert.ok(!/\d{4}-\d{2}/.test(body),
    `${AY_HELPER} contains a hardcoded year.`);
});

test("the helper actually derives from the clock", () => {
  // The control on the rule: if financialYearChoicesAround were itself a fixed
  // list, every assertion above would be satisfied by something just as stale.
  const src = readFileSync("lib/dates/periods.ts", "utf8");
  const fn = src.slice(src.indexOf(`export function ${HELPER}`));
  const body = fn.slice(0, fn.indexOf("\n}"));
  assert.ok(/today/.test(body),
    `${HELPER} does not read a date — it cannot be the answer to a list that `
    + "goes stale.");
  assert.ok(!/\d{4}-\d{2}/.test(body),
    `${HELPER} contains a hardcoded financial year.`);
});
