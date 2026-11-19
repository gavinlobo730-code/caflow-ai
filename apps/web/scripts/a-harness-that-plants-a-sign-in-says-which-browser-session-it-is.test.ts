// A script that plants a fake sign-in in a browser also plants the marker that says it is the browser session the person signed in during.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-harness-that-plants-a-sign-in-says-which-browser-session-it-is.test.ts
//
// WHAT WAS WRONG (found on 19-11-2026, driving the merged branch in a real browser). POST-A-483 made a sign-in end when the browser
// closes: at page start a stored session is kept only if the person ticked "keep me signed in", or a tab of this browser session
// holds the marker (lib/auth/browserSession). The nightly smoke walk and the drive both plant the session in local storage and
// nothing else, so after that change every page they opened was the sign-in screen: the drive failed all 19 scenarios it was asked
// for (including the ones nobody had touched) and the walk would have audited the sign-in page at every route. Nothing in a pull
// request runs either of them, so it would have surfaced as a red nightly the next morning.
//
// THE RULE, not the three spellings: every script under apps/web/scripts that writes a "-auth-token" key into a browser also writes the
// marker key the app reads, and that key is the app's own constant, read from lib/auth/browserSession.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { MARKER_KEY } from "../lib/auth/browserSession.ts";

const SCRIPTS = import.meta.dirname;

function scriptsThatPlantASignIn(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== "node_modules") walk(full); continue; }
      if (!/\.(mjs|js)$/.test(e.name)) continue;
      if (/localStorage\.setItem\(\s*"sb-"/.test(fs.readFileSync(full, "utf8"))) out.push(full);
    }
  };
  walk(SCRIPTS);
  return out;
}

test("the scripts that plant a sign-in are found, so the rule below is not vacuous", () => {
  const found = scriptsThatPlantASignIn().map((f) => path.basename(f)).sort();
  assert.ok(found.includes("smoke-walk.mjs") && found.includes("driveMoneyEditors.mjs"), `the scan did not find the walk and the drive: ${found.join(", ")}`);
});

test("every script that plants a sign-in also plants the browser-session marker", () => {
  assert.equal(MARKER_KEY, "practicesync_session_marker", "the app's marker key changed: the harnesses spell it out, so each must follow");
  for (const file of scriptsThatPlantASignIn()) {
    const src = fs.readFileSync(file, "utf8");
    assert.match(src, new RegExp(`sessionStorage\\.setItem\\(\\s*"${MARKER_KEY}"`),
      `${path.relative(SCRIPTS, file)} plants a sign-in in local storage and not the marker ${MARKER_KEY} in session storage: the browser-session rule signs it out at page start and every page is the sign-in screen`);
  }
});
