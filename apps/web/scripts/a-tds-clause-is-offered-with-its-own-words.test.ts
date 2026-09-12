// TDS-22, the display half. The backend registry gained four clause keys —
// 194I(A)/(B) and 194J(A)/(B) — and the supplier screen's dropdown is served
// straight from GET /api/tds/sections, so they appear automatically. What does
// NOT appear automatically is a readable label: SECTION_LABELS is this
// screen's own map and an unlisted code renders as the bare "194I(A)".
//
// That map is a display concern and stays one. What it must not become is a
// SECOND registry — the list of which sections exist, and which a vendor may
// carry, is the server's (`vendor_eligible`), and the Schedule III captions
// are the scar that says why.
//
// Run with: node --experimental-strip-types --test scripts/a-tds-clause-is-offered-with-its-own-words.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(__dirname, "..", "app", "accounting", "suppliers", "page.tsx");
const code = stripComments(fs.readFileSync(PAGE, "utf8"));

const LIMBS = ["194I(A)", "194I(B)", "194J(A)", "194J(B)"];

test("every clause the registry holds has words a CA can read", () => {
  for (const limb of LIMBS) {
    assert.ok(code.includes(`"${limb}":`),
      `${limb} would render as a bare code in the section dropdown`);
  }
});

test("the labels distinguish the two limbs of each section", () => {
  // The whole point of the clause is that a CA can tell plant hire from
  // building rent. Two labels that read the same defeat it.
  const labels = LIMBS.map(l => {
    const m = code.match(new RegExp(`"${l.replace(/[()]/g, "\\$&")}":\\s*"([^"]+)"`));
    return m?.[1] ?? "";
  });
  assert.equal(new Set(labels).size, LIMBS.length, `labels collide: ${labels}`);
  assert.ok(labels.every(l => l.length > 8), `a label is too short to help: ${labels}`);
});

test("no label states a rate", () => {
  // Nothing in this product states the concessional rate. A label reading
  // "technical services — 2%" would be the first place it appeared, and it
  // would be a figure nobody checked against the Finance Act.
  for (const limb of LIMBS) {
    const m = code.match(new RegExp(`"${limb.replace(/[()]/g, "\\$&")}":\\s*"([^"]+)"`));
    assert.ok(m && !/%|\bper cent\b/i.test(m[1]),
      `${limb}'s label quotes a rate: ${m?.[1]}`);
  }
});

test("the screen still lets the SERVER decide which sections a vendor may carry", () => {
  assert.match(code, /vendor_eligible \?\? true/,
    "a second exclusion list in the browser is how the Schedule III captions " +
    "drifted in both directions at once");
});
