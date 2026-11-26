// Password-recovery URL marker tests — run with:
//   node --experimental-strip-types --test lib/auth/recoveryLink.test.ts
//
// Regression guard for sweep-auth-and-public-03: /auth/reset-password used to
// show the "set a new password" form for ANY existing Supabase session, not
// only one established by a genuine recovery link. hasRecoveryMarkerInUrl is
// the check that now gates that fallback.
import test from "node:test";
import assert from "node:assert/strict";
import {
  RECOVERY_LINK_MEMORY_MS,
  forgetRecoveryLink,
  hasRecoveryMarkerInUrl,
  recoveryLinkWasOpened,
  rememberRecoveryLink,
  resetRecoveryLinkMemoryForTests,
} from "./recoveryLink.ts";

test("implicit flow: a hash carrying type=recovery is a marker", () => {
  assert.equal(
    hasRecoveryMarkerInUrl({
      hash: "#access_token=abc&expires_in=3600&refresh_token=def&token_type=bearer&type=recovery",
      search: "",
    }),
    true,
  );
});

test("implicit flow: type=recovery as the only hash param is a marker", () => {
  assert.equal(hasRecoveryMarkerInUrl({ hash: "#type=recovery", search: "" }), true);
});

test("PKCE flow: a ?code= query param is a marker", () => {
  assert.equal(hasRecoveryMarkerInUrl({ hash: "", search: "?code=abcdef123456" }), true);
});

test("PKCE flow: code as a later query param is still a marker", () => {
  assert.equal(hasRecoveryMarkerInUrl({ hash: "", search: "?foo=bar&code=abcdef" }), true);
});

// The bug: an ordinary already-signed-in visit to /auth/reset-password (no
// recovery link ever opened) carries neither marker at all.
test("an ordinary visit with no hash and no query is NOT a marker", () => {
  assert.equal(hasRecoveryMarkerInUrl({ hash: "", search: "" }), false);
});

test("an unrelated hash (e.g. a client-side route fragment) is NOT a marker", () => {
  assert.equal(hasRecoveryMarkerInUrl({ hash: "#section-2", search: "" }), false);
});

test("an unrelated query string is NOT a marker", () => {
  assert.equal(hasRecoveryMarkerInUrl({ hash: "", search: "?utm_source=email" }), false);
});

test("a param name that merely contains 'type=recovery' as a substring of another key does not match", () => {
  // e.g. "#sometype=recovery" must not be read as "&type=recovery" or "#type=recovery"
  assert.equal(hasRecoveryMarkerInUrl({ hash: "#sometype=recovery", search: "" }), false);
});

test("a param name that merely contains 'code=' as a substring of another key does not match", () => {
  assert.equal(hasRecoveryMarkerInUrl({ hash: "", search: "?zipcode=12345" }), false);
});

// ── POST-A-510: the marker is remembered from the address as it was BEFORE the sign-in library cleaned it ──────────────────────────────

const AT = 1_000_000;
const IMPLICIT = { pathname: "/auth/reset-password/", hash: "#access_token=a&refresh_token=b&type=recovery", search: "" };
const CLEANED = { pathname: "/auth/reset-password/", hash: "", search: "" };

test("a load of the reset page opened by an implicit-flow link is remembered, and the cleaned address read later does not erase it", () => {
  resetRecoveryLinkMemoryForTests();
  rememberRecoveryLink(IMPLICIT, AT);
  rememberRecoveryLink(CLEANED, AT + 50);            // the library has cleared the hash by now: only the first call counts
  assert.equal(recoveryLinkWasOpened(AT + 3_000), true);
  assert.equal(hasRecoveryMarkerInUrl(CLEANED), false); // the very read the page used to make, which finds nothing
});

test("a PKCE link (?code=) on the reset page is remembered", () => {
  resetRecoveryLinkMemoryForTests();
  rememberRecoveryLink({ pathname: "/auth/reset-password", hash: "", search: "?code=abc123" }, AT);
  assert.equal(recoveryLinkWasOpened(AT + 10), true);
});

test("a marker on any other page is not a recovery link", () => {
  resetRecoveryLinkMemoryForTests();
  rememberRecoveryLink({ pathname: "/auth/callback", hash: "", search: "?code=abc123" }, AT);
  assert.equal(recoveryLinkWasOpened(AT + 10), false);
  resetRecoveryLinkMemoryForTests();
  rememberRecoveryLink({ pathname: "/dashboard", hash: "#access_token=a&type=recovery", search: "" }, AT);
  assert.equal(recoveryLinkWasOpened(AT + 10), false);
});

test("a visit to the reset page with no marker remembers nothing", () => {
  resetRecoveryLinkMemoryForTests();
  rememberRecoveryLink(CLEANED, AT);
  assert.equal(recoveryLinkWasOpened(AT + 10), false);
});

test("what was remembered lapses after a few minutes", () => {
  resetRecoveryLinkMemoryForTests();
  rememberRecoveryLink(IMPLICIT, AT);
  assert.equal(recoveryLinkWasOpened(AT + RECOVERY_LINK_MEMORY_MS), true);
  assert.equal(recoveryLinkWasOpened(AT + RECOVERY_LINK_MEMORY_MS + 1), false);
});

test("a clock that reads earlier than the load is not a recovery link", () => {
  resetRecoveryLinkMemoryForTests();
  rememberRecoveryLink(IMPLICIT, AT);
  assert.equal(recoveryLinkWasOpened(AT - 1), false);
});

test("the page forgets it when it is done, so an ordinary session visiting later is not read as one that came by a link", () => {
  resetRecoveryLinkMemoryForTests();
  rememberRecoveryLink(IMPLICIT, AT);
  assert.equal(recoveryLinkWasOpened(AT + 1), true);
  forgetRecoveryLink();
  assert.equal(recoveryLinkWasOpened(AT + 2), false);
});

test("asking is a read: a second ask (React runs a state initialiser twice in development) gets the same answer", () => {
  resetRecoveryLinkMemoryForTests();
  rememberRecoveryLink(IMPLICIT, AT);
  assert.equal(recoveryLinkWasOpened(AT + 1), true);
  assert.equal(recoveryLinkWasOpened(AT + 2), true);
});
