// The picked window reaches the server as the right two query values, and the picker lists the running year first
// (POST-A-427). Run with:
//   node --experimental-strip-types --test lib/practice/analyticsWindow.test.ts
//
// The module is pure and imports only a type, so this runs it as it is: a source scan cannot tell `analyticsWindowOf`
// returning the month for every year from `analyticsWindowOf` returning the year.
import { test } from "node:test";
import assert from "node:assert/strict";
import { ANALYTICS_FY_COUNT, CUSTOM_WINDOW_ID, analyticsWindowChoices, analyticsWindowOf, customWindowProblem } from "./analyticsWindow.ts";

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

test("the picker offers the three running windows, then the years it was given newest first, then a range of days", () => {
  const choices = analyticsWindowChoices(["2026-27", "2025-26", "2024-25"]);
  assert.deepEqual(choices.map((c) => c.id), ["month", "quarter", "week", "fy:2026-27", "fy:2025-26", "fy:2024-25", "custom"]);
  assert.equal(choices[3].label, "This financial year (2026-27), to date");
  assert.equal(choices[4].label, "Financial year 2025-26");
  assert.equal(choices[6].label, "A range of days…");
  assert.equal(choices.length, 3 + ANALYTICS_FY_COUNT + 1);
  assert.equal(CUSTOM_WINDOW_ID, "custom");
});

test("every id the picker offers maps to a window the server knows, and back to the label it shows", () => {
  const days = { from: "2026-04-01", to: "2026-09-30" };
  for (const c of analyticsWindowChoices(["2026-27", "2025-26", "2024-25"])) {
    const w = analyticsWindowOf(c.id, days);
    assert.ok(["week", "month", "quarter", "fy", "custom"].includes(w.period), c.id);
    if (w.period === "fy") assert.ok(c.label.includes(w.financialYear as string), `${c.label} does not name ${w.financialYear}`);
  }
});

test("a range of days maps to period=custom and its two days, and only the custom window carries them", () => {
  assert.deepEqual(analyticsWindowOf("custom", { from: "2026-04-01", to: "2026-09-30" }), { period: "custom", dateFrom: "2026-04-01", dateTo: "2026-09-30" });
  for (const id of ["week", "month", "quarter", "fy:2025-26"]) {
    const w = analyticsWindowOf(id, { from: "2026-04-01", to: "2026-09-30" });
    assert.equal("dateFrom" in w, false, `${id} carries a day`);
    assert.equal("dateTo" in w, false, `${id} carries a day`);
  }
});

test("a range of days that was not given two readable days is the month, never a guess at a day", () => {
  assert.deepEqual(analyticsWindowOf("custom"), { period: "month" });
  for (const days of [{ from: "", to: "" }, { from: "2026-04-01", to: "" }, { from: "", to: "2026-09-30" }, { from: "01/04/2026", to: "30/09/2026" }, { from: "2026-4-1", to: "2026-09-30" }]) {
    assert.deepEqual(analyticsWindowOf("custom", days), { period: "month" }, JSON.stringify(days));
  }
});

test("a custom window says what stops it, in the words the screen shows, and is null when the two days can be asked for", () => {
  const today = "2026-11-13";
  assert.match(customWindowProblem("", "", today) ?? "", /^Choose the first and the last day/);
  assert.equal(customWindowProblem("", "2026-09-30", today), "Choose the first day of the window.");
  assert.equal(customWindowProblem("2026-04-01", "", today), "Choose the last day of the window.");
  assert.match(customWindowProblem("2026-09-30", "2026-04-01", today) ?? "", /^The To day is before the From day/);
  assert.match(customWindowProblem("2026-04-01", "2026-11-14", today) ?? "", /^The To day is after today in India/);
  assert.equal(customWindowProblem("2026-04-01", "2026-09-30", today), null);
  assert.equal(customWindowProblem("2026-11-13", "2026-11-13", today), null, "a window of one day, today, can be asked for");
  assert.equal(customWindowProblem("2026-11-10", "2026-11-10", today), null, "a window of one past day can be asked for");
  assert.equal(customWindowProblem("2020-04-01", "2026-11-13", today), null, "a window may span years");
  // A text that is not an ISO day is no day, the way `analyticsWindowOf` reads it: the two cannot disagree about whether a window can be asked for.
  assert.equal(customWindowProblem("01/04/2026", "2026-09-30", today), "Choose the first day of the window.");
  assert.equal(customWindowProblem("2026-04-01", "30/09/2026", today), "Choose the last day of the window.");
  assert.match(customWindowProblem("2026-4-1", "soon", today) ?? "", /^Choose the first and the last day/);
});
