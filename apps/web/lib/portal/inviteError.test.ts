// Regression test for the raw-Supabase-error text shown on a rate-limited
// portal invite (sweep-client-misc-05 / manual-03). Run with:
//   node --experimental-strip-types --test lib/portal/inviteError.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { portalInviteEmailFailureMessage } from "./inviteError.ts";

test("names that the invite was already created, not only that the send failed", () => {
  const msg = portalInviteEmailFailureMessage("email rate limit exceeded");
  assert.match(msg, /invite was created/i);
  assert.match(msg, /email rate limit exceeded/);
});

test("tells the CA what to do next", () => {
  const msg = portalInviteEmailFailureMessage("email rate limit exceeded");
  assert.match(msg, /Invite Another Contact/);
});

test("carries whatever the underlying provider message was, verbatim", () => {
  const msg = portalInviteEmailFailureMessage("some other transient error");
  assert.match(msg, /some other transient error/);
});
