// The Setup tab writes one registration at a time, and does not hold its own
// idea of which registrations exist. Run with:
//   node --experimental-strip-types --test scripts/statutory-identity-is-recorded-once.test.ts
//
// WHY THIS EXISTS
//     PUT /api/payroll/statutory-identity is PATCH-shaped: it writes only the
//     fields present in the body, so "leave the TAN alone" and "this client has
//     no TAN" stay different edits.
//
//     A form that posted its whole state on every save would collapse those
//     two. Editing the LIN would send tan: "" alongside it, and a TAN this
//     screen had merely failed to load would be cleared — silently, on a value
//     that goes onto a filed quarter. That is exactly the class of silent write
//     the table was added to end, so the shape is pinned here rather than left
//     to whoever next touches the file.
//
//     The FIELD LIST is the same argument from the other side. It comes from
//     the API's `fields` block; a hardcoded copy here would drift the moment a
//     registration was added to the table, and the new one would be invisible
//     with nothing to show it was missing.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/clients/[id]/payroll/page.tsx";
const src = fs.readFileSync(path.join(ROOT, PAGE), "utf8");

/** The file with comments stripped — these assertions are about CODE, and the
 *  notes above the component quote the very shapes they warn against. */
const code = src
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/^\s*\/\/.*$/gm, "");

test("the tab exists and is reachable", () => {
  assert.match(code, /function StatutoryIdentityTab\(/);
  assert.match(code, /tab === "setup"\s+&& <StatutoryIdentityTab clientId=\{clientId\} \/>/);
  assert.match(code, /\{ id: "setup",\s+label: "Setup"/);
});

test("a save sends the one field that changed, not the whole form", () => {
  assert.match(code, /body: JSON\.stringify\(\{ client_id: clientId, \[name\]: raw \}\)/,
    "the identity save must be a single computed key, so an untouched field is never sent");
});

test("the field list is read from the API, not held here", () => {
  assert.match(code, /fields: IdentityField\[\]/);
  assert.match(code, /setFields\(res\.data\.fields \?\? \[\]\)/);
  // The four names must NOT appear as a literal list in the page: that would be
  // a second source of truth for what a statutory identity is.
  assert.doesNotMatch(code, /\[\s*"tan"\s*,\s*"epf_establishment_code"/,
    "no hardcoded field list — the API's `fields` block is the only one");
});

test("a failed load is not rendered as 'nothing recorded'", () => {
  // Same mistake the 26/26 attendance default made, in the UI: an absent answer
  // and a failed question shown identically.
  assert.match(code, /const \[loadFailed, setLoadFailed\] = useState\(false\)/);
  assert.match(src, /This is not the same as having none recorded/);
});

test("the server's refusal reaches the CA verbatim", () => {
  // The 422 for a bad TAN names WHY. A generic "couldn't save" would throw away
  // the only useful part of it.
  assert.match(code, /setSaveError\(body\?\.error \|\| body\?\.detail \|\|/);
});

test("PTRC and PTEC are separate fields", () => {
  // The Registration Certificate authorises DEDUCTING from employees; the
  // Enrolment Certificate is the entity's own levy. One field for both would
  // pay one against the other in a state department's ledger.
  assert.match(code, /ptrc_number: ptForm\.ptrc_number\.trim\(\)/);
  assert.match(code, /ptec_number: ptForm\.ptec_number\.trim\(\)/);
});
