// Finalising a payroll run with an unresolved gap is refused, not warned about.
// Run with:
//   node --experimental-strip-types --test scripts/a-release-is-blocked-or-signed-for.test.ts
//
// WHY THIS EXISTS
//     The run returns statutory_gaps and attendance_gaps — things it could not
//     establish. They were shown on the draft and enforced nowhere. Finalising
//     posts a real, immutable general-ledger journal, so the warnings stopped
//     being advice at exactly the moment nothing was enforcing them.
//
//     The server now refuses (409) and NAMES the gaps. What is pinned here is
//     that the screen answers a block as a block:
//
//       * the gaps are rendered, not collapsed into "could not finalize".
//         A generic error would send the CA back to the draft to work out
//         which, and the sentences are the whole point of having collected
//         them.
//       * the override needs a typed reason of substance before the button
//         works. The floor matches the server and migration 328's CHECK.
//       * a block is separate state from an error, because they are answered
//         differently and merging them loses the gaps.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/clients/[id]/payroll/page.tsx";
const src = fs.readFileSync(path.join(ROOT, PAGE), "utf8");

/** Comments stripped — the assertions are about CODE, and the notes in the page
 *  describe the very behaviour they guard. */
const code = src
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/^\s*\/\/.*$/gm, "");

test("a refused finalise is held as a block, not as an error string", () => {
  assert.match(code, /const \[blockedRun, setBlockedRun\] = useState</);
  assert.match(code, /Array\.isArray\(detail\.gaps\)/,
    "the 409 body carries the gaps; recognising it is what keeps them");
});

test("the gaps are rendered, each one", () => {
  assert.match(code, /blockedRun\.gaps\.map\(\(g, i\) =>/);
  // Not a count — the sentences are the whole point of having collected them.
  assert.doesNotMatch(code, /blockedRun\.gaps\.length\} problems/);
});

test("the override needs a reason of substance before the button works", () => {
  assert.match(code, /const OVERRIDE_REASON_MIN = 20;/);
  assert.match(code, /disabled=\{overrideReason\.trim\(\)\.length < OVERRIDE_REASON_MIN/);
});

test("the reason is passed explicitly, not read back from state", () => {
  // Otherwise the retry races the textarea.
  assert.match(code, /async function finalizeRun\(runId: string, overrideReason\?: string\)/);
  assert.match(code, /JSON\.stringify\(overrideReason \? \{ override_reason: overrideReason \} : \{\}\)/);
});

test("a plain failure still reaches the CA as an error", () => {
  // task #229: a silently discarded finalize failure left the CA thinking the
  // run had posted. The block must not swallow that path.
  assert.match(code, /setFinalizeError\(/);
  assert.match(code, /Could not finalize the payroll run/);
});

test("the CA is offered the way out that is not an override", () => {
  assert.match(src, /Go back and fix them/);
});

test("a successful finalise clears the block", () => {
  assert.match(code, /setBlockedRun\(null\);\s*\n\s*setOverrideReason\(""\);\s*\n\s*await load\(\)/);
});
