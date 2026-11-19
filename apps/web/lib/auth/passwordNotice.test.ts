// Run with: node --experimental-strip-types --test lib/auth/passwordNotice.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { rememberPasswordNotice, takePasswordNotice } from "./passwordNotice.ts";

test("a sentence left by a page that was unmounted is read once, then forgotten", () => {
  assert.equal(takePasswordNotice(), null, "nothing was left");
  rememberPasswordNotice("Your password has been updated.");
  assert.equal(takePasswordNotice(), "Your password has been updated.");
  assert.equal(takePasswordNotice(), null, "it is shown once and not again on a later visit");
});

test("the latest sentence wins", () => {
  rememberPasswordNotice("first");
  rememberPasswordNotice("second");
  assert.equal(takePasswordNotice(), "second");
  assert.equal(takePasswordNotice(), null);
});
