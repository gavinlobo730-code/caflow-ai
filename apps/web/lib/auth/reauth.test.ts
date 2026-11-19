// Onboarding reauthentication-nonce tests — run with:
//   node --experimental-strip-types --test lib/auth/reauth.test.ts
//
// Regression guard for the "OTP verification fails with the correct code" bug.
// reauth.ts has only a type-import, so it strips to dependency-free JS.
import test from "node:test";
import assert from "node:assert/strict";
import {
  setPasswordWithReauthNonce,
  isInvalidNonceError,
  isSessionMissingError,
  isSamePasswordError,
  SESSION_EXPIRED_MESSAGE,
  type ReauthCapableAuth,
} from "./reauth.ts";

/** A mock that records every auth method call so we can assert the call shape. */
function makeMockAuth(result: { error: unknown } = { error: null }) {
  const calls: { method: string; args: unknown[] }[] = [];
  const auth = {
    updateUser(attributes: { password?: string; nonce?: string }) {
      calls.push({ method: "updateUser", args: [attributes] });
      return Promise.resolve({ data: { user: null }, ...result } as never);
    },
    // The bug used this. It must NEVER be called for a reauthentication nonce.
    verifyOtp(params: unknown) {
      calls.push({ method: "verifyOtp", args: [params] });
      return Promise.resolve({ data: {}, error: null } as never);
    },
  };
  return { auth: auth as unknown as ReauthCapableAuth, calls };
}

test("setPasswordWithReauthNonce calls updateUser with { password, nonce }", async () => {
  const { auth, calls } = makeMockAuth();
  await setPasswordWithReauthNonce(auth, "super-secret-pw", "70842686");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, "updateUser");
  assert.deepEqual(calls[0].args[0], { password: "super-secret-pw", nonce: "70842686" });
});

test("it NEVER calls verifyOtp (the root-cause bug)", async () => {
  const { auth, calls } = makeMockAuth();
  await setPasswordWithReauthNonce(auth, "pw", "12345678");
  assert.equal(calls.some((c) => c.method === "verifyOtp"), false);
});

test("the 8-digit code is sent verbatim — no truncation to 6, no slice/parseInt", async () => {
  const { auth, calls } = makeMockAuth();
  await setPasswordWithReauthNonce(auth, "pw", "70842686"); // exact code from the bug report
  const sent = (calls[0].args[0] as { nonce: string }).nonce;
  assert.equal(sent, "70842686");
  assert.equal(sent.length, 8);
});

test("the nonce is trimmed (paste whitespace tolerated) but not otherwise altered", async () => {
  const { auth, calls } = makeMockAuth();
  await setPasswordWithReauthNonce(auth, "pw", "  70842686  ");
  assert.equal((calls[0].args[0] as { nonce: string }).nonce, "70842686");
});

test("the underlying updateUser result is returned to the caller", async () => {
  const err = { message: "Token has expired or is invalid", status: 403, code: "otp_expired" };
  const { auth } = makeMockAuth({ error: err });
  const res = await setPasswordWithReauthNonce(auth, "pw", "00000000");
  assert.equal((res as { error: unknown }).error, err);
});

test("isInvalidNonceError detects expired/invalid nonce messages", () => {
  assert.equal(isInvalidNonceError({ message: "Token has expired or is invalid" }), true);
  assert.equal(isInvalidNonceError({ message: "Invalid nonce" }), true);
  assert.equal(isInvalidNonceError({ message: "otp_expired" }), true);
  assert.equal(isInvalidNonceError({ message: "Network unreachable" }), false);
  assert.equal(isInvalidNonceError(null), false);
});

// sweep-auth-and-public-04: with no session at all, updateUser() rejects with
// the SDK's raw "Auth session missing!" and that string used to reach the CA
// verbatim.
test("isSessionMissingError detects the SDK's no-session error", () => {
  assert.equal(isSessionMissingError({ message: "Auth session missing!" }), true);
  assert.equal(isSessionMissingError({ message: "auth session missing" }), true);
  assert.equal(isSessionMissingError({ message: "Invalid nonce" }), false);
  assert.equal(isSessionMissingError({ message: "Network unreachable" }), false);
  assert.equal(isSessionMissingError(null), false);
});

test("SESSION_EXPIRED_MESSAGE names the reason and both ways forward", () => {
  assert.match(SESSION_EXPIRED_MESSAGE, /expired|not signed in/i);
  assert.doesNotMatch(SESSION_EXPIRED_MESSAGE, /auth session missing/i);
});

test("a same-password refusal, by code or by message, is recognised and nothing else is (POST-A-478)", () => {
  // As the live sign-in log recorded it on 18-11-2026: 422, code same_password.
  assert.equal(isSamePasswordError({ code: "same_password", message: "New password should be different from the old password." }), true);
  // A server that sends no code.
  assert.equal(isSamePasswordError({ message: "New password should be different from the old password." }), true);
  assert.equal(isSamePasswordError({ code: "weak_password", message: "Password should be at least 10 characters." }), false);
  assert.equal(isSamePasswordError({ message: "Auth session missing!" }), false);
  assert.equal(isSamePasswordError(null), false);
  assert.equal(isSamePasswordError(undefined), false);
  assert.equal(isSamePasswordError({}), false);
});

// POST-A-512: Settings > Security knows the current password and must send it with the change; an emailed-link screen has none.
test("setPasswordWithReauthNonce sends the current password when the screen has one, and nothing extra when it has not", async () => {
  const withCurrent = makeMockAuth();
  await setPasswordWithReauthNonce(withCurrent.auth as unknown as ReauthCapableAuth, "New#Pass1", " 123456 ", "Old#Pass1");
  assert.deepEqual(withCurrent.calls[0].args[0], { password: "New#Pass1", nonce: "123456", current_password: "Old#Pass1" });

  const without = makeMockAuth();
  await setPasswordWithReauthNonce(without.auth as unknown as ReauthCapableAuth, "New#Pass1", "123456");
  assert.deepEqual(without.calls[0].args[0], { password: "New#Pass1", nonce: "123456" }, "no current_password key for a screen that has none");
});
