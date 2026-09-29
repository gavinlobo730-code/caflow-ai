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

// ── /login/forgot-password (portal) ─────────────────────────────────────────
// The portal's own "Forgot password?" link lands on this same shared
// reset-request page (?portal=1). A fully-authenticated session — firm staff
// testing the portal in the same browser, or a portal client who is already
// signed in — must not be bounced away from it before the reset form is ever
// shown.
//
// NEGATIVE CONTROL: dropping the isPortalRecovery exemption (bounce
// unconditionally whenever hasSession && onLogin && mfaPending === false)
// fails 1 test.

import { shouldBounceFromLogin } from "./guardDecision.ts";

const loginBounceBase = {
  hasSession: true, mfaPending: false, onLogin: true, isPortalRecovery: false,
} as const;
const bouncesFromLogin = (over: Partial<typeof loginBounceBase>) =>
  shouldBounceFromLogin({ ...loginBounceBase, ...over });

test("a fully authenticated session sitting on /login is bounced to /", () => {
  assert.equal(bouncesFromLogin({}), true);
});

test("the portal's own forgot-password page is NOT bounced, even when fully authenticated", () => {
  // The bug: this used to send an already-signed-in visitor to "/" before
  // they ever saw the reset-request form.
  assert.equal(bouncesFromLogin({ isPortalRecovery: true }), false);
});

test("no session means nothing to bounce", () => {
  assert.equal(bouncesFromLogin({ hasSession: false }), false);
});

test("a page outside /login is never bounced by this rule", () => {
  assert.equal(bouncesFromLogin({ onLogin: false }), false);
});

test("an unresolved or owed MFA challenge is not bounced by this rule either", () => {
  assert.equal(bouncesFromLogin({ mfaPending: true }), false);
  assert.equal(bouncesFromLogin({ mfaPending: null }), false);
});

// ── RoleGuard ────────────────────────────────────────────────────────────────
// NEGATIVE CONTROL: dropping the `roleLoading` term (the old
// `!loading && !permitted`) fails "a role still resolving is not a refusal".

import { roleGuardDecision } from "./guardDecision.ts";

test("a role still resolving is not a refusal — the guard waits", () => {
  // The bug: session known, role not yet, userRole null => hasRole false.
  assert.equal(roleGuardDecision({ loading: false, roleLoading: true, permitted: false }), "wait");
});

test("a session still restoring waits too", () => {
  assert.equal(roleGuardDecision({ loading: true, roleLoading: true, permitted: false }), "wait");
});

test("a decided role that is allowed renders", () => {
  assert.equal(roleGuardDecision({ loading: false, roleLoading: false, permitted: true }), "allow");
});

test("a decided role that is not allowed is refused", () => {
  assert.equal(roleGuardDecision({ loading: false, roleLoading: false, permitted: false }), "deny");
});

// ── /signup bounce ───────────────────────────────────────────────────────────
// sweep-auth-and-public-02: /signup had no mirror of the onLogin bounce, so a
// fully authenticated Partner with an existing firm still got the live
// "Create your firm" form.
//
// NEGATIVE CONTROLS — each applied, then reverted:
//
//   | control                                    | tests that fail |
//   |--------------------------------------------|------------------|
//   | drop the hasFirm === true term (treat any hasFirm as a firm) | 1 |
//   | drop the onSignup term (bounce from anywhere)                | 1 |
//   | drop the mfaPending === false term (bounce mid-challenge)    | 1 |

import { shouldBounceFromSignup } from "./guardDecision.ts";

const signupBase = {
  hasSession: true, mfaPending: false, hasFirm: true, onSignup: true,
} as const;
const bounces = (over: Partial<typeof signupBase>) =>
  shouldBounceFromSignup({ ...signupBase, ...over });

test("a fully authenticated session with an existing firm is bounced from /signup", () => {
  assert.equal(bounces({}), true);
});

test("a firm-less session (mid-signup) is left alone", () => {
  assert.equal(bounces({ hasFirm: false }), false);
});

test("a still-resolving firm lookup is left alone, not treated as having a firm", () => {
  assert.equal(bounces({ hasFirm: null }), false);
});

test("no session means nothing to bounce", () => {
  assert.equal(bounces({ hasSession: false }), false);
});

test("a page outside /signup is never bounced by this rule", () => {
  assert.equal(bounces({ onSignup: false }), false);
});

test("an unresolved or owed MFA challenge is not bounced — /login's own redirect handles it", () => {
  assert.equal(bounces({ mfaPending: true }), false);
  assert.equal(bounces({ mfaPending: null }), false);
});

// ── /onboarding wizard ───────────────────────────────────────────────────────
// sweep-auth-and-public-04: /onboarding is PUBLIC, so mayRenderProtected()
// never gets asked about it and the wizard rendered Step 1 with no session at
// all — "Auth session missing!" on submit, a blank email in the greeting.
//
// NEGATIVE CONTROL: dropping the `hasSession` term (always render once
// loading is done) fails the one test that matters here.

import { mayRenderOnboardingWizard } from "./guardDecision.ts";

test("a resolved session renders the wizard", () => {
  assert.equal(mayRenderOnboardingWizard({ loading: false, hasSession: true }), true);
});

test("no session, once resolved, does NOT render the wizard", () => {
  // The bug: this used to render Step 1 regardless.
  assert.equal(mayRenderOnboardingWizard({ loading: false, hasSession: false }), false);
});

test("still loading renders the wizard's own placeholder rather than the expired-link state", () => {
  // Avoids flashing "expired" before the session has even been restored.
  assert.equal(mayRenderOnboardingWizard({ loading: true, hasSession: false }), true);
  assert.equal(mayRenderOnboardingWizard({ loading: true, hasSession: true }), true);
});
