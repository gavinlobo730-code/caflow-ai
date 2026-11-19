import { test } from "node:test";
import assert from "node:assert/strict";
import { LINK_NOT_ACTIVE, canAskAgain, sameAddress, stashFrom, viewFor } from "./signupContinue.ts";

// The server's own sentence for every link that cannot be used (services/signup_link_service.NOT_ACTIVE).
const SERVER_SENTENCE = "This sign-up link is no longer active. It may have expired, been replaced by a newer one, or already been used to create the practice.";

test("the server's one sentence for a dead link is recognised, and an ordinary failure is not", () => {
  assert.match(SERVER_SENTENCE, LINK_NOT_ACTIVE);
  assert.doesNotMatch("Could not check this link just now. Please try again.", LINK_NOT_ACTIVE);
  assert.doesNotMatch("Failed to fetch", LINK_NOT_ACTIVE);
});

test("addresses are compared trimmed and without case, and an empty one is never the same as anything", () => {
  assert.equal(sameAddress(" Ravi@Sharma-Co.IN ", "ravi@sharma-co.in"), true);
  assert.equal(sameAddress("a@x.in", "b@x.in"), false);
  assert.equal(sameAddress("", ""), false);
  assert.equal(sameAddress(null, undefined), false);
  assert.equal(sameAddress("a@x.in", null), false);
});

test("a dead link, an address with no secret in it, a link not yet asked about and a failure to ask each have their own view whoever is signed in", () => {
  for (const signedInAs of [null, "", "someone@else.in", "ravi@sharma-co.in"]) {
    assert.equal(viewFor({ link: "checking", signedInAs, linkAddress: "ravi@sharma-co.in" }), "checking");
    assert.equal(viewFor({ link: "gone", signedInAs, linkAddress: null }), "gone");
    assert.equal(viewFor({ link: "incomplete", signedInAs, linkAddress: null }), "incomplete", "a lost fragment is not an expired link");
    assert.equal(viewFor({ link: "problem", signedInAs, linkAddress: null }), "problem");
  }
});

test("a live link is ready for a signed-out browser and for the link's own address", () => {
  assert.equal(viewFor({ link: "live", signedInAs: null, linkAddress: "ravi@sharma-co.in" }), "ready");
  assert.equal(viewFor({ link: "live", signedInAs: "", linkAddress: "ravi@sharma-co.in" }), "ready");
  assert.equal(viewFor({ link: "live", signedInAs: "RAVI@sharma-co.in", linkAddress: "ravi@sharma-co.in" }), "ready");
});

test("a live link opened in a browser signed in as somebody else asks before it does anything", () => {
  assert.equal(viewFor({ link: "live", signedInAs: "someone@else.in", linkAddress: "ravi@sharma-co.in" }), "other_account");
});

test("the stash is written from what the server says the link was asked for", () => {
  assert.deepEqual(stashFrom({ email: "ravi@sharma-co.in", firm_name: "Sharma & Associates", full_name: "CA Ravi Sharma" }),
    { firmName: "Sharma & Associates", fullName: "CA Ravi Sharma", email: "ravi@sharma-co.in" });
});

test("a new link can be asked for only with the address and both names", () => {
  assert.equal(canAskAgain({ firmName: "F", fullName: "N", email: "a@x.in" }), true);
  for (const missing of ["firmName", "fullName", "email"] as const) {
    const stash: Record<string, string> = { firmName: "F", fullName: "N", email: "a@x.in" };
    delete stash[missing];
    assert.equal(canAskAgain(stash), false, `${missing} missing`);
  }
  assert.equal(canAskAgain({}), false);
});
