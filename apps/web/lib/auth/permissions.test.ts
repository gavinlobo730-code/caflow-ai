// Batch 7 permission tests — run with:
//   node --experimental-strip-types --test lib/auth/permissions.test.ts
// permissions.ts has only a type-import, so it strips to dependency-free JS.
import test from "node:test";
import assert from "node:assert/strict";
import { canAccessWorkspace, canAccessHref, isPartnerOnlyAllowed } from "./permissions.ts";

const STAFF_ROLES = ["Partner", "Manager", "Article", "Staff"] as const;

test("Practice workspace is Partner-only (G1)", () => {
  assert.equal(canAccessWorkspace("practice", "Partner"), true);
  assert.equal(canAccessWorkspace("practice", "Manager"), false);
  assert.equal(canAccessWorkspace("practice", "Article"), false);
  assert.equal(canAccessWorkspace("practice", "Staff"), false);
});

test("Knowledge workspace is visible to all staff roles", () => {
  for (const r of STAFF_ROLES) assert.equal(canAccessWorkspace("knowledge", r), true);
});

test("/practice href hidden from Manager and staff, allowed for Partner", () => {
  assert.equal(canAccessHref("/practice", "Partner"), true);
  assert.equal(canAccessHref("/practice", "Manager"), false);
  assert.equal(canAccessHref("/practice", "Article"), false);
  assert.equal(canAccessHref("/practice", "Staff"), false);
});

test("Legacy /billing unchanged: Partner + Manager visible, staff hidden", () => {
  assert.equal(canAccessHref("/billing", "Partner"), true);
  assert.equal(canAccessHref("/billing", "Manager"), true);   // unchanged (no regression)
  assert.equal(canAccessHref("/billing", "Article"), false);
  assert.equal(canAccessHref("/billing", "Staff"), false);
});

test("isPartnerOnlyAllowed only true for Partner", () => {
  assert.equal(isPartnerOnlyAllowed("Partner"), true);
  assert.equal(isPartnerOnlyAllowed("Manager"), false);
  assert.equal(isPartnerOnlyAllowed(null), true); // null defaults to Partner (existing convention)
});

test("existing workspaces still gated as before", () => {
  assert.equal(canAccessWorkspace("deadlines", "Article"), false); // unchanged
  assert.equal(canAccessWorkspace("clients", "Staff"), true);
  assert.equal(canAccessWorkspace("knowledge", "Manager"), true);
});
