// The assessment year is not the financial year. Run with:
//   node --experimental-strip-types --test lib/income-tax/assessmentYear.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  assessmentYearChoices,
  assessmentYearForFy,
  financialYearForAy,
  isYearLabel,
} from "./assessmentYear.ts";

test("a year label is not a shape", () => {
  assert.equal(isYearLabel("2025-26"), true);
  assert.equal(isYearLabel("2099-00"), true);
  // ^\d{4}-\d{2}$ passes this, and then it means 2026-27.
  assert.equal(isYearLabel("2026-28"), false);
  assert.equal(isYearLabel("2026-99"), false);
  assert.equal(isYearLabel("2026"), false);
  assert.equal(isYearLabel(""), false);
});

test("the assessment year is one ahead of the financial year", () => {
  // IT Act s.2(9) with s.3: FY 2025-26 is assessed in AY 2026-27.
  assert.equal(assessmentYearForFy("2025-26"), "2026-27");
  assert.equal(financialYearForAy("2026-27"), "2025-26");
});

test("the conversion holds across a century boundary", () => {
  assert.equal(assessmentYearForFy("2099-00"), "2100-01");
  assert.equal(financialYearForAy("2100-01"), "2099-00");
});

test("a label that is not a label gets nothing, not a wrong year", () => {
  assert.equal(assessmentYearForFy("2026-28"), "");
  assert.equal(financialYearForAy("garbage"), "");
});

test("after 1 April, the year being filed is second in the list", () => {
  // 10 Sep 2026: FY 2025-26 has ended, so AY 2026-27 is the return being
  // prepared. AY 2027-28 is offered first only because advance tax for the
  // year in progress is a real thing to look at.
  assert.deepEqual(assessmentYearChoices(3, new Date(2026, 8, 10)),
                   ["2027-28", "2026-27", "2025-26"]);
});

test("before 1 April, the year in progress has not ended", () => {
  // 15 Feb 2026 is still inside FY 2025-26, so the last SETTLED year is
  // FY 2024-25 = AY 2025-26.
  assert.deepEqual(assessmentYearChoices(3, new Date(2026, 1, 15)),
                   ["2026-27", "2025-26", "2024-25"]);
});
