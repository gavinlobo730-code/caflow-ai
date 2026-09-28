// Regression test for the contradictory "Active" badge (sweep-client-misc-06):
// a client with only a pending invite and zero signed-in contacts read
// "Active" in green directly beside "0 active, 1 pending". Run with:
//   node --experimental-strip-types --test lib/portal/badge.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { portalStatusBadge } from "./badge.ts";

test("at least one active contact reads Active", () => {
  assert.deepEqual(portalStatusBadge(1, 0), { label: "Active", tone: "active" });
  assert.deepEqual(portalStatusBadge(2, 3), { label: "Active", tone: "active" });
});

test("BUG sweep-client-misc-06: zero active contacts with a pending invite no longer reads Active", () => {
  const badge = portalStatusBadge(0, 1);
  assert.notEqual(badge.label, "Active");
  assert.notEqual(badge.tone, "active");
  assert.deepEqual(badge, { label: "Invited, not yet signed in", tone: "invited" });
});

test("no contacts at all reads Not enabled", () => {
  assert.deepEqual(portalStatusBadge(0, 0), { label: "Not enabled", tone: "disabled" });
});
