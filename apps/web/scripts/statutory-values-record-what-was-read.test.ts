// The firm's own reading of the state PT notifications. Run with:
//   node --experimental-strip-types --test scripts/statutory-values-record-what-was-read.test.ts
//
// WHY THIS EXISTS
//     Professional tax is levied by twenty-two states, each setting its own
//     slabs by its own notification. The software models four and reports the
//     rest as gaps rather than deducting zero — right, because Article 276
//     makes the employer liable, so a silent nil is a shortfall with interest.
//
//     Correct, and not a product: the only remedy was that somebody edits
//     Python. This screen lets a CA record what they READ, once per firm.
//
//     Three properties are pinned here because losing any of them would
//     reintroduce the exact fault the mechanism exists to avoid, and none of
//     them looks wrong on screen:
//
//       * amounts through the exact parser. `parseFloat("1,25,000")` is 1, and
//         a slab band of one rupee deducts from everybody.
//       * the whole set posted in ONE call. A per-band save would let a
//         half-recorded state exist between two clicks, and a wage in the hole
//         comes out as a nil deduction.
//       * the notification reference and date required before saving. The only
//         reason a hand-entered figure may drive a statutory deduction is that
//         a named person read a named notification on a named date.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/settings/statutory-values/page.tsx";
const src = fs.readFileSync(path.join(ROOT, PAGE), "utf8");
const api = fs.readFileSync(path.join(ROOT, "lib/api/index.ts"), "utf8");

/** Comments stripped — these assertions are about CODE, and the notes in this
 *  file and that one quote the forms they warn against. */
const code = src
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/^\s*\/\/.*$/gm, "");

test("the page exists and is reachable from Settings", () => {
  assert.match(code, /export default function StatutoryValuesPage/);
  const index = fs.readFileSync(path.join(ROOT, "app/settings/page.tsx"), "utf8");
  assert.match(index, /href="\/settings\/statutory-values"/);
});

test("amounts go through the exact parser, never parseFloat", () => {
  assert.doesNotMatch(code, /parseFloat\s*\(/,
    "parseFloat('1,25,000') is 1 — a slab band of one rupee deducts from everybody");
  assert.match(code, /import \{ paiseFromRupeeInput \} from "@\/lib\/money\/rupeeInput"/);
  assert.match(code, /const from = paiseFromRupeeInput\(band\.from\)/);
  assert.match(code, /const amount = paiseFromRupeeInput\(band\.amount\)/);
});

test("a field the parser refuses stops the save instead of becoming a number", () => {
  assert.match(code, /if \(from === null \|\| amount === null/);
  assert.match(src, /must be plain figures in rupees, without commas/);
});

test("the whole set is posted in one call", () => {
  // A per-band endpoint would let a half-recorded state exist between two
  // clicks, and during that window a wage in the hole is a nil deduction.
  assert.match(code, /api\.statutoryValues\.savePtSlabs\(\{/);
  assert.match(code, /bands: parsed\.map\(/);
  assert.doesNotMatch(code, /savePtBand\(/);
});

test("the notification reference and date are required before saving", () => {
  assert.match(code, /if \(!reference\.trim\(\) \|\| !notifiedOn \|\| !effectiveFrom\)/);
  assert.match(src, /a recorded figure that names no source/);
});

test("the authority is printed beside the figures", () => {
  // It is the reason these numbers may drive a deduction at all, so it belongs
  // on the card and not only in the form.
  assert.match(code, /\{first\.notification_reference\} · notified \{first\.notification_date\}/);
});

test("states that still deduct nothing are named, not counted", () => {
  // So a CA can see whether any of them is one of their clients'.
  assert.match(code, /const stillMissing = levyingCodes\.filter\(/);
  assert.match(src, /still\s*\n?\s*deduct nothing/);
});

test("a set recorded against a modelled state is shown as not used", () => {
  // Never applied and never silently dropped: applying it would let one typo
  // replace a table verified against the state Act for every client.
  assert.match(code, /setConflicts\(res\.data\.pt_conflicts \?\? \[\]\)/);
  assert.match(src, /Recorded, but not used/);
});

test("the page holds no copy of who levies professional tax", () => {
  // It comes from the API. A hardcoded list would drift the moment a state
  // moved, and the drift would be invisible.
  assert.match(code, /setLevying\(res\.data\.pt_levying_states \?\? \{\}\)/);
  assert.doesNotMatch(code, /"Gujarat"|"Telangana"/);
});

test("the api client exposes the firm-scoped calls", () => {
  assert.match(api, /statutoryValues: \{/);
  assert.match(api, /"\/api\/payroll\/statutory-values"/);
  assert.match(api, /method: "PUT", body: JSON\.stringify\(body\) \}\),/);
});

test("only Partner and Manager reach the screen", () => {
  // payroll:write is Manager+, and one recorded slab deducts from every client
  // of the firm in that state.
  assert.match(code, /<RoleGuard allowed=\{\["Partner", "Manager"\]\}>/);
});
