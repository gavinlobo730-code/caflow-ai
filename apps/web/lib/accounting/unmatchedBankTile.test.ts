// Run with: node --experimental-strip-types --test lib/accounting/unmatchedBankTile.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  FAILED_NOTE,
  NOT_ALLOWED_NOTE,
  bankCountDecision,
  readingFromAnswer,
  unmatchedBankTile,
} from "./unmatchedBankTile.ts";

test("a real count is the figure, amber only when it is positive", () => {
  assert.deepEqual(unmatchedBankTile({ kind: "count", count: 12 }),
    { value: "12", note: null, attention: true, opensBank: true });
  assert.deepEqual(unmatchedBankTile({ kind: "count", count: 0 }),
    { value: "0", note: null, attention: false, opensBank: true });
});

test("a person who cannot read banking is told so, and is never shown a zero", () => {
  const tile = unmatchedBankTile({ kind: "not_allowed" });
  assert.equal(tile.value, "—");
  assert.equal(tile.note, NOT_ALLOWED_NOTE);
  assert.equal(tile.attention, false);
  assert.equal(tile.opensBank, false);
});

test("a count the database could not give is a dash with a reason, never a zero", () => {
  const tile = unmatchedBankTile({ kind: "failed" });
  assert.equal(tile.value, "—");
  assert.equal(tile.note, FAILED_NOTE);
  assert.notEqual(tile.value, "0");
});

test("while the count is awaited the tile is a dash, not a zero", () => {
  const tile = unmatchedBankTile({ kind: "waiting" });
  assert.equal(tile.value, "—");
  assert.equal(tile.note, null);
});

test("a finished request is a count, or unknown: anything but a whole non-negative figure in a successful answer is unknown", () => {
  assert.deepEqual(readingFromAnswer({ success: true, data: { unmatched: 7 }, error: null }), { kind: "count", count: 7 });
  assert.deepEqual(readingFromAnswer({ success: true, data: { unmatched: 0 }, error: null }), { kind: "count", count: 0 });
  // an answer that carries no figure is unknown, never zero
  assert.deepEqual(readingFromAnswer({ success: true, data: {}, error: null }), { kind: "failed" });
  assert.deepEqual(readingFromAnswer({ success: true, data: null, error: null }), { kind: "failed" });
  assert.deepEqual(readingFromAnswer({ success: false, data: { unmatched: 5 }, error: "boom" }), { kind: "failed" });
  assert.deepEqual(readingFromAnswer({ success: true, data: { unmatched: "5" } }), { kind: "failed" });
  assert.deepEqual(readingFromAnswer({ success: true, data: { unmatched: -1 } }), { kind: "failed" });
  assert.deepEqual(readingFromAnswer({ success: true, data: { unmatched: 2.5 } }), { kind: "failed" });
  assert.deepEqual(readingFromAnswer({ success: true, data: { unmatched: Number.NaN } }), { kind: "failed" });
  assert.deepEqual(readingFromAnswer(null), { kind: "failed" });
  assert.deepEqual(readingFromAnswer(undefined), { kind: "failed" });
  assert.deepEqual(readingFromAnswer("7"), { kind: "failed" });
});

test("the count is asked only once the permission map has resolved and says yes", () => {
  assert.equal(bankCountDecision(false, false), "wait");
  // an unresolved map must not be read as a yes, even if the flag were true
  assert.equal(bankCountDecision(false, true), "wait");
  assert.equal(bankCountDecision(true, true), "ask");
  assert.equal(bankCountDecision(true, false), "not_allowed");
});
