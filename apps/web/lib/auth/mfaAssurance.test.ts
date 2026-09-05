// MFA assurance resolution — run with:
//   node --experimental-strip-types --test lib/auth/mfaAssurance.test.ts
//
// WHAT WAS WRONG
//
//   Production, 2026-09-05: both Partners hold a VERIFIED TOTP factor enrolled
//   2026-08-15, and every session created since is aal1 with a single `password`
//   AMR claim. Not one `totp` after enrolment day — while 162 browser writes
//   reached audit_log on 3 September from those sessions. MFA was enrolled and
//   never asked for.
//
//   The old resolution failed open in three places at once: `catch { return
//   false }`, a null `data` treated the same way, and a caller that rendered the
//   app while the answer was still unresolved. It also asked only
//   `getAuthenticatorAssuranceLevel()`, whose `nextLevel` is derived from the
//   cached user object — so a restored session whose user carries no `factors`
//   reports "nothing owed" for an account that has one.
//
// WHAT THESE TESTS PIN
//
//   That "I could not tell" never resolves to "satisfied", and that a verified
//   factor is believed even when the AAL call disagrees. The direction is the
//   whole point: every one of these is a test that the gate does NOT open.
//
// NEGATIVE CONTROLS — each applied, then reverted:
//
//   | control                                          | tests that fail |
//   |--------------------------------------------------|-----------------|
//   | catch errors as "satisfied" (the old behaviour)  | 6               |
//   | ask only the AAL call, not listFactors           | 3               |
//   | let a persistent failure resolve to satisfied    | 1               |
//   | treat unresolved as `false` in toMfaPending      | 1               |
import test from "node:test";
import assert from "node:assert/strict";
import {
  resolveAssurance,
  resolveAssuranceOnce,
  toMfaPending,
  type AssuranceCapableAuth,
} from "./mfaAssurance.ts";

const noSleep = async () => {};

function auth(
  levels: unknown,
  factors: unknown,
): AssuranceCapableAuth {
  return {
    getAuthenticatorAssuranceLevel: async () => {
      if (levels instanceof Error) throw levels;
      return { data: levels } as never;
    },
    listFactors: async () => {
      if (factors instanceof Error) throw factors;
      return { data: factors } as never;
    },
  };
}

const VERIFIED = { totp: [{ status: "verified" }] };
const UNVERIFIED = { totp: [{ status: "unverified" }] };
const NO_FACTORS = { totp: [] };

// ── the state production is actually in ──────────────────────────────────────

test("a verified factor on an aal1 session owes a challenge", async () => {
  const got = await resolveAssuranceOnce(
    auth({ currentLevel: "aal1", nextLevel: "aal2" }, VERIFIED));
  assert.equal(got, "pending");
});

test("a verified factor is believed even when nextLevel says aal1", async () => {
  // The exact shape a session restored from storage produces: the cached user
  // carries no factors, so the AAL call reports nothing owed — for an account
  // that has a verified factor sitting in the database. This is the half the
  // old code never asked, and the one that matches production.
  const got = await resolveAssuranceOnce(
    auth({ currentLevel: "aal1", nextLevel: "aal1" }, VERIFIED));
  assert.equal(got, "pending", "the cached user object was believed over the factor list");
});

test("an aal2 session owes nothing", async () => {
  const got = await resolveAssuranceOnce(
    auth({ currentLevel: "aal2", nextLevel: "aal2" }, VERIFIED));
  assert.equal(got, "satisfied");
});

test("an account with no factor at all owes nothing", async () => {
  const got = await resolveAssuranceOnce(
    auth({ currentLevel: "aal1", nextLevel: "aal1" }, NO_FACTORS));
  assert.equal(got, "satisfied");
});

test("an unverified factor is not a factor", async () => {
  const got = await resolveAssuranceOnce(
    auth({ currentLevel: "aal1", nextLevel: "aal1" }, UNVERIFIED));
  assert.equal(got, "satisfied");
});

// ── "I could not tell" is never "satisfied" ──────────────────────────────────

test("both oracles failing resolves to unresolved, not satisfied", async () => {
  const got = await resolveAssuranceOnce(
    auth(new Error("network"), new Error("network")));
  assert.equal(got, "unresolved");
});

test("a null payload is not permission", async () => {
  const got = await resolveAssuranceOnce(auth(null, null));
  assert.equal(got, "unresolved");
});

test("the factor list failing does not let an unknown account through", async () => {
  const got = await resolveAssuranceOnce(
    auth(new Error("network"), NO_FACTORS));
  assert.notEqual(got, "unresolved");   // the factor list answered: no factor
  assert.equal(got, "satisfied");
});

test("the AAL call failing still finds the factor", async () => {
  const got = await resolveAssuranceOnce(auth(new Error("network"), VERIFIED));
  assert.equal(got, "pending");
});

// ── the retry, and where it lands ────────────────────────────────────────────

test("a transient failure is retried and then answered", async () => {
  // BOTH oracles must fail for the first attempt to be unresolved — if
  // listFactors answers, one call is enough and no retry is needed or wanted.
  let calls = 0;
  const flaky: AssuranceCapableAuth = {
    getAuthenticatorAssuranceLevel: async () => {
      calls++;
      throw new Error("blip");
    },
    listFactors: async () => {
      if (calls === 1) throw new Error("blip");
      return { data: VERIFIED } as never;
    },
  };
  const got = await resolveAssurance(flaky, { attempts: 3, sleep: noSleep });
  assert.equal(got, "pending");
  assert.ok(calls > 1, "it did not retry");
});

test("the cached user object alone cannot say 'satisfied'", async () => {
  // nextLevel === "aal1" with no answer from listFactors is precisely the state
  // a restored session reports for an account that HAS a verified factor. It
  // must resolve to unresolved (and so, after retries, to pending) — never to
  // "nothing owed".
  const got = await resolveAssuranceOnce(
    auth({ currentLevel: "aal1", nextLevel: "aal1" }, null));
  assert.equal(got, "unresolved");
});

test("a persistent failure fails CLOSED, holding the user at the challenge", async () => {
  // Being wrongly held is recoverable by signing out and in. Being wrongly let
  // through is a silent authentication bypass — which is the bug being fixed.
  const got = await resolveAssurance(
    auth(new Error("down"), new Error("down")), { attempts: 3, sleep: noSleep });
  assert.equal(got, "pending");
});

test("the retry is bounded", async () => {
  let calls = 0;
  const dead: AssuranceCapableAuth = {
    getAuthenticatorAssuranceLevel: async () => { calls++; throw new Error("down"); },
    listFactors: async () => { throw new Error("down"); },
  };
  await resolveAssurance(dead, { attempts: 3, sleep: noSleep });
  assert.equal(calls, 3, "the retry is not bounded at `attempts`");
});

// ── the mapping the caller uses ──────────────────────────────────────────────

test("unresolved maps to null, never to false", async () => {
  assert.equal(toMfaPending("pending"), true);
  assert.equal(toMfaPending("satisfied"), false);
  assert.equal(toMfaPending("unresolved"), null,
    "unresolved was flattened to 'nothing owed'");
});
