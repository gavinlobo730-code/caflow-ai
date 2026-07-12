// Period-picker date-range math. Run with:
//   node --experimental-strip-types --test lib/dates/periods.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { fyRangeFor, shiftFY, resolvePeriodRange, periodOptionLabel } from "./periods.ts";

const FY = "2026-27";
const TODAY = "2026-07-12"; // a Sunday

test("fyRangeFor: April 1 to March 31", () => {
  assert.deepEqual(fyRangeFor("2026-27"), { start: "2026-04-01", end: "2027-03-31" });
});

test("shiftFY: forward and backward", () => {
  assert.equal(shiftFY("2026-27", -1), "2025-26");
  assert.equal(shiftFY("2026-27", 1), "2027-28");
});

test("today", () => {
  assert.deepEqual(resolvePeriodRange("today", FY, { from: "", to: "" }, TODAY), { start: TODAY, end: TODAY });
});

test("yesterday", () => {
  assert.deepEqual(resolvePeriodRange("yesterday", FY, { from: "", to: "" }, TODAY), { start: "2026-07-11", end: "2026-07-11" });
});

test("this_week spans Monday to Sunday, including when today IS Sunday", () => {
  assert.deepEqual(resolvePeriodRange("this_week", FY, { from: "", to: "" }, TODAY), { start: "2026-07-06", end: "2026-07-12" });
});

test("this_week from a midweek Wednesday", () => {
  assert.deepEqual(resolvePeriodRange("this_week", FY, { from: "", to: "" }, "2026-07-15"), { start: "2026-07-13", end: "2026-07-19" });
});

test("last_3_months: first of (this month - 2) through today", () => {
  assert.deepEqual(resolvePeriodRange("last_3_months", FY, { from: "", to: "" }, TODAY), { start: "2026-05-01", end: TODAY });
});

test("last_3_months rolls back across a calendar-year boundary", () => {
  assert.deepEqual(resolvePeriodRange("last_3_months", FY, { from: "", to: "" }, "2026-01-15"), { start: "2025-11-01", end: "2026-01-15" });
});

test("this_fy uses the page's financial year", () => {
  assert.deepEqual(resolvePeriodRange("this_fy", FY, { from: "", to: "" }, TODAY), { start: "2026-04-01", end: "2027-03-31" });
});

test("last_fy shifts the financial year back one", () => {
  assert.deepEqual(resolvePeriodRange("last_fy", FY, { from: "", to: "" }, TODAY), { start: "2025-04-01", end: "2026-03-31" });
});

test("custom: both dates given", () => {
  assert.deepEqual(resolvePeriodRange("custom", FY, { from: "2026-06-01", to: "2026-06-30" }, TODAY), { start: "2026-06-01", end: "2026-06-30" });
});

test("custom: open-ended from/to fall back to a wide bound", () => {
  assert.deepEqual(resolvePeriodRange("custom", FY, { from: "2026-06-01", to: "" }, TODAY), { start: "2026-06-01", end: "2999-12-31" });
  assert.deepEqual(resolvePeriodRange("custom", FY, { from: "", to: "2026-06-30" }, TODAY), { start: "1900-01-01", end: "2026-06-30" });
});

test("periodOptionLabel resolves FY-dependent labels", () => {
  assert.equal(periodOptionLabel("this_fy", FY), "This Financial Year (FY 2026-27)");
  assert.equal(periodOptionLabel("last_fy", FY), "Last Financial Year (FY 2025-26)");
  assert.equal(periodOptionLabel("today", FY), "Today");
});
