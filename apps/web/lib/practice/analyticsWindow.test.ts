// The picked window reaches the server as the right two query values, and the picker lists the running year first
// (POST-A-427). Run with:
//   node --experimental-strip-types --test lib/practice/analyticsWindow.test.ts
//
// The module is pure and imports only a type, so this runs it as it is: a source scan cannot tell `analyticsWindowOf`
// returning the month for every year from `analyticsWindowOf` returning the year.
import { test } from "node:test";
import assert from "node:assert/strict";
import { ANALYTICS_FY_COUNT, analyticsWindowChoices, analyticsWindowOf } from "./analyticsWindow.ts";

test("the three running windows map to themselves", () => {
  for (const id of ["week", "month", "quarter"] as const) {
    assert.deepEqual(analyticsWindowOf(id), { period: id });
  }
});

test("a financial year maps to period=fy and its label, and nothing else carries a label", () => {
  assert.deepEqual(analyticsWindowOf("fy:2025-26"), { period: "fy", financialYear: "2025-26" });
  for (const id of ["week", "month", "quarter"]) assert.equal("financialYear" in analyticsWindowOf(id), false);
});

test("an id the picker did not offer is the month, never a guess at a year", () => {
  for (const id of ["", "year", "FY:2025-26", "decade"]) assert.deepEqual(analyticsWindowOf(id), { period: "month" });
});

test("the picker offers the three running windows and then the years it was given, newest first", () => {
  const choices = analyticsWindowChoices(["2026-27", "2025-26", "2024-25"]);
  assert.deepEqual(choices.map((c) => c.id), ["month", "quarter", "week", "fy:2026-27", "fy:2025-26", "fy:2024-25"]);
  assert.equal(choices[3].label, "This financial year (2026-27), to date");
  assert.equal(choices[4].label, "Financial year 2025-26");
  assert.equal(choices.length, 3 + ANALYTICS_FY_COUNT);
});

test("every id the picker offers maps to a window the server knows, and back to the label it shows", () => {
  for (const c of analyticsWindowChoices(["2026-27", "2025-26", "2024-25"])) {
    const w = analyticsWindowOf(c.id);
    assert.ok(["week", "month", "quarter", "fy"].includes(w.period), c.id);
    if (w.period === "fy") assert.ok(c.label.includes(w.financialYear as string), `${c.label} does not name ${w.financialYear}`);
  }
});
