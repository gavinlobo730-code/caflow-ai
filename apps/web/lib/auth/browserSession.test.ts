// node --experimental-strip-types --test lib/auth/browserSession.test.ts
//
// POST-A-483: what a page that starts does about a session it finds stored.
import test from "node:test";
import assert from "node:assert/strict";
import { HEARTBEAT_FRESH_MS, KEEP_DAYS, heartbeatAge, keepFlag, keepIsActive, startDecision, urlCarriesASignIn } from "./browserSession.ts";

const NOW = 1_800_000_000_000;
const none = { keepActive: false, hasMarker: false, otherTabAnswered: false, heartbeatAgeMs: null as number | null };

test("a browser reopened with nothing to say it was open signs the person out", () => {
  assert.equal(startDecision({ ...none }), "end");
  assert.equal(startDecision({ ...none, heartbeatAgeMs: HEARTBEAT_FRESH_MS + 1 }), "end");
  assert.equal(startDecision({ ...none, heartbeatAgeMs: 6 * 60 * 60 * 1000 }), "end");
});

test("any one sign that this is the same browser session keeps the person in", () => {
  assert.equal(startDecision({ ...none, hasMarker: true }), "continue");
  assert.equal(startDecision({ ...none, otherTabAnswered: true }), "continue");
  assert.equal(startDecision({ ...none, keepActive: true }), "continue");
  assert.equal(startDecision({ ...none, heartbeatAgeMs: 5_000 }), "continue");
  assert.equal(startDecision({ ...none, heartbeatAgeMs: HEARTBEAT_FRESH_MS }), "continue");
});

test("a heartbeat a little in the future is clock skew, one far in the future is nothing", () => {
  assert.equal(startDecision({ ...none, heartbeatAgeMs: -10_000 }), "continue");
  assert.equal(startDecision({ ...none, heartbeatAgeMs: -3_600_000 }), "end");
});

test("a lock held by another tab, or an address that carries a sign-in, keeps the person in", () => {
  assert.equal(startDecision({ ...none, otherTabHoldsLock: true }), "continue");
  assert.equal(startDecision({ ...none, freshSignIn: true }), "continue");
});

test("the keep flag lasts fourteen days, for the person who ticked it, and not a moment longer", () => {
  assert.equal(KEEP_DAYS, 14);
  const raw = keepFlag(NOW, "u1");
  assert.equal(keepIsActive(raw, NOW, "u1"), true);
  assert.equal(keepIsActive(raw, NOW + 13 * 86_400_000, "u1"), true);
  assert.equal(keepIsActive(raw, NOW + 15 * 86_400_000, "u1"), false);
  // edited to last for ever: refused
  assert.equal(keepIsActive(JSON.stringify({ until: NOW + 400 * 86_400_000, uid: "u1" }), NOW, "u1"), false);
});

test("somebody else's tickbox is not the next person's: the flag names who ticked it", () => {
  const raw = keepFlag(NOW, "u1");
  assert.equal(keepIsActive(raw, NOW, "u2"), false);
  assert.equal(keepIsActive(raw, NOW, null), false);
  assert.equal(keepIsActive(raw, NOW, undefined), false);
  // a flag with no owner (written before this rule) keeps nobody
  assert.equal(keepIsActive(JSON.stringify({ until: NOW + 1000 }), NOW, "u1"), false);
});

test("a missing, unreadable or odd keep flag is no flag", () => {
  for (const raw of [null, undefined, "", "not json", "null", "[]", "5", '{"until":"soon"}', '{"until":null}', '{"until":NaN}', JSON.stringify({ until: NOW - 1, uid: "u1" })]) {
    assert.equal(keepIsActive(raw as string | null | undefined, NOW, "u1"), false, String(raw));
  }
});

test("an address that carries a sign-in is told from an ordinary one", () => {
  assert.equal(urlCarriesASignIn("#access_token=abc&refresh_token=def&type=magiclink", ""), true);
  assert.equal(urlCarriesASignIn("#access_token=abc&type=recovery", ""), true);
  assert.equal(urlCarriesASignIn("", "?code=1234"), true);
  assert.equal(urlCarriesASignIn("", "?token_hash=zz&type=invite"), true);
  assert.equal(urlCarriesASignIn("", ""), false);
  assert.equal(urlCarriesASignIn("#section", "?tab=bank"), false);
  assert.equal(urlCarriesASignIn("", "?encoded=1"), false);
});

test("the heartbeat's age is read from what was stored, and an unreadable value is no heartbeat", () => {
  assert.equal(heartbeatAge(String(NOW - 4_000), NOW), 4_000);
  assert.equal(heartbeatAge(null, NOW), null);
  assert.equal(heartbeatAge("", NOW), null);
  assert.equal(heartbeatAge("abc", NOW), null);
});
