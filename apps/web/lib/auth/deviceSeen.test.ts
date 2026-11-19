// node --experimental-strip-types --test lib/auth/deviceSeen.test.ts
//
// POST-A-486: a tab somebody is using tells the server it is still there, every ten minutes and not when nobody is at it.
import test from "node:test";
import assert from "node:assert/strict";
import { SEEN_EVERY_MS, shouldReportSeen } from "./deviceSeen.ts";

const NOW = 1_800_000_000_000;

test("the interval is ten minutes", () => {
  assert.equal(SEEN_EVERY_MS, 10 * 60 * 1000);
});

test("a tab that has never reported reports at once, whatever the activity", () => {
  assert.equal(shouldReportSeen(NOW, null, null), true);
  assert.equal(shouldReportSeen(NOW, undefined, NOW - 3 * SEEN_EVERY_MS), true);
});

test("it waits the interval before reporting again", () => {
  assert.equal(shouldReportSeen(NOW + SEEN_EVERY_MS - 1, NOW, NOW + SEEN_EVERY_MS - 2), false);
  assert.equal(shouldReportSeen(NOW + SEEN_EVERY_MS, NOW, NOW + SEEN_EVERY_MS - 5_000), true);
});

test("a tab left alone for the whole interval does not report, so an open tab is not a person at a desk", () => {
  assert.equal(shouldReportSeen(NOW + SEEN_EVERY_MS + 1, NOW, NOW), false);
  assert.equal(shouldReportSeen(NOW + 5 * SEEN_EVERY_MS, NOW, NOW + SEEN_EVERY_MS), false);
});

test("no known activity means no report once the first has gone", () => {
  assert.equal(shouldReportSeen(NOW + SEEN_EVERY_MS, NOW, null), false);
  assert.equal(shouldReportSeen(NOW + SEEN_EVERY_MS, NOW, Number.NaN), false);
});

test("a clock that moved back reports rather than going quiet", () => {
  assert.equal(shouldReportSeen(NOW - 1, NOW, NOW - 1), true);
});
