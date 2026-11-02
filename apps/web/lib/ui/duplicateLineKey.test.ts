// POST-A-128 — the key that copies a line, as a pure rule.
//
// Run with: node --experimental-strip-types --test lib/ui/duplicateLineKey.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { isDuplicateLineKey, isMacPlatform, withCopyAfter } from "./duplicateLineKey.ts";

const chord = (over: Partial<Parameters<typeof isDuplicateLineKey>[0]> = {}) =>
  ({ key: "d", ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...over });

test("Control+D copies a line on Windows and Linux, in either case of the letter", () => {
  assert.equal(isDuplicateLineKey(chord({ ctrlKey: true }), false), true);
  assert.equal(isDuplicateLineKey(chord({ ctrlKey: true, key: "D" }), false), true, "Caps Lock");
});

test("Command+D copies a line on a Mac, and Control+D does not: it is the text field's forward-delete there", () => {
  assert.equal(isDuplicateLineKey(chord({ metaKey: true }), true), true);
  assert.equal(isDuplicateLineKey(chord({ ctrlKey: true }), true), false);
  assert.equal(isDuplicateLineKey(chord({ metaKey: true, ctrlKey: true }), true), false);
});

test("Command+D on Windows and Linux is not the chord", () => {
  assert.equal(isDuplicateLineKey(chord({ metaKey: true }), false), false);
});

test("a plain D, another letter, or Shift or Alt held, is left to the field and the browser", () => {
  assert.equal(isDuplicateLineKey(chord(), false), false, "typing d");
  assert.equal(isDuplicateLineKey(chord({ ctrlKey: true, key: "e" }), false), false);
  assert.equal(isDuplicateLineKey(chord({ ctrlKey: true, shiftKey: true }), false), false, "Ctrl+Shift+D bookmarks every tab");
  assert.equal(isDuplicateLineKey(chord({ ctrlKey: true, altKey: true }), false), false, "AltGr");
  assert.equal(isDuplicateLineKey(chord({ metaKey: true, shiftKey: true }), true), false);
});

test("a Mac is told apart from the browser's own words, and where there is no browser it is not one", () => {
  assert.equal(isMacPlatform({ platform: "MacIntel" }), true);
  assert.equal(isMacPlatform({ platform: "iPad" }), true);
  assert.equal(isMacPlatform({ platform: "", userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)" }), true);
  assert.equal(isMacPlatform({ platform: "Win32" }), false);
  assert.equal(isMacPlatform({ platform: "Linux x86_64" }), false);
  assert.equal(isMacPlatform(undefined), false);
});

test("the copy goes right after the line it was taken from, and the original is untouched", () => {
  const rows = [{ id: 1, n: "a" }, { id: 2, n: "b" }, { id: 3, n: "c" }];
  const out = withCopyAfter(rows, 1, (r) => ({ ...r, id: 9 }));
  assert.deepEqual(out.map((r) => r.id), [1, 2, 9, 3]);
  assert.equal(out[2].n, "b");
  assert.deepEqual(rows.map((r) => r.id), [1, 2, 3], "the input array was changed");
  assert.deepEqual(withCopyAfter(rows, 2, (r) => ({ ...r, id: 9 })).map((r) => r.id), [1, 2, 3, 9], "the last line");
});

test("an index outside the rows copies nothing", () => {
  const rows = [{ id: 1 }];
  for (const i of [-1, 1, 5, 0.5, Number.NaN]) assert.deepEqual(withCopyAfter(rows, i, (r) => ({ ...r, id: 9 })), rows, `index ${i}`);
});
