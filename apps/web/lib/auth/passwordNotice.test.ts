// Run with: node --experimental-strip-types --test lib/auth/passwordNotice.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { rememberPasswordNotice, takePasswordNotice, rememberPasswordRefusal, takePasswordRefusal } from "./passwordNotice.ts";

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

// POST-A-512: the live test of 19-11-2026 showed NOTHING when the service refused the change, because the refusal was set on a page
// that had gone. A refusal is carried to the next page exactly as the success sentence is, and the two never mix.
test("a refusal left by a page that was unmounted is read once, then forgotten", () => {
  assert.equal(takePasswordRefusal(), null, "nothing was left");
  rememberPasswordRefusal("Your current password is needed to change it. Enter it and try again.");
  assert.equal(takePasswordRefusal(), "Your current password is needed to change it. Enter it and try again.");
  assert.equal(takePasswordRefusal(), null, "shown once");
});

test("a refusal and a success sentence are kept apart", () => {
  rememberPasswordNotice("Your password has been updated.");
  rememberPasswordRefusal("Current password is incorrect.");
  assert.equal(takePasswordNotice(), "Your password has been updated.");
  assert.equal(takePasswordRefusal(), "Current password is incorrect.");
});
