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

/** `value="2025-26"` on an <option>, which is the shape that goes stale. */
const FY_OPTION = /<option\s[^>]*value=["'](\d{4}-\d{2})["']/g;

test("no control offers a hardcoded financial year", () => {
  const offenders: string[] = [];
  for (const root of ROOTS) {
    for (const path of pages(root)) {
      const src = readFileSync(path, "utf8");
      for (const m of src.matchAll(FY_OPTION)) {
        const year = Number(m[1].slice(0, 4));
        // A four-digit-dash-two-digit value that is not a plausible financial
        // year — a version, a code — is not this defect.
        if (year < 2000 || year > 2100) continue;
        const line = src.slice(0, m.index).split("\n").length;
        offenders.push(`${path}:${line}  value="${m[1]}"`);
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

test("the two screens this was found on build their list from the helper", () => {
  // The instances, pinned separately from the rule. The rule above would pass
  // if somebody deleted the dropdown entirely; these say the control still
  // exists and is derived.
  for (const path of ["app/tds/returns/page.tsx", "app/accounting/budget/page.tsx"]) {
    const src = readFileSync(path, "utf8");
    assert.ok(src.includes(HELPER),
      `${path} no longer builds its financial-year list from ${HELPER}().`);
  }
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
