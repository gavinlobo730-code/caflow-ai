// Onboarding reauthentication-nonce tests — run with:
//   node --experimental-strip-types --test lib/auth/reauth.test.ts
//
// Regression guard for the "OTP verification fails with the correct code" bug.
// reauth.ts has only a type-import, so it strips to dependency-free JS.
import test from "node:test";
import assert from "node:assert/strict";
import { setPasswordWithReauthNonce, isInvalidNonceError, type ReauthCapableAuth } from "./reauth.ts";

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
