// POST-A-528: the platform page's gate. The effect that verifies platform-admin access runs again whenever the context's session object changes
// (a verified code, the hourly token refresh), and `verify` set the gate to "checking" at its start, which the render draws as a spinner in place
// of the page, so a platform administrator who had stepped up with a code, or left the page open an hour, had the page replaced under them and
// anything typed lost. A gate that is already open now stays open while it is read again; a re-check that says no takes the page away at once, and
// one that fails shows the error state. Run with:
//   node --experimental-strip-types --test scripts/the-platform-gate-is-not-re-entered-while-it-is-open.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const src = fs.readFileSync(path.join(import.meta.dirname, "..", "app/platform/page.tsx"), "utf8");
const code = src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");

test("verify shows 'checking' only while the gate is not already open", () => {
  assert.match(code, /const verify = useCallback\(async \(\) => \{\s*setGate\(\(g\) => \(g === "ok" \? g : "checking"\)\);/);
  assert.doesNotMatch(code, /setGate\("checking"\)/, "the gate is set to checking unconditionally again");
});

test("a re-check is never what keeps the gate open: only a successful answer that says yes sets it open, and a no or a failure takes it away", () => {
  assert.match(code, /if \(me\.data\?\.is_platform_admin !== true\) \{\s*setGate\("denied"\);\s*router\.replace\("\/"\);\s*return;\s*\}\s*setGate\("ok"\);/);
  assert.match(code, /setGateErr\(cleanErr\(e, "Could not verify platform access\."\)\);\s*setGate\("error"\);/);
  assert.equal((code.match(/setGate\("ok"\)/g) ?? []).length, 1, "the gate is opened in more than one place");
});

test("a session that is not there at all still sends the person to sign in", () => {
  assert.match(code, /if \(!live\) \{ router\.replace\("\/login"\); return; \}/);
});
