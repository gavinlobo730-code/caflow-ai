// Which screens the product has, frozen — so a rebuild cannot lose one.
//
// The client workspace is about to be rebuilt around a module hub instead of
// a sidebar. That is a large, deliberate change to how a CA reaches a screen,
// and the failure mode it carries is not a crash: it is a page that quietly
// stops being linked from anywhere and is discovered missing in November, by
// a CA who used it once a year.
//
// generate-known-routes.js already walks the same tree, but it REGENERATES on
// every build by design — knownRoutes.generated.ts is a cache of what exists,
// so deleting a page updates it silently and nothing objects. This snapshot is
// the opposite: a record of what existed when somebody last looked, which does
// not move unless a person moves it.
//
//   * a route in the snapshot that no longer has a page.tsx FAILS, by name;
//   * a route that is new passes — the redesign is expected to add screens;
//   * a route that MOVED is a loss and an addition, so the loss still fails,
//     which is the point: /clients/:id/gst becoming /clients/:id/hub/gst is
//     exactly the change that breaks every bookmark and every deep link the
//     product itself holds.
//
// What it does NOT check is whether anything LINKS to the page — that is
// scripts/no-orphan-screens.test.ts's job on the frontend and
// apps/api/tests/test_the_redesign_cannot_orphan_an_endpoint.py's on the
// backend. This one only says the screen still exists.
//
// Refresh deliberately, and say in the commit which screens went and why:
//   node scripts/refresh-screen-snapshot.js
//
// Run with: node --experimental-strip-types --test scripts/the-redesign-cannot-lose-a-screen.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { screenRoutes } from "./refresh-screen-snapshot.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_DIR = path.join(__dirname, "..", "app");
const SNAPSHOT_FILE = path.join(__dirname, "screens.snapshot.json");

// A snapshot truncated by a half-finished write passes every other assertion
// here vacuously. The tree of 2026-09-12 has 159 screens.
const MIN_SCREENS = 120;

const snapshot: string[] = JSON.parse(fs.readFileSync(SNAPSHOT_FILE, "utf8"));
const present = new Set(screenRoutes(APP_DIR));

test("the snapshot is not empty", () => {
  assert.ok(
    snapshot.length >= MIN_SCREENS,
    `screens.snapshot.json holds ${snapshot.length} screens, expected at least ` +
      `${MIN_SCREENS}. A truncated snapshot makes every other test here pass ` +
      `without checking anything.`
  );
});

test("the snapshot is sorted and unique, so a refresh diffs readably", () => {
  const tidy = [...new Set(snapshot)].sort();
  assert.deepEqual(
    snapshot,
    tidy,
    "screens.snapshot.json is not sorted-unique — regenerate it with " +
      "`node scripts/refresh-screen-snapshot.js`"
  );
});

test("no screen has been deleted without saying so", () => {
  const lost = snapshot.filter((route) => !present.has(route));
  assert.deepEqual(
    lost,
    [],
    `${lost.length} screen(s) in the snapshot no longer exist:\n  ` +
      lost.join("\n  ") +
      `\n\nIf a screen MOVED, the old path is still a loss — every deep link ` +
      `and bookmark to it is now a 404, and Cloudflare serves this app as a ` +
      `static export, so there is no server to redirect it. Either keep the ` +
      `route, add a redirect, or refresh the snapshot and name the screens in ` +
      `the commit message:\n  node scripts/refresh-screen-snapshot.js`
  );
});

test("the snapshot describes this app, not a different one", () => {
  // Below this the snapshot is simply stale, and reporting a hundred
  // individual losses hides the one fact worth knowing.
  const still = snapshot.filter((route) => present.has(route)).length;
  assert.ok(
    still >= 0.8 * snapshot.length,
    `only ${still} of ${snapshot.length} snapshotted screens still exist. ` +
      `That is a rewrite, not a regression — read the change, then refresh ` +
      `the snapshot deliberately.`
  );
});
