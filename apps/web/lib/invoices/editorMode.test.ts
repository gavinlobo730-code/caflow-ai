import { test } from "node:test";
import assert from "node:assert/strict";
import { editorMode } from "./editorMode.ts";

// POST-A-125. A new invoice that was created and then refused at the issue is a draft on the server. The currency and the series
// suggestion belong to the NEW invoice only, so they must follow the draft and not `isEdit`.

test("a new invoice that has not been saved is all new: currency editable, number fillable", () => {
  assert.deepEqual(editorMode(false, null), { draftExists: false, currencyIsFrozen: false, mayFillTheNumber: true });
});

test("an invoice opened for editing is a draft that exists: currency frozen, number not filled", () => {
  assert.deepEqual(editorMode(true, null), { draftExists: true, currencyIsFrozen: true, mayFillTheNumber: false });
});

test("a new invoice that was created and refused at the issue is a draft that exists, as an edit is", () => {
  assert.deepEqual(editorMode(false, "11111111-1111-1111-1111-111111111111"),
    { draftExists: true, currencyIsFrozen: true, mayFillTheNumber: false });
});

test("an empty id is no draft", () => {
  assert.equal(editorMode(false, "").draftExists, false);
});
