// sweep-practice-hub-06: /practice ("Practice — Revenue Overview") repeated
// the same four KPI tiles (Total Receivable, Overdue, TDS Receivable,
// Collected (cash)) already shown on /practice/revenue, off the same
// api.billing.dashboard() call — two screens rendering one answer twice.
//
// The fix keeps Overview as the practice-setup / tax-identity home (its own
// job — see TaxIdentity in that file) and reduces the duplicated figures to
// one summary line with a link across to Revenue, which keeps its own full
// set of tiles and shortcuts unchanged.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-practice-overview-page-links-to-revenue-instead-of-duplicating-it.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripComments } from "./stripComments.ts";

const OVERVIEW_PAGE = "app/practice/page.tsx";
const REVENUE_PAGE = "app/practice/revenue/page.tsx";

// Comments are stripped before every check below — this file's own comment
// explaining the fix names the tiles it removed, and a plain substring
// search cannot tell that explanation from a live tile (see stripComments.ts).
function pageSource(path: string): string {
  return stripComments(readFileSync(path, "utf8"));
}

test("Overview no longer titles itself as the Revenue screen", () => {
  assert.doesNotMatch(
    pageSource(OVERVIEW_PAGE),
    /Revenue Overview/,
    `${OVERVIEW_PAGE} still headlines itself "Revenue Overview" — that is ` +
      "Revenue's own job (/practice/revenue)",
  );
});

test("Overview does not repeat Revenue's TDS Receivable / Collected (cash) tiles", () => {
  const src = pageSource(OVERVIEW_PAGE);
  for (const label of ["TDS Receivable", "Collected (cash)"]) {
    assert.ok(
      !src.includes(label),
      `${OVERVIEW_PAGE} still renders a "${label}" tile — that duplicates ` +
        `${REVENUE_PAGE}, which is where those figures belong`,
    );
  }
});

test("Overview links to Revenue instead of restating its figures", () => {
  assert.match(
    pageSource(OVERVIEW_PAGE),
    /href="\/practice\/revenue"/,
    `${OVERVIEW_PAGE} no longer links to /practice/revenue`,
  );
});

test("Revenue keeps its own full tile set and shortcuts unchanged", () => {
  const src = pageSource(REVENUE_PAGE);
  for (const label of [
    "Total Receivable", "Overdue", "TDS Receivable", "Collected (cash)", "Active Schedules",
  ]) {
    assert.ok(src.includes(label), `${REVENUE_PAGE} is missing its own "${label}" tile`);
  }
});
