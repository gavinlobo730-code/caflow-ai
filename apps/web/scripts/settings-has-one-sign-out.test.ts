// Sign Out lives in exactly one place — the global avatar menu
// (components/shell/UtilityCluster.tsx) — not duplicated on the Settings
// page under a "Danger Zone" heading that action doesn't belong under.
//
// Run with:
//   node --experimental-strip-types --test scripts/settings-has-one-sign-out.test.ts
//
// WHAT WAS WRONG (sweep-settings-hub-1-08)
//     app/settings/page.tsx rendered its own "Danger Zone" section whose only
//     content was a Sign Out button, alongside the global avatar-menu sign
//     out that is available on every page. Not broken, just duplicated — and
//     "Danger Zone" is normally reserved for destructive/irreversible
//     actions, which signing out is not.
//
// THE FIX
//     The Danger Zone section (and its now-unused handleSignOut/signOut/
//     router) is removed from the Settings page. The avatar menu's own sign
//     out (UtilityCluster.tsx) is untouched and is still the one place to
//     sign out from.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
}

test("the Settings page no longer has its own Danger Zone / Sign Out section", () => {
  const src = read("app/settings/page.tsx");
  assert.doesNotMatch(src, /Danger Zone/);
  assert.doesNotMatch(src, /handleSignOut/);
  assert.doesNotMatch(src, /Sign Out/);
});

test("the global avatar menu still signs out", () => {
  const src = read("components/shell/UtilityCluster.tsx");
  assert.match(src, /Sign out/);
  assert.match(src, /signOut\(\)/);
});
