// What AuthGuard may render — run with:
//   node --experimental-strip-types --test lib/auth/guardDecision.test.ts
//
// The rule under test is one line and it is the third of the three fail-opens
// that let production run at aal1 with MFA enrolled: `mfaPending === null`
// (unresolved) used to fall through to rendering the app. Only an explicit
// `false` may.
//
// NEGATIVE CONTROLS — each applied, then reverted:
//
//   | control                                         | tests that fail |
//   |-------------------------------------------------|-----------------|
//   | let unresolved (null) render the app            | 2               |
//   | drop the login-page exemption                   | 1               |
import test from "node:test";
import assert from "node:assert/strict";
import { mayRenderProtected, type GuardState } from "./guardDecision.ts";

const base: GuardState = {
  hasSession: true, mfaPending: false, hasFirm: true,
  isPublic: false, onLogin: false,
};
const at = (over: Partial<GuardState>) => mayRenderProtected({ ...base, ...over });

test("a resolved session owing nothing renders the app", () => {
  assert.equal(at({}), true);
});

test("UNRESOLVED does not render the app", () => {
  // The bug. `null` meant "still resolving" and rendered anyway.
  assert.equal(at({ mfaPending: null }), false);
});

test("a challenge owed does not render the app", () => {
  assert.equal(at({ mfaPending: true }), false);
});

test("only an explicit false is permission", () => {
  for (const pending of [true, null] as const) {
    assert.equal(at({ mfaPending: pending }), false, `mfaPending=${pending} rendered`);
  }
});

test("the login page renders while a challenge is owed, because it IS the challenge", () => {
  assert.equal(at({ mfaPending: true, onLogin: true }), true);
  assert.equal(at({ mfaPending: null, onLogin: true }), true);
});

test("no session renders only public pages", () => {
  assert.equal(at({ hasSession: false, isPublic: false }), false);
  assert.equal(at({ hasSession: false, isPublic: true }), true);
});

test("a signed-in user with no firm does not get the app", () => {
  assert.equal(at({ hasFirm: false }), false);
});

test("a resolving firm lookup is not treated as no firm", () => {
  // hasFirm === null means still loading; only an explicit false diverts to
  // onboarding. Unlike MFA, this one is not a security gate.
  assert.equal(at({ hasFirm: null }), true);
});
