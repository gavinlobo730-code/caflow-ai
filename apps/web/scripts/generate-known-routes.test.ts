// Proves lib/workspace/knownRoutes.generated.ts can't silently drift from
// the app/ route tree, and that matchesKnownRoute() actually catches the bug
// class it exists for (Task 4 of the navigation investigation).
// Run with: node --experimental-strip-types --test scripts/generate-known-routes.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildKnownRoutesFile } from "./generate-known-routes.js";
import { matchesKnownRoute } from "../lib/workspace/routeManifest.ts";
import { KNOWN_ROUTE_SHAPES } from "../lib/workspace/knownRoutes.generated.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_DIR = path.join(__dirname, "..", "app");
const GENERATED_FILE = path.join(__dirname, "..", "lib", "workspace", "knownRoutes.generated.ts");

test("knownRoutes.generated.ts matches what the generator produces from app/ right now", () => {
  const generated = buildKnownRoutesFile(APP_DIR);
  const checkedIn = fs.readFileSync(GENERATED_FILE, "utf8");
  assert.equal(
    generated,
    checkedIn,
    "lib/workspace/knownRoutes.generated.ts is stale — re-run " +
      "`npm run generate:known-routes` (or `next build`, which now runs it " +
      "automatically) before committing."
  );
});

test("the root page is included in the real generated manifest, not silently dropped by the walker", () => {
  assert.ok(matchesKnownRoute("/", KNOWN_ROUTE_SHAPES));
});

test("a real static page is known in the real generated manifest", () => {
  assert.ok(matchesKnownRoute("/accounting", KNOWN_ROUTE_SHAPES));
  assert.ok(matchesKnownRoute("/accounting/coa-import/", KNOWN_ROUTE_SHAPES));
});

test("a deleted page within a still-live workspace prefix is rejected", () => {
  // The exact bug this manifest exists to catch: /accounting/chart-of-accounts
  // was retired in R3.3b, but "/accounting" itself is still very much a real,
  // live workspace — a same-prefix-only check would wrongly call this valid.
  assert.ok(!matchesKnownRoute("/accounting/chart-of-accounts", KNOWN_ROUTE_SHAPES));
  assert.ok(!matchesKnownRoute("/accounting/chart-of-accounts/", KNOWN_ROUTE_SHAPES));
});

// The remaining tests exercise matchesKnownRoute's matching algorithm in
// isolation against small hand-built fixtures, independent of the app's
// actual (ever-changing) route list.
const FIXTURE_SHAPES = [[], ["settings"], ["clients", ":id", "sales"], ["clients", ":id"]];

test("root, static, and dynamic shapes all match their real form", () => {
  assert.ok(matchesKnownRoute("/", FIXTURE_SHAPES));
  assert.ok(matchesKnownRoute("/settings", FIXTURE_SHAPES));
  assert.ok(matchesKnownRoute("/settings/", FIXTURE_SHAPES));
  assert.ok(matchesKnownRoute("/clients/any-id/sales", FIXTURE_SHAPES));
  assert.ok(matchesKnownRoute("/clients/any-id/sales/", FIXTURE_SHAPES));
  assert.ok(matchesKnownRoute("/clients/any-id", FIXTURE_SHAPES));
});

test("wrong depth or an unrecognized static segment is rejected", () => {
  assert.ok(!matchesKnownRoute("/clients/some-id/sales/extra-segment", FIXTURE_SHAPES));
  assert.ok(!matchesKnownRoute("/clients/some-id/not-a-real-section", FIXTURE_SHAPES));
  assert.ok(!matchesKnownRoute("/settings/security", FIXTURE_SHAPES));
  assert.ok(!matchesKnownRoute("/nope", FIXTURE_SHAPES));
});
