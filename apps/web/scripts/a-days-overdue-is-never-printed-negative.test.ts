// A count of days LATE is never printed negative on the client sales screen.
// Run with:
//   node --experimental-strip-types --test scripts/a-days-overdue-is-never-printed-negative.test.ts
//
// WHAT WAS WRONG (PRE-A-010)
//     `collections_service.assess_invoice` returned `(today - due_date).days`
//     unclamped, so an open invoice due in twelve days came back -12, the
//     overdue sweep wrote that into `client_sales_invoices.days_overdue`
//     (NOT NULL DEFAULT 0, no CHECK), and this screen printed
//     `${days_overdue}d overdue` wherever the value was TRUTHY. -12 is truthy.
//     The server clamps at the writer now, but nothing rewrote the rows already
//     stored, so the screen also stops a stored negative at the READ.
//
// THE RULE (not a spelling of today's lines)
//   1. The row mapping that builds a SalesInvoice from the PostgREST select
//      coerces `days_overdue` through Math.max(..., 0).
//   2. Every place that PRINTS days_overdue (a template-literal or JSX
//      interpolation) sits behind a `> 0` test on the same value, so a
//      truthiness test (`days_overdue ? ... : ""`) cannot come back.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const SALES = path.join(WEB, "app/clients/[id]/sales/page.tsx");

function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .split("\n")
    .map((l) => l.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

/** Interpolations of days_overdue that are NOT preceded, within the same
 *  expression, by a `days_overdue ... > 0` test. */
function ungatedDaysOverdueInterpolations(code: string): string[] {
  const out: string[] = [];
  const re = /\$\{\s*[\w.?]*days_overdue\s*\}|\{\s*[\w.?]*days_overdue\s*\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(code)) !== null) {
    const before = code.slice(Math.max(0, m.index - 160), m.index);
    // The test must be on days_overdue itself and must be a > 0 comparison.
    if (!/days_overdue(?:\s*\?\?\s*0\))?\s*>\s*0/.test(before)) {
      out.push(code.slice(Math.max(0, m.index - 60), m.index + m[0].length));
    }
  }
  return out;
}

const code = withoutComments(fs.readFileSync(SALES, "utf8"));

test("a days-late count is never printed negative", async (t) => {
  await t.test("the row mapping clamps a stored days_overdue at zero", () => {
    assert.match(
      code,
      /days_overdue:\s*Math\.max\(\s*r\.days_overdue\s*\?\?\s*0\s*,\s*0\s*\)/,
      "the mapping from the PostgREST row must read days_overdue through Math.max(..., 0): " +
        "rows written before PRE-A-010 may hold a negative figure",
    );
  });

  await t.test("every printed days_overdue is behind a > 0 test", () => {
    const loose = ungatedDaysOverdueInterpolations(code);
    assert.deepEqual(loose, [], `days_overdue printed without a > 0 test:\n${loose.join("\n")}`);
  });

  await t.test("the scan finds the two print sites (so the rule is not vacuous)", () => {
    const printed = code.match(/\$\{\s*[\w.?]*days_overdue\s*\}|\{\s*[\w.?]*days_overdue\s*\}/g) ?? [];
    assert.ok(printed.length >= 2, `expected at least two print sites, found ${printed.length}`);
  });

  await t.test("negative control: a truthiness-gated print is caught", () => {
    const bad = "{invoice.days_overdue ? ` (${invoice.days_overdue}d overdue)` : \"\"}";
    assert.equal(ungatedDaysOverdueInterpolations(bad).length, 1);
    const good = "{(invoice.days_overdue ?? 0) > 0 ? ` (${invoice.days_overdue}d overdue)` : \"\"}";
    assert.equal(ungatedDaysOverdueInterpolations(good).length, 0);
  });
});
