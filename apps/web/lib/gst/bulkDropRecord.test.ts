// What the bulk GSTR-2B panel says about answered files the server did not record (POST-A-057). Run with:
//   node --experimental-strip-types --test lib/gst/bulkDropRecord.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { notRecordedSentence } from "./bulkDropRecord.ts";

test("nothing is said when every answered file was recorded", () => {
  assert.equal(notRecordedSentence([], true), null);
  assert.equal(notRecordedSentence([], false), null);
});

test("when the rest of the drop was recorded, the files that were not are named, not the whole drop", () => {
  const one = notRecordedSentence(["june.json"], true) ?? "";
  assert.match(one, /june\.json was not recorded, so it will not be listed/);
  assert.doesNotMatch(one, /this drop/);
  const two = notRecordedSentence(["a.json", "b.json"], true) ?? "";
  assert.match(two, /a\.json, b\.json was not recorded, so they/);
});

test("only a drop none of which was recorded is spoken of as a whole", () => {
  assert.match(notRecordedSentence(["a.json"], false) ?? "", /the files of this drop was not recorded/);
});

test("the sentence points at no place on the page", () => {
  for (const s of [notRecordedSentence(["a"], true), notRecordedSentence(["a"], false)]) {
    assert.doesNotMatch(s ?? "", /\babove\b|\bbelow\b/);
  }
});
