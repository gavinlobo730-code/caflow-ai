// Period-picker date-range math. Run with:
//   node --experimental-strip-types --test lib/dates/periods.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { fyRangeFor, shiftFY, resolvePeriodRange, periodOptionLabel, splitPeriodColumns, periodSplitNotice, formatRangeLabel, financialYearChoices, encodePeriodChoice, decodePeriodChoice, periodChoices, FY_CHOICE_COUNT } from "./periods.ts";

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

test("all_time resolves to the same wide bound custom falls back to", () => {
  assert.deepEqual(resolvePeriodRange("all_time", FY, { from: "", to: "" }, TODAY), { start: "1900-01-01", end: "2999-12-31" });
});

test("periodOptionLabel resolves FY-dependent labels", () => {
  // Named outright, matching the dropdown. "This Financial Year" was relative
  // to a year chosen in the client header, which is exactly the thing removed:
  // a heading reading "This" over rows from a year the header disagreed with.
  assert.equal(periodOptionLabel("this_fy", FY), "FY 2026-27");
  assert.equal(periodOptionLabel("last_fy", FY), "FY 2025-26");
  assert.equal(periodOptionLabel("today", FY), "Today");
  assert.equal(periodOptionLabel("all_time", FY), "All Time");
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

test("all_time collapses to a single 'All Time' column even when Monthly/Quarterly is requested — a 1900-2999 span split by month would be 13,000+ columns", () => {
  for (const granularity of ["month", "quarter", "year"] as const) {
    const cols = splitPeriodColumns("all_time", FY, { from: "", to: "" }, granularity, TODAY);
    assert.equal(cols.length, 1);
    assert.equal(cols[0].label, "All Time");
  }
});

test("an accidentally wide custom range (not just all_time) also collapses rather than generating a huge column count", () => {
  const cols = splitPeriodColumns("custom", FY, { from: "1950-01-01", to: "2026-01-01" }, "month", TODAY);
  assert.equal(cols.length, 1);
});

// ── All Time against the real ledger ──────────────────────────────────────────
// The bug these cover: "Display columns by: Quarterly" was a silent no-op on
// All Time. It collapsed (correctly — 1900–2999 by quarter is ~4,400 columns)
// but said nothing, so the control read as broken. Given the client's actual
// posted span, All Time becomes a range that can genuinely be split.

const SPAN = { first: "2024-04-01", last: "2026-03-31" }; // two financial years

test("all_time with a ledger span splits by quarter instead of collapsing", () => {
  const cols = splitPeriodColumns("all_time", FY, { from: "", to: "" }, "quarter", TODAY, SPAN);
  assert.equal(cols.length, 8, "two financial years is eight quarters");
  assert.equal(cols[0].start, "2024-04-01");
  assert.equal(cols[7].end, "2026-03-31");
});

test("all_time with a ledger span splits by month and by year too", () => {
  assert.equal(splitPeriodColumns("all_time", FY, { from: "", to: "" }, "month", TODAY, SPAN).length, 24);
});

test("'Yearly' means FINANCIAL year, not calendar year", () => {
  // Apr 2024 – Mar 2026 is exactly two Indian financial years. Under a calendar
  // split it would be three columns, the last holding one quarter of a year —
  // which is not a unit any CA reports in.
  const cols = splitPeriodColumns("all_time", FY, { from: "", to: "" }, "year", TODAY, SPAN);
  assert.equal(cols.length, 2);
  assert.deepEqual(cols.map((c) => c.label), ["FY 2024-25", "FY 2025-26"]);
});

test("the split never runs past the ledger — no empty leading or trailing column", () => {
  const cols = splitPeriodColumns("all_time", FY, { from: "", to: "" }, "quarter", TODAY, SPAN);
  assert.ok(cols.every((c) => c.start >= SPAN.first && c.end <= SPAN.last));
});

test("all_time WITHOUT a span still collapses — an empty ledger must not invent a range", () => {
  const cols = splitPeriodColumns("all_time", FY, { from: "", to: "" }, "quarter", TODAY, null);
  assert.equal(cols.length, 1);
  assert.equal(cols[0].label, "All Time");
});

test("a ledger span does not affect any period other than all_time", () => {
  const cols = splitPeriodColumns("this_fy", FY, { from: "", to: "" }, "quarter", TODAY, SPAN);
  assert.equal(cols.length, 4);
  assert.equal(cols[0].start, "2026-04-01", "this_fy must stay the FY, not the ledger span");
});

test("total still returns exactly one column — the regression a naive refactor introduces", () => {
  // splitBy() returns [] for "total"; falling through to it would hand every
  // existing single-period report zero columns instead of a total.
  for (const span of [SPAN, null] as const) {
    for (const mode of ["this_fy", "all_time", "last_fy"] as const) {
      const cols = splitPeriodColumns(mode, FY, { from: "", to: "" }, "total", TODAY, span);
      assert.equal(cols.length, 1, `${mode} with span=${span ? "set" : "null"}`);
    }
  }
});

test("a ledger span longer than the column cap collapses rather than rendering 100+ columns", () => {
  const long = { first: "2000-01-01", last: "2026-01-01" }; // 26 years
  assert.equal(splitPeriodColumns("all_time", FY, { from: "", to: "" }, "month", TODAY, long).length, 1);
  // ...but quarterly over the same span is 105 columns, also over the cap,
  // while yearly (27) is under it and must still split.
  assert.equal(splitPeriodColumns("all_time", FY, { from: "", to: "" }, "year", TODAY, long).length, 27);
});

// ── The notice: why a requested split did not happen ──────────────────────────

test("no notice when the split actually happened", () => {
  assert.equal(periodSplitNotice("all_time", FY, { from: "", to: "" }, "quarter", TODAY, SPAN), null);
  assert.equal(periodSplitNotice("this_fy", FY, { from: "", to: "" }, "month", TODAY, SPAN), null);
});

test("no notice for 'total' — nothing was refused", () => {
  assert.equal(periodSplitNotice("all_time", FY, { from: "", to: "" }, "total", TODAY, null), null);
});

test("an empty ledger explains itself instead of silently showing one column", () => {
  const notice = periodSplitNotice("all_time", FY, { from: "", to: "" }, "quarter", TODAY, null);
  assert.ok(notice && notice.includes("No posted entries"));
});

test("exceeding the column cap says so, and says what to do about it", () => {
  const long = { first: "2000-01-01", last: "2026-01-01" };
  const notice = periodSplitNotice("all_time", FY, { from: "", to: "" }, "month", TODAY, long);
  assert.ok(notice && notice.includes("Monthly"), "names the granularity that was refused");
  assert.ok(notice && /\d+/.test(notice), "says how many columns it would have been");
});

test("an inverted custom range is reported rather than rendered as one odd column", () => {
  const notice = periodSplitNotice("custom", FY, { from: "2026-06-30", to: "2026-06-01" }, "month", TODAY);
  assert.ok(notice && notice.includes("ends before it starts"));
});


// ── Choosing a financial year on the page ──────────────────────────────────
// These back the removal of the client header's FY selector. The failure they
// guard against is not an exception: it is two controls on one screen, each
// individually correct, describing different periods.

test("the year list runs backwards from the current one and includes no future year", () => {
  const inMarch = new Date("2027-03-15T00:00:00");   // still FY 2026-27
  assert.deepEqual(financialYearChoices(4, inMarch),
    ["2026-27", "2025-26", "2024-25", "2023-24"]);

  const inApril = new Date("2027-04-01T00:00:00");   // FY 2027-28 begins
  assert.equal(financialYearChoices(4, inApril)[0], "2027-28");
});

test("the year list offers FY_CHOICE_COUNT years by default", () => {
  assert.equal(financialYearChoices(undefined, new Date("2026-08-28T00:00:00")).length,
               FY_CHOICE_COUNT);
});

test("a period choice round-trips through the single dropdown value", () => {
  for (const mode of ["today", "yesterday", "this_week", "last_3_months", "all_time", "custom"] as const) {
    const encoded = encodePeriodChoice(mode, FY);
    assert.deepEqual(decodePeriodChoice(encoded, FY), { mode, financialYear: FY });
  }
  assert.equal(encodePeriodChoice("this_fy", FY), "fy:2026-27");
  assert.deepEqual(decodePeriodChoice("fy:2026-27", "2024-25"),
                   { mode: "this_fy", financialYear: "2026-27" });
});

test("last_fy encodes as the year it actually means, not as a relative mode", () => {
  // Anything persisted before this change still resolves to a real year rather
  // than staying relative to a base nothing sets any more.
  assert.equal(encodePeriodChoice("last_fy", FY), "fy:2025-26");
  const decoded = decodePeriodChoice(encodePeriodChoice("last_fy", FY), FY);
  assert.deepEqual(decoded, { mode: "this_fy", financialYear: "2025-26" });
  assert.deepEqual(resolvePeriodRange(decoded.mode, decoded.financialYear, { from: "", to: "" }),
                   resolvePeriodRange("last_fy", FY, { from: "", to: "" }));
});

test("every dropdown option decodes to a range, and every FY option is named", () => {
  const opts = periodChoices(4, new Date("2026-08-28T00:00:00"));
  for (const o of opts) {
    if (o.value === "custom") continue;
    const { mode, financialYear } = decodePeriodChoice(o.value, FY);
    const range = resolvePeriodRange(mode, financialYear, { from: "", to: "" }, "2026-08-28");
    assert.ok(range.start <= range.end, `${o.value} produced an inverted range`);
  }
  const fyLabels = opts.filter((o) => o.value.startsWith("fy:")).map((o) => o.label);
  assert.deepEqual(fyLabels, ["FY 2026-27", "FY 2025-26", "FY 2024-25", "FY 2023-24"]);
  // The relative labels are what disagreed with the header. Nothing offers them.
  assert.equal(opts.some((o) => /This Financial Year|Last Financial Year/.test(o.label)), false);
});

test("picking a financial year picks the April-March range for that year", () => {
  const { mode, financialYear } = decodePeriodChoice("fy:2024-25", "2026-27");
  assert.deepEqual(resolvePeriodRange(mode, financialYear, { from: "", to: "" }),
                   { start: "2024-04-01", end: "2025-03-31" });
});
