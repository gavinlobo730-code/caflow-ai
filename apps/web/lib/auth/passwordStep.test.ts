// node --experimental-strip-types --test lib/auth/passwordStep.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { passwordStepButtonEnabled, passwordStepMode } from "./passwordStep.ts";

test("with the password not yet set the step is a save and needs both boxes", () => {
  assert.equal(passwordStepMode({ passwordSet: false, pw: "", pw2: "" }), "save");
  const base = { passwordSet: false, saving: false, needsReauth: false };
  assert.equal(passwordStepButtonEnabled({ ...base, pw: "", pw2: "" }), false);
  assert.equal(passwordStepButtonEnabled({ ...base, pw: "x", pw2: "" }), false);
  assert.equal(passwordStepButtonEnabled({ ...base, pw: "x", pw2: "x" }), true);
});

test("once the password is set the step is Continue and needs nothing typed (a person back on step 1 is never stuck)", () => {
  assert.equal(passwordStepMode({ passwordSet: true, pw: "", pw2: "" }), "continue");
  assert.equal(passwordStepButtonEnabled({ passwordSet: true, pw: "", pw2: "", saving: false, needsReauth: false }), true);
});

test("typing a new password after it was set makes it a change again, needing both boxes", () => {
  assert.equal(passwordStepMode({ passwordSet: true, pw: "a", pw2: "" }), "save");
  assert.equal(passwordStepMode({ passwordSet: true, pw: "", pw2: "b" }), "save");
  assert.equal(passwordStepButtonEnabled({ passwordSet: true, pw: "a", pw2: "", saving: false, needsReauth: false }), false);
  assert.equal(passwordStepButtonEnabled({ passwordSet: true, pw: "a", pw2: "a", saving: false, needsReauth: false }), true);
});

test("a save in flight, or a code waiting to be entered, holds the button", () => {
  assert.equal(passwordStepButtonEnabled({ passwordSet: true, pw: "", pw2: "", saving: true, needsReauth: false }), false);
  assert.equal(passwordStepButtonEnabled({ passwordSet: false, pw: "a", pw2: "a", saving: false, needsReauth: true }), false);
});
