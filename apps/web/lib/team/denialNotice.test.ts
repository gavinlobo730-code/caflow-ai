import { test } from "node:test";
import assert from "node:assert/strict";
import { denialNotice } from "./denialNotice.ts";

// POST-A-005. The access drawer shows the server's sentence about what a block
// reaches, and shows nothing when it was told nothing. This is the whole of the
// browser's decision, so it is tested as a decision: a sentence comes back as
// received, and everything that is not a sentence is "not told".

test("a sentence comes back exactly as the server sent it", () => {
  const sent = "A block here is enforced by the server.  It is not checked on a direct read. ";
  // not trimmed, not collapsed, not reworded
  assert.equal(denialNotice(sent), sent);
});

test("an absent field is not told, and not told is nothing", () => {
  // an older backend, or a frontend live before the backend that serves the field
  assert.equal(denialNotice(undefined), null);
  assert.equal(denialNotice(null), null);
});

test("a blank sentence is not told", () => {
  assert.equal(denialNotice(""), null);
  assert.equal(denialNotice("   "), null);
  assert.equal(denialNotice("\n\t"), null);
});

test("anything that is not a string is not told, however truthy", () => {
  // `{}` and `[]` are truthy, and a payload that is not a string must not reach
  // the page as one: an object rendered as a React child throws.
  for (const v of [{}, [], ["a sentence"], { text: "a sentence" }, 0, 1, true, false, 42.5]) {
    assert.equal(denialNotice(v), null, `${JSON.stringify(v)} must not be rendered`);
  }
});
