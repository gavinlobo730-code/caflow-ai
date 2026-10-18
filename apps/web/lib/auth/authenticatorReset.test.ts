// The request body for a lost authenticator — run with:
//   node --experimental-strip-types --test lib/auth/authenticatorReset.test.ts
//
// The body names a person and gives a reason and NOTHING the server should believe about who the person is: the name,
// the e-mail and the summary a Partner reads are written by the server from the member's own row.
import test from "node:test";
import assert from "node:assert/strict";
import { AUTHENTICATOR_RESET, askedWithText, resetRequestPayload } from "./authenticatorReset.ts";

test("the request type is the one the approvals engine registers", () => {
  assert.equal(AUTHENTICATOR_RESET, "mfa_reset");
});

test("a person's own authenticator is asked for with a flag, trimmed", () => {
  assert.deepEqual(resetRequestPayload({ kind: "self" }, "  New phone  "), { reason: "New phone", self: true });
});

test("a member's is asked for by id and sends no name or e-mail for the server to believe", () => {
  const body = resetRequestPayload({ kind: "member", userId: "u-9" }, "Dropped it");
  assert.deepEqual(body, { reason: "Dropped it", user_id: "u-9" });
  assert.deepEqual(Object.keys(body).sort(), ["reason", "user_id"]);
});

test("negative control: a self request carries no user id to get wrong", () => {
  assert.equal("user_id" in resetRequestPayload({ kind: "self" }, "x"), false);
});

test("the line under a request says how the asker signed in, and an unknown is not either answer", () => {
  assert.equal(askedWithText("aal2"), "Asked after signing in with a second factor.");
  assert.equal(askedWithText("aal1"), "Asked with a password only.");
  for (const unknown of [undefined, null, "", "aal3", 2]) {
    assert.equal(askedWithText(unknown), "How the asker signed in was not recorded.");
  }
});
