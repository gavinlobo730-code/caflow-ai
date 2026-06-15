// Permission tests (Module 9.0 / M1 — canonical roles + fail-closed defaults) — run with:
//   node --experimental-strip-types --test lib/auth/permissions.test.ts
// permissions.ts has only a type-import, so it strips to dependency-free JS.
import test from "node:test";
import assert from "node:assert/strict";
import { canAccessWorkspace, canAccessHref, isPartnerOnlyAllowed, normalizeRole } from "./permissions.ts";

const STAFF_ROLES = ["Partner", "Manager", "Executive", "Reviewer"] as const;

test("Practice workspace is Partner-only (G1)", () => {
  assert.equal(canAccessWorkspace("practice", "Partner"), true);
  assert.equal(canAccessWorkspace("practice", "Manager"), false);
  assert.equal(canAccessWorkspace("practice", "Executive"), false);
  assert.equal(canAccessWorkspace("practice", "Reviewer"), false);
  assert.equal(canAccessWorkspace("practice", "Client"), false);
});

test("Knowledge workspace is visible to all staff roles", () => {
  for (const r of STAFF_ROLES) assert.equal(canAccessWorkspace("knowledge", r), true);
});

test("/practice href hidden from Manager and staff, allowed for Partner", () => {
  assert.equal(canAccessHref("/practice", "Partner"), true);
  assert.equal(canAccessHref("/practice", "Manager"), false);
  assert.equal(canAccessHref("/practice", "Executive"), false);
  assert.equal(canAccessHref("/practice", "Reviewer"), false);
});

test("Legacy /billing unchanged: Partner + Manager visible, staff hidden", () => {
  assert.equal(canAccessHref("/billing", "Partner"), true);
  assert.equal(canAccessHref("/billing", "Manager"), true);   // unchanged (no regression)
  assert.equal(canAccessHref("/billing", "Executive"), false);
  assert.equal(canAccessHref("/billing", "Reviewer"), false);
});

test("isPartnerOnlyAllowed only true for Partner (null now fails closed)", () => {
  assert.equal(isPartnerOnlyAllowed("Partner"), true);
  assert.equal(isPartnerOnlyAllowed("Manager"), false);
  assert.equal(isPartnerOnlyAllowed(null), false); // M1: unknown role no longer defaults to Partner
});

test("unknown/null role fails CLOSED to least privilege", () => {
  // null is treated as Reviewer-equivalent: sensitive hrefs hidden, basics allowed.
  assert.equal(canAccessHref("/practice", null), false);
  assert.equal(canAccessHref("/billing", null), false);
  assert.equal(canAccessHref("/tasks", null), true);   // not in STAFF_HIDDEN
  assert.equal(canAccessWorkspace("practice", null), false);
});

test("normalizeRole maps legacy vocabulary to canonical", () => {
  assert.equal(normalizeRole("Article"), "Executive");
  assert.equal(normalizeRole("staff"), "Executive");
  assert.equal(normalizeRole("owner"), "Partner");
  assert.equal(normalizeRole("admin"), "Manager");
  assert.equal(normalizeRole("viewer"), "Reviewer");
  assert.equal(normalizeRole("Partner"), "Partner");
  assert.equal(normalizeRole("wizard"), null);
  assert.equal(normalizeRole(null), null);
});

test("existing workspaces still gated as before", () => {
  assert.equal(canAccessWorkspace("deadlines", "Executive"), false); // unchanged
  assert.equal(canAccessWorkspace("clients", "Reviewer"), true);
  assert.equal(canAccessWorkspace("knowledge", "Manager"), true);
});
