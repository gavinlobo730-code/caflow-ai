// node --experimental-strip-types --test lib/auth/signupLanding.test.ts
//
// POST-A-480: a new-firm sign-up with an address that already has a practice must SAY SO, not open that practice.
import test from "node:test";
import assert from "node:assert/strict";
import { signedInAsSentence, signupLanding } from "./signupLanding.ts";

const base = { hasSession: true, hasFirm: false as boolean | null, signupStarted: true, createdHere: false };

test("a new person with a sign-up started gets the new-firm steps", () => {
  assert.equal(signupLanding({ ...base }), "wizard");
});

test("a sign-up started with an address that already has a practice gets the notice, not that practice's dashboard", () => {
  assert.equal(signupLanding({ ...base, hasFirm: true }), "existing-practice");
});

test("a member who only visited the page, with no sign-up started, is sent home as before", () => {
  assert.equal(signupLanding({ ...base, hasFirm: true, signupStarted: false }), "go-home");
});

test("while it is not yet known whether there is a practice the wizard stays, and it is never judged without a session", () => {
  assert.equal(signupLanding({ ...base, hasFirm: null }), "wizard");
  assert.equal(signupLanding({ ...base, hasFirm: true, hasSession: false }), "wizard");
});

test("the firm this very wizard just created never turns the wizard into the notice", () => {
  assert.equal(signupLanding({ ...base, hasFirm: true, createdHere: true }), "wizard");
});

test("the sentence names who they are, their role and the practice, and says less when it knows less", () => {
  assert.equal(signedInAsSentence("Asha Rao", "Manager", "Test Firm"), "You are signed in as Asha Rao, Manager at Test Firm.");
  assert.equal(signedInAsSentence("Asha Rao", null, "Test Firm"), "You are signed in as Asha Rao at Test Firm.");
  assert.equal(signedInAsSentence("Asha Rao", "Manager", ""), "You are signed in as Asha Rao, Manager.");
  assert.equal(signedInAsSentence("", "", ""), "You are signed in as this account.");
  assert.equal(signedInAsSentence(undefined, undefined, undefined), "You are signed in as this account.");
});
