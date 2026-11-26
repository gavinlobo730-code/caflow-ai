// POST-A-267 — the wage months a salary challan may name: the quarter's three, of its own financial year.
//
// Run with:
//   node --experimental-strip-types --test lib/tds/salaryChallanMonth.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { wageMonthsOfQuarter } from "./salaryChallanMonth.ts";

test("each quarter offers its three months", () => {
  assert.deepEqual(wageMonthsOfQuarter("2025-26", "Q1").map((c) => c.value), ["2025-04", "2025-05", "2025-06"]);
  assert.deepEqual(wageMonthsOfQuarter("2025-26", "Q2").map((c) => c.value), ["2025-07", "2025-08", "2025-09"]);
  assert.deepEqual(wageMonthsOfQuarter("2025-26", "Q3").map((c) => c.value), ["2025-10", "2025-11", "2025-12"]);
});

test("the fourth quarter is January to March of the year the financial year ends in", () => {
  assert.deepEqual(wageMonthsOfQuarter("2025-26", "Q4"), [
    { value: "2026-01", label: "Jan 2026" }, { value: "2026-02", label: "Feb 2026" }, { value: "2026-03", label: "Mar 2026" },
  ]);
  assert.equal(wageMonthsOfQuarter("2025-2026", "Q4")[2].value, "2026-03");
});

test("a year or quarter that is not one offers nothing", () => {
  assert.deepEqual(wageMonthsOfQuarter("", "Q1"), []);
  assert.deepEqual(wageMonthsOfQuarter("FY25", "Q1"), []);
  assert.deepEqual(wageMonthsOfQuarter("2025-26", "Q5"), []);
});
