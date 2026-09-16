import { test } from "node:test";
import assert from "node:assert/strict";
import { objectOrNull, arrayOrEmpty } from "../lib/api/shape.ts";

test("an array is not an object payload — the case that crashed 13 screens", () => {
  // The smoke stub answers `data: []`. `[]` is truthy, so every `if (!x)`
  // guard on a screen passed it through and the first nested read threw.
  assert.equal(objectOrNull([]), null);
  assert.equal(objectOrNull([{ a: 1 }]), null);
});

test("null, undefined and scalars are not object payloads", () => {
  for (const v of [null, undefined, 0, 1, "", "error", true, false]) {
    assert.equal(objectOrNull(v), null, `${JSON.stringify(v)} should be null`);
  }
});

test("a real object passes through unchanged", () => {
  const payload = { fys: ["2025-26"], rows: [] };
  assert.equal(objectOrNull(payload), payload);
});

test("arrayOrEmpty accepts arrays and flattens everything else to []", () => {
  const rows = [1, 2, 3];
  assert.equal(arrayOrEmpty(rows), rows);
  for (const v of [null, undefined, {}, 0, "x", true]) {
    assert.deepEqual(arrayOrEmpty(v), []);
  }
});

test("an empty array is still an array — not turned into no-data", () => {
  // A list endpoint legitimately returns zero rows; that is not a shape error.
  const empty: unknown[] = [];
  assert.equal(arrayOrEmpty(empty), empty);
});
