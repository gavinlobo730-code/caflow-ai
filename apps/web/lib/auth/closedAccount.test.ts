// node --experimental-strip-types --test lib/auth/closedAccount.test.ts
//
// POST-A-482. The API answers a closed account's requests with these refusals (core/auth.py); the browser signs the
// person out on exactly these and on nothing else.
import test from "node:test";
import assert from "node:assert/strict";
import { closedAccountPath, closedAccountReason, closedAccountWords, isAlreadyOutside } from "./closedAccount.ts";

test("each refusal the API writes for a closed account is recognised", () => {
  assert.equal(closedAccountReason(403, "Firm suspended"), "firm-suspended");
  assert.equal(closedAccountReason(403, "Firm unavailable"), "firm-unavailable");
  assert.equal(closedAccountReason(403, "Account disabled. Contact your firm administrator."), "person-disabled");
  assert.equal(closedAccountReason(401, "Session revoked. Please sign in again."), "signed-out");
});

test("no other refusal signs anybody out", () => {
  assert.equal(closedAccountReason(403, "Multi-factor authentication required for this action."), null);
  assert.equal(closedAccountReason(403, "You do not have permission to do that."), null);
  assert.equal(closedAccountReason(403, "Firm suspended"), "firm-suspended");
  assert.equal(closedAccountReason(404, "Firm suspended"), null);
  assert.equal(closedAccountReason(500, "Account disabled."), null);
  assert.equal(closedAccountReason(401, "Token expired"), null);
  assert.equal(closedAccountReason(401, "Your session could not be verified. Please sign in again."), null);
  assert.equal(closedAccountReason(401, "Missing or invalid Authorization header"), null);
  assert.equal(closedAccountReason(403, null), null);
  assert.equal(closedAccountReason(403, undefined), null);
  assert.equal(closedAccountReason(403, "Your firm suspended nothing"), null);
});

test("every reason has its own words, which blame nobody and name no address", () => {
  const seen = new Set<string>();
  for (const r of ["firm-suspended", "firm-unavailable", "person-disabled", "signed-out"]) {
    const w = closedAccountWords(r);
    assert.ok(w.heading.length > 0 && w.body.length > 0);
    assert.doesNotMatch(w.heading + " " + w.body, /@|https?:|\.com/i);
    seen.add(w.heading);
  }
  assert.equal(seen.size, 4);
  assert.match(closedAccountWords("person-disabled").body, /administrator/);
  assert.match(closedAccountWords("firm-suspended").body, /signed out/);
});

test("a person signed out for being idle is told so, with the limit and how to continue", () => {
  const w = closedAccountWords("idle");
  assert.equal(w.heading, "You were signed out for your security");
  assert.match(w.body, /30 minutes/);
  assert.match(w.body, /Sign in again/);
  assert.equal(closedAccountPath("idle"), "/auth/account-closed/?why=idle");
});

test("an unknown or missing reason still says the person was signed out, and how to continue", () => {
  for (const r of [null, undefined, "", "nonsense"]) {
    const w = closedAccountWords(r);
    assert.equal(w.heading, "You have been signed out");
    assert.match(w.body, /Sign in again/);
  }
});

test("the page path carries the reason, and the page and the sign-in are not sent there again", () => {
  assert.equal(closedAccountPath("firm-suspended"), "/auth/account-closed/?why=firm-suspended");
  assert.equal(isAlreadyOutside("/auth/account-closed/"), true);
  assert.equal(isAlreadyOutside("/login"), true);
  assert.equal(isAlreadyOutside("/login/forgot-password"), true);
  assert.equal(isAlreadyOutside("/clients/abc/overview/"), false);
  assert.equal(isAlreadyOutside("/auth/reset-password"), false);
});
