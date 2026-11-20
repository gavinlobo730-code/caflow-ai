// Run with: node --experimental-strip-types --test lib/auth/assuranceCarry.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { mayKeepAssurance, type KnownAssurance } from "./assuranceCarry.ts";

const known = (over: Partial<KnownAssurance> = {}): KnownAssurance => ({ userId: "u-1", accessToken: "tok-A", pending: false, ...over });
const keep = (event: string, k: KnownAssurance, nextUserId: string | null = "u-1", nextAccessToken: string | null = "tok-A") =>
  mayKeepAssurance({ event, known: k, nextUserId, nextAccessToken });

test("an announcement that cannot have changed which session this is keeps what is known", () => {
  assert.equal(keep("TOKEN_REFRESHED", known(), "u-1", "tok-B"), true, "an hourly refresh (a new token, the same session)");
  assert.equal(keep("USER_UPDATED", known(), "u-1", "tok-B"), true, "a password or profile saved");
  assert.equal(keep("SIGNED_IN", known(), "u-1", "tok-A"), true, "the library announcing the session it loaded from storage again (a tab regaining focus)");
});

test("a value that says a challenge is owed is kept as well: unresolved is the only thing that is never kept", () => {
  assert.equal(keep("TOKEN_REFRESHED", known({ pending: true })), true);
});

test("a SIGNED_IN with another token is a new sign-in and is read afresh", () => {
  assert.equal(keep("SIGNED_IN", known(), "u-1", "tok-B"), false);
});

test("another person is never the same session, whatever the event", () => {
  for (const e of ["TOKEN_REFRESHED", "USER_UPDATED", "SIGNED_IN"]) assert.equal(keep(e, known(), "u-2", "tok-A"), false, e);
});

test("the announcements that change the session are read afresh", () => {
  for (const e of ["SIGNED_OUT", "PASSWORD_RECOVERY", "INITIAL_SESSION", "SOMETHING_NEW", ""]) {
    assert.equal(keep(e, known()), false, e);
  }
});

// POST-A-515 (c): a verified code raised the level of a session that already owed nothing, and rebuilt the page under the person
// (Settings > Security proving a password or checking a code; the platform page stepping up). It keeps what let the person in, and only that.
test("a verified code keeps the value of a session that is already admitted, whatever its new token is", () => {
  assert.equal(keep("MFA_CHALLENGE_VERIFIED", known({ pending: false }), "u-1", "tok-B"), true, "the level is in the new token");
  assert.equal(keep("MFA_CHALLENGE_VERIFIED", known({ pending: false }), "u-1", "tok-A"), true);
});

test("a verified code never keeps a challenge that was owed, a value not yet read, or another person's", () => {
  assert.equal(keep("MFA_CHALLENGE_VERIFIED", known({ pending: true }), "u-1", "tok-B"), false, "the code is what ends the challenge: read afresh");
  assert.equal(keep("MFA_CHALLENGE_VERIFIED", known({ pending: true }), "u-1", "tok-A"), false, "and the answer does not depend on the token being a new one");
  assert.equal(keep("MFA_CHALLENGE_VERIFIED", known({ pending: null }), "u-1", "tok-B"), false, "nothing read yet: nothing to keep");
  assert.equal(keep("MFA_CHALLENGE_VERIFIED", known({ pending: false }), "u-2", "tok-B"), false, "another person");
  assert.equal(keep("MFA_CHALLENGE_VERIFIED", known({ pending: false, userId: null }), "u-1", "tok-B"), false);
  assert.equal(keep("MFA_CHALLENGE_VERIFIED", known({ pending: false }), "u-1", null), false, "no session in the announcement");
  assert.equal(keep("MFA_CHALLENGE_VERIFIED", known({ pending: false }), null, "tok-B"), false);
});

test("nothing is kept while nothing is yet known, with no person, or with no session in the announcement", () => {
  assert.equal(keep("TOKEN_REFRESHED", known({ pending: null })), false);
  assert.equal(keep("TOKEN_REFRESHED", known({ userId: null })), false);
  assert.equal(keep("TOKEN_REFRESHED", known(), null, "tok-A"), false);
  assert.equal(keep("TOKEN_REFRESHED", known(), "u-1", null), false);
  assert.equal(keep("SIGNED_IN", known({ accessToken: null }), "u-1", "tok-A"), false, "a SIGNED_IN with no token to compare is not the same session");
});
