// Regression tests for public-route classification — run with:
//   node --experimental-strip-types --test lib/auth/public-paths.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { isPublicPath, PUBLIC_PREFIXES } from "./public-paths.ts";

test("/sign is in PUBLIC_PREFIXES", () => {
  assert.ok(PUBLIC_PREFIXES.includes("/sign"), "/sign must be in PUBLIC_PREFIXES");
});

test("/sign and /sign/ are public paths (engagement-letter signing page)", () => {
  // usePathname() returns /sign or /sign/ (trailingSlash: true in next.config.mjs)
  assert.equal(isPublicPath("/sign"), true);
  assert.equal(isPublicPath("/sign/"), true);
});

test("/sign does not accidentally expose /signout or other sub-paths", () => {
  // isPublicPath matches exact prefix OR prefix+"/" only — not any string starting with /sign
  assert.equal(isPublicPath("/signout"), false);
  assert.equal(isPublicPath("/signnot"), false);
});

test("pre-existing public paths still resolve correctly (no regression)", () => {
  assert.equal(isPublicPath("/login"), true);
  assert.equal(isPublicPath("/login/"), true);
  assert.equal(isPublicPath("/signup"), true);
  assert.equal(isPublicPath("/onboarding"), true);
  assert.equal(isPublicPath("/onboarding/step-2"), true);
  assert.equal(isPublicPath("/auth"), true);
  assert.equal(isPublicPath("/auth/callback"), true);
  assert.equal(isPublicPath("/portal"), true);
  assert.equal(isPublicPath("/portal/dashboard"), true);
  assert.equal(isPublicPath("/platform"), true);
  assert.equal(isPublicPath("/platform/admin"), true);
});

test("protected routes are NOT public (auth guard must still block these)", () => {
  assert.equal(isPublicPath("/"), false);
  assert.equal(isPublicPath("/clients"), false);
  assert.equal(isPublicPath("/leads"), false);
  assert.equal(isPublicPath("/tasks"), false);
  assert.equal(isPublicPath("/invoices"), false);
  assert.equal(isPublicPath("/settings"), false);
  assert.equal(isPublicPath("/ai-assistant"), false);
  assert.equal(isPublicPath("/billing"), false);
  assert.equal(isPublicPath("/practice"), false);
});
