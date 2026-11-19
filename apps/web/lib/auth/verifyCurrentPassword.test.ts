// node --experimental-strip-types --test lib/auth/verifyCurrentPassword.test.ts
//
// The current-password proof of Settings > Security (POST-A-512): made on a throwaway client, answered in the card's own words, and
// the throwaway session signed out whatever the answer was.
import test from "node:test";
import assert from "node:assert/strict";
import { verifyCurrentPassword, CURRENT_PASSWORD_WRONG, type ProofClient } from "./verifyCurrentPassword.ts";

function fakeClient(signIn: () => Promise<{ error: unknown }>, signOut?: () => Promise<unknown>) {
  const calls: string[] = [];
  const client: ProofClient = {
    auth: {
      async signInWithPassword(c) { calls.push(`signIn:${c.email}`); return signIn(); },
      async signOut(o) { calls.push(`signOut:${o?.scope ?? "default"}`); return signOut ? signOut() : { error: null }; },
    },
  };
  return { client, calls };
}

test("a right password is accepted, and the throwaway session is signed out on this device only", async () => {
  const { client, calls } = fakeClient(async () => ({ error: null }));
  const r = await verifyCurrentPassword("a@b.in", "Right#Pass1", () => client);
  assert.deepEqual(r, { ok: true });
  assert.deepEqual(calls, ["signIn:a@b.in", "signOut:local"]);
});

test("a wrong password says so in the card's words, not the sign-in screen's 'email or password'", async () => {
  const { client, calls } = fakeClient(async () => ({ error: { code: "invalid_credentials", message: "Invalid login credentials", status: 400 } }));
  const r = await verifyCurrentPassword("a@b.in", "wrong", () => client);
  assert.deepEqual(r, { ok: false, message: CURRENT_PASSWORD_WRONG });
  assert.equal(CURRENT_PASSWORD_WRONG, "Current password is incorrect.");
  assert.ok(calls.includes("signOut:local"), "the throwaway client is cleaned up after a refusal too");
});

test("a throttle or an unreachable service is NOT reported as a wrong password", async () => {
  const throttled = fakeClient(async () => ({ error: { code: "over_request_rate_limit", message: "rate limit", status: 429 } }));
  const r1 = await verifyCurrentPassword("a@b.in", "x", () => throttled.client);
  assert.equal(r1.ok, false);
  assert.notEqual((r1 as { message: string }).message, CURRENT_PASSWORD_WRONG);
  assert.match((r1 as { message: string }).message, /Too many attempts/);

  const down = fakeClient(async () => { throw Object.assign(new TypeError("Failed to fetch"), {}); });
  const r2 = await verifyCurrentPassword("a@b.in", "x", () => down.client);
  assert.equal(r2.ok, false);
  assert.notEqual((r2 as { message: string }).message, CURRENT_PASSWORD_WRONG);
  assert.match((r2 as { message: string }).message, /could not be reached/);
});

test("a sign-out that fails changes nothing about the answer", async () => {
  const ok = fakeClient(async () => ({ error: null }), async () => { throw new Error("network down"); });
  assert.deepEqual(await verifyCurrentPassword("a@b.in", "Right#Pass1", () => ok.client), { ok: true });
  const bad = fakeClient(async () => ({ error: { code: "invalid_credentials" } }), async () => { throw new Error("network down"); });
  assert.deepEqual(await verifyCurrentPassword("a@b.in", "wrong", () => bad.client), { ok: false, message: CURRENT_PASSWORD_WRONG });
});
