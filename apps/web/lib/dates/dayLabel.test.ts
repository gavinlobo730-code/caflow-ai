// Unit tests for the calendar-date label. Run with:
//   node --experimental-strip-types --test lib/dates/dayLabel.test.ts
import test from "node:test";
import assert from "node:assert/strict";

import { dayLabel } from "./dayLabel.ts";

test("a date is labelled without passing through a Date, so no time zone can move it", () => {
  assert.equal(dayLabel("2026-08-22"), "22 Aug 2026");
  assert.equal(dayLabel("2026-01-01"), "01 Jan 2026");
  assert.equal(dayLabel("2027-03-31"), "31 Mar 2027");
});

test("a timestamp's date part is read as written", () => {
  assert.equal(dayLabel("2026-08-22T23:30:00+00:00"), "22 Aug 2026");
});

test("anything that is not a date reads as a dash", () => {
  for (const bad of [null, undefined, "", "yesterday", "22/08/2026", "2026-13-01"]) {
    assert.equal(dayLabel(bad as string | null | undefined), "—", String(bad));
  }
});
