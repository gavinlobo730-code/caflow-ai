// Period-picker date-range math. Run with:
//   node --experimental-strip-types --test lib/dates/periods.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { fyRangeFor, shiftFY, resolvePeriodRange, periodOptionLabel, splitPeriodColumns, formatRangeLabel } from "./periods.ts";

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

// ── formatRangeLabel ─────────────────────────────────────────────────────

test("formatRangeLabel: a single day shows once, a range shows both ends", () => {
  assert.equal(formatRangeLabel("2026-07-12", "2026-07-12"), "12 Jul 2026");
  assert.equal(formatRangeLabel("2026-04-01", "2027-03-31"), "1 Apr 2026 – 31 Mar 2027");
});

// ── splitPeriodColumns ───────────────────────────────────────────────────

test("granularity 'total' always returns exactly one column", () => {
  const cols = splitPeriodColumns("this_fy", FY, { from: "", to: "" }, "total", TODAY);
  assert.equal(cols.length, 1);
  assert.deepEqual(cols[0], { label: "FY 2026-27", start: "2026-04-01", end: "2027-03-31" });
});

test("monthly split of a full FY yields 12 calendar-month columns", () => {
  const cols = splitPeriodColumns("this_fy", FY, { from: "", to: "" }, "month", TODAY);
  assert.equal(cols.length, 12);
  assert.deepEqual(cols[0], { label: "Apr 2026", start: "2026-04-01", end: "2026-04-30" });
  assert.deepEqual(cols[11], { label: "Mar 2027", start: "2027-03-01", end: "2027-03-31" });
});

test("monthly split clips the first and last buckets to the requested range", () => {
  // last_3_months from 2026-07-12 → 2026-05-01..2026-07-12
  const cols = splitPeriodColumns("last_3_months", FY, { from: "", to: "" }, "month", TODAY);
  assert.deepEqual(cols, [
    { label: "May 2026", start: "2026-05-01", end: "2026-05-31" },
    { label: "Jun 2026", start: "2026-06-01", end: "2026-06-30" },
    { label: "Jul 2026", start: "2026-07-01", end: "2026-07-12" }, // clipped, month not yet over
  ]);
});

test("quarterly split of a full FY yields 4 Indian-FY quarters", () => {
  const cols = splitPeriodColumns("this_fy", FY, { from: "", to: "" }, "quarter", TODAY);
  assert.deepEqual(cols, [
    { label: "Apr–Jun 2026", start: "2026-04-01", end: "2026-06-30" },
    { label: "Jul–Sep 2026", start: "2026-07-01", end: "2026-09-30" },
    { label: "Oct–Dec 2026", start: "2026-10-01", end: "2026-12-31" },
    { label: "Jan–Mar 2027", start: "2027-01-01", end: "2027-03-31" },
  ]);
});

test("yearly split of a 2-year custom range yields 2 FY columns, each clipped", () => {
  const cols = splitPeriodColumns("custom", FY, { from: "2025-06-01", to: "2026-09-30" }, "year", TODAY);
  assert.deepEqual(cols, [
    { label: "FY 2025-26", start: "2025-06-01", end: "2026-03-31" },
    { label: "FY 2026-27", start: "2026-04-01", end: "2026-09-30" },
  ]);
});

test("a custom range's 'total' label shows the actual dates, not a preset name", () => {
  const cols = splitPeriodColumns("custom", FY, { from: "2026-06-01", to: "2026-06-30" }, "total", TODAY);
  assert.equal(cols[0].label, "1 Jun 2026 – 30 Jun 2026");
});
