// The filing period a CA picks, and the save that used to throw on every one.
//
// GST-12: the Add GST Filing modal raised a RangeError whenever it was saved.
// Two readers disagreed about one string — the due-date filler took the option
// apart with split(" ") and the save with split("-") — because the option's
// value and its label were the same "MMM YYYY". These tests are about the
// two halves of that: the option carries a machine value, and there is one
// parser.
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildMonthOptions, parsePeriodOption, periodBounds, MONTH_NAMES } from "./filingPeriod.ts";

// ── The option carries two different strings ───────────────────────────────

test("value is machine-readable and label is human-readable, and they differ", () => {
  const opts = buildMonthOptions(new Date(2026, 4, 15));   // 15 May 2026
  const last = opts[opts.length - 1];
  assert.equal(last.value, "2026-05");
  assert.equal(last.label, "May 2026");
  for (const o of opts) {
    assert.notEqual(o.value, o.label,
      "value === label is the defect: it lets a reader parse the human form");
    assert.match(o.value, /^\d{4}-(0[1-9]|1[0-2])$/);
  }
});

test("twelve months ending with the month given, oldest first", () => {
  const opts = buildMonthOptions(new Date(2026, 1, 3));    // 3 Feb 2026
  assert.equal(opts.length, 12);
  assert.equal(opts[0].value, "2025-03");
  assert.equal(opts[11].value, "2026-02");
  assert.equal(opts[0].label, "Mar 2025");
});

test("the window crosses a year boundary without arithmetic on the label", () => {
  const opts = buildMonthOptions(new Date(2026, 0, 20));   // 20 Jan 2026
  assert.equal(opts[11].value, "2026-01");
  assert.equal(opts[10].value, "2025-12");
  assert.equal(opts[0].value, "2025-02");
});

// ── One parser ─────────────────────────────────────────────────────────────

test("a period value parses", () => {
  assert.deepEqual(parsePeriodOption("2026-05"), { year: 2026, month: 5 });
  assert.deepEqual(parsePeriodOption("2026-01"), { year: 2026, month: 1 });
  assert.deepEqual(parsePeriodOption("2026-12"), { year: 2026, month: 12 });
});

test("THE STRING THAT USED TO ARRIVE HERE is refused, not half-read", () => {
  // "May 2026".split("-") is ["May 2026"], .map(Number) is [NaN], so pYear was
  // NaN and pMonth undefined — and nothing checked, so the modal built
  // "NaN-undefined-01" and then threw inside toISOString().
  assert.equal(parsePeriodOption("May 2026"), null);
  assert.equal(parsePeriodOption(""), null);
  assert.equal(parsePeriodOption("2026-5"), null);     // unpadded
  assert.equal(parsePeriodOption("2026-13"), null);    // no such month
  assert.equal(parsePeriodOption("2026-00"), null);
  assert.equal(parsePeriodOption("2026-05-01"), null); // a date is not a period
});

// ── The period's own dates ─────────────────────────────────────────────────

test("a period runs from the 1st to the last day of its month", () => {
  assert.deepEqual(periodBounds("2026-05"), { start: "2026-05-01", end: "2026-05-31" });
  assert.deepEqual(periodBounds("2026-04"), { start: "2026-04-01", end: "2026-04-30" });
  assert.deepEqual(periodBounds("2026-12"), { start: "2026-12-01", end: "2026-12-31" });
});

test("February, both kinds", () => {
  assert.equal(periodBounds("2026-02")!.end, "2026-02-28");
  assert.equal(periodBounds("2024-02")!.end, "2024-02-29");
});

test("the month end is not read back in UTC", () => {
  // The old line was `new Date(pYear, pMonth, 0).toISOString().slice(0, 10)`.
  // new Date(2026, 5, 0) is local midnight on 31 May; in IST (UTC+5:30) that
  // instant is 30 May 18:30 UTC, so the old form returned "2026-05-30" — the
  // filing period ended a day early. This is the assertion that catches a
  // revert.
  const utcForm = new Date(2026, 5, 0).toISOString().slice(0, 10);
  const end = periodBounds("2026-05")!.end;
  assert.equal(end, "2026-05-31");
  // getTimezoneOffset() is minutes BEHIND UTC, so it is negative for zones
  // ahead of it. Only those lose a day this way — local midnight there is the
  // previous evening in UTC. India is one of them at -330; a zone west of
  // Greenwich reads the same answer out of both forms, which is exactly why a
  // defect like this survives review by anyone not sitting in it.
  if (new Date().getTimezoneOffset() < 0) {
    assert.notEqual(end, utcForm,
      "in a zone ahead of UTC the old form gives the previous day");
  }
});

test("an unparseable period has no bounds rather than invented ones", () => {
  assert.equal(periodBounds("May 2026"), null);
  assert.equal(periodBounds(""), null);
});

// ── The old code, run here, so the control is intrinsic ────────────────────

test("THE OLD SAVE, reproduced, throws — this is the bug GST-12 named", () => {
  // Exactly what app/gst/page.tsx did, on exactly what it was handed.
  const period = "May 2026";                       // the option's value WAS its label
  const [pYear, pMonth] = period.split("-").map(Number);
  assert.ok(Number.isNaN(pYear));
  assert.equal(pMonth, undefined);
  assert.equal(`${pYear}-${String(pMonth).padStart(2, "0")}-01`, "NaN-undefined-01");
  assert.throws(() => new Date(pYear, pMonth as unknown as number, 0).toISOString(),
    RangeError,
    "the modal's try/catch turned this into an unexplained error on every save");
  // And the same call on the FIXED value does not throw, so the parse was the
  // whole of it — which is why the second defect below stayed hidden.
  const p = parsePeriodOption("2026-05")!;
  assert.doesNotThrow(() => new Date(p.year, p.month, 0).toISOString());
});

test("month names are the short forms the label uses", () => {
  assert.equal(MONTH_NAMES.length, 12);
  assert.equal(MONTH_NAMES[0], "Jan");
  assert.equal(MONTH_NAMES[11], "Dec");
});
