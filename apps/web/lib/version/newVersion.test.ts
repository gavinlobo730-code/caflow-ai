import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CHECK_EVERY_MS, FIRST_CHECK_AFTER_MS, RECHECK_ON_RETURN_MS, cleanVersion, dueForLook, isNewer, mayLoadOnMove, readLiveVersion,
} from "./newVersion.ts";
import { buildVersion } from "../../scripts/write-build-version.mjs";

test("a newer build is two known ids that differ, and an unknown on either side says nothing", () => {
  assert.equal(isNewer("abc1234", "def5678"), true);
  assert.equal(isNewer("abc1234", "abc1234"), false);
  for (const unknown of ["", null, undefined, 7, {}, "has a space", "x".repeat(81), "<script>"]) {
    assert.equal(isNewer(unknown, "def5678"), false, `built ${String(unknown)}`);
    assert.equal(isNewer("abc1234", unknown), false, `live ${String(unknown)}`);
  }
});

test("the live answer is read only when it is the file expected", () => {
  assert.equal(readLiveVersion({ version: "abc1234" }), "abc1234");
  for (const bad of [null, undefined, "abc1234", ["abc1234"], {}, { version: 7 }, { version: "" }, { version: "a b" }, { Version: "abc1234" }]) {
    assert.equal(readLiveVersion(bad), null, JSON.stringify(bad));
  }
  assert.equal(cleanVersion("local-m3x9.1_a"), "local-m3x9.1_a");
});

test("the file is asked for a while after the tab opens, then on a slow beat, sooner on coming back, and never while hidden", () => {
  const opened = 1_000_000;
  assert.equal(dueForLook(opened + FIRST_CHECK_AFTER_MS - 1, opened, null, true, false), false);
  assert.equal(dueForLook(opened + FIRST_CHECK_AFTER_MS, opened, null, true, false), true);
  const looked = opened + FIRST_CHECK_AFTER_MS;
  assert.equal(dueForLook(looked + CHECK_EVERY_MS - 1, opened, looked, true, false), false);
  assert.equal(dueForLook(looked + CHECK_EVERY_MS, opened, looked, true, false), true);
  // Coming back to the tab looks sooner than the beat, and not at once after a look.
  assert.equal(dueForLook(looked + RECHECK_ON_RETURN_MS - 1, opened, looked, true, true), false);
  assert.equal(dueForLook(looked + RECHECK_ON_RETURN_MS, opened, looked, true, true), true);
  assert.equal(dueForLook(looked + 10 * CHECK_EVERY_MS, opened, looked, false, true), false, "a hidden tab asked");
  assert.ok(RECHECK_ON_RETURN_MS < CHECK_EVERY_MS && FIRST_CHECK_AFTER_MS >= 10_000);
});

test("a move to another screen loads a new build once, and not again for the same build", () => {
  assert.equal(mayLoadOnMove("def5678", null), true);
  assert.equal(mayLoadOnMove("def5678", "abc1234"), true);
  assert.equal(mayLoadOnMove("def5678", "def5678"), false, "the tab would reload at every move while a cache serves the old build");
  assert.equal(mayLoadOnMove(null, null), false);
});

test("a build's id is the commit being built, and a build with none still has one", () => {
  assert.equal(buildVersion({ CF_PAGES_COMMIT_SHA: "CAE9CE2D1AA5CAFA2E376D3D404124BEB8BF3156" }, 0), "cae9ce2d1aa5cafa2e376d3d404124beb8bf3156");
  const local = buildVersion({}, 1_763_000_000_000);
  assert.match(local, /^local-[0-9a-z]+$/);
  assert.equal(cleanVersion(local), local, "a local id is not one the browser accepts");
  assert.notEqual(buildVersion({ CF_PAGES_COMMIT_SHA: "not a sha" }, 5), "not a sha");
  assert.notEqual(buildVersion({}, 1), buildVersion({}, 2));
});
