// Permission tests (Module 9.0 / M1 — canonical roles + fail-closed defaults) — run with:
//   node --experimental-strip-types --test lib/auth/permissions.test.ts
// permissions.ts has only a type-import, so it strips to dependency-free JS.
import test from "node:test";
import assert from "node:assert/strict";
import { isPartnerOnlyAllowed, normalizeRole } from "./permissions.ts";
import { areaOffered, mayOpen } from "../access/screenAccess.ts";

// The role lists that hid areas and addresses went on 21-11-2026 (POST-A-543); what they decided is asked of the one table
// now (`lib/access/screenAccess.ts`, tested in `screenAccess.test.ts`). The two facts this file always held are kept, asked
// of that table: My practice is a Partner's alone whatever is ticked, and Knowledge follows its own permission.
const everything = { can: () => true };

test("My practice is Partner-only (G1), whatever permissions the person holds", () => {
  assert.equal(areaOffered("practice", { ...everything, isPartner: true }), true);
  assert.equal(areaOffered("practice", { ...everything, isPartner: false }), false);
  for (const address of ["/practice", "/practice/billing", "/billing", "/accounting/receivables", "/executive-dashboard"]) {
    assert.equal(mayOpen(address, { ...everything, isPartner: false }).allowed, false, address);
    assert.equal(mayOpen(address, { ...everything, isPartner: false }).partnerOnly, true, address);
    assert.equal(mayOpen(address, { ...everything, isPartner: true }).allowed, true, address);
  }
});

test("Knowledge is offered to whoever holds its permission", () => {
  assert.equal(areaOffered("knowledge", { can: (r) => r === "knowledge", isPartner: false }), true);
  assert.equal(areaOffered("knowledge", { can: () => false, isPartner: false }), false);
});

test("isPartnerOnlyAllowed only true for Partner (null now fails closed)", () => {
  assert.equal(isPartnerOnlyAllowed("Partner"), true);
  assert.equal(isPartnerOnlyAllowed("Manager"), false);
  assert.equal(isPartnerOnlyAllowed(null), false); // M1: unknown role no longer defaults to Partner
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

