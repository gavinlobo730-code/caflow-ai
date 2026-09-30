// node --experimental-strip-types --test lib/auth/mfaRefusal.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  MFA_REQUIRED_DETAIL,
  MFA_SETUP_MESSAGE,
  explainMfaRefusal,
  isMfaRefusal,
} from "./mfaRefusal.ts";

test("the backend's MFA refusal becomes the setup sentence", () => {
  assert.equal(explainMfaRefusal("Multi-factor authentication required for this action."), MFA_SETUP_MESSAGE);
  assert.equal(explainMfaRefusal(`  ${MFA_REQUIRED_DETAIL} `), MFA_SETUP_MESSAGE);
});

test("the setup sentence names where to go", () => {
  assert.match(MFA_SETUP_MESSAGE, /authenticator app/);
  assert.match(MFA_SETUP_MESSAGE, /Settings → Security/);
});

test("every other refusal passes through unchanged", () => {
  for (const m of [
    "Insufficient permissions",
    "GSTR-3B covering this date was filed on 18 Jul 2026.",
    // The platform-admin guard is a different guard with its own sentence.
    "Multi-factor authentication is required for this action. Enrol at Settings → Security.",
  ]) {
    assert.equal(explainMfaRefusal(m), m);
    assert.equal(isMfaRefusal(m), false, m);
  }
});

test("the refusal is recognised before and after translation", () => {
  assert.equal(isMfaRefusal(MFA_REQUIRED_DETAIL), true);
  assert.equal(isMfaRefusal(MFA_SETUP_MESSAGE), true);
  assert.equal(isMfaRefusal(undefined), false);
  assert.equal(isMfaRefusal(null), false);
});
