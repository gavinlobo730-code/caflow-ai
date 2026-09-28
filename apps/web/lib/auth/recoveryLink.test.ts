// Password-recovery URL marker tests — run with:
//   node --experimental-strip-types --test lib/auth/recoveryLink.test.ts
//
// Regression guard for sweep-auth-and-public-03: /auth/reset-password used to
// show the "set a new password" form for ANY existing Supabase session, not
// only one established by a genuine recovery link. hasRecoveryMarkerInUrl is
// the check that now gates that fallback.
import test from "node:test";
import assert from "node:assert/strict";
import { hasRecoveryMarkerInUrl } from "./recoveryLink.ts";

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
