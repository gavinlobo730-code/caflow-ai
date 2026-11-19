// node --experimental-strip-types --test lib/auth/idleTimeout.test.ts
//
// POST-A-483: thirty minutes alone signs a person out, with a minute's warning.
import test from "node:test";
import assert from "node:assert/strict";
import { ACTIVITY_WRITE_EVERY_MS, IDLE_LIMIT_MS, WARN_BEFORE_MS, idleStatus, parseActivity, shouldWriteActivity } from "./idleTimeout.ts";

const NOW = 1_800_000_000_000;

test("the limit is thirty minutes with a warning in the last minute", () => {
  assert.equal(IDLE_LIMIT_MS, 30 * 60 * 1000);
  assert.equal(WARN_BEFORE_MS, 60 * 1000);
});

test("just now is active with the whole limit left", () => {
  assert.deepEqual(idleStatus(NOW, NOW), { state: "active", secondsLeft: 1800 });
});

test("the warning starts sixty seconds before the end and counts down", () => {
  assert.equal(idleStatus(NOW + IDLE_LIMIT_MS - WARN_BEFORE_MS - 1, NOW).state, "active");
  assert.deepEqual(idleStatus(NOW + IDLE_LIMIT_MS - WARN_BEFORE_MS, NOW), { state: "warning", secondsLeft: 60 });
  assert.deepEqual(idleStatus(NOW + IDLE_LIMIT_MS - 1_500, NOW), { state: "warning", secondsLeft: 2 });
});

test("at the limit and beyond the session is expired", () => {
  assert.deepEqual(idleStatus(NOW + IDLE_LIMIT_MS, NOW), { state: "expired", secondsLeft: 0 });
  assert.deepEqual(idleStatus(NOW + 5 * 60 * 60 * 1000, NOW), { state: "expired", secondsLeft: 0 });
});

test("a missing, unreadable or future stamp is read as just now, so a clock that jumped signs nobody out", () => {
  for (const last of [null, undefined, Number.NaN, NOW + 10 * 60_000]) {
    assert.deepEqual(idleStatus(NOW, last as number | null | undefined), { state: "active", secondsLeft: 1800 });
  }
});

test("a tab writes its activity at most every few seconds, and at once after a clock change", () => {
  assert.equal(shouldWriteActivity(NOW, null), true);
  assert.equal(shouldWriteActivity(NOW + 1_000, NOW), false);
  assert.equal(shouldWriteActivity(NOW + ACTIVITY_WRITE_EVERY_MS, NOW), true);
  assert.equal(shouldWriteActivity(NOW - 1, NOW), true);
});

test("the stored stamp is a number or nothing", () => {
  assert.equal(parseActivity(String(NOW)), NOW);
  assert.equal(parseActivity(null), null);
  assert.equal(parseActivity(""), null);
  assert.equal(parseActivity("soon"), null);
});
