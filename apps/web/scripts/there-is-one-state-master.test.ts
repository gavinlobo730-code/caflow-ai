// One list of Indian states and their GST codes. Run with:
//   node --experimental-strip-types --test scripts/there-is-one-state-master.test.ts
//
// WHY THIS EXISTS
//     There were four. lib/constants/indianStates.ts was the complete one, and
//     lib/invoices/gst.ts carried a second array of thirty entries that
//     InvoiceEditor and CustomerFormModal passed to StateLookup EXPLICITLY —
//     overriding the complete list the component defaults to. Goa (30), Dadra &
//     Nagar Haveli and Daman & Diu (26), Puducherry (34), Ladakh (38),
//     Lakshadweep (31) and Andaman & Nicobar (35) could not be selected as a
//     place of supply or as a customer's state at all.
//
//     That is not a cosmetic gap. The place of supply decides CGST+SGST against
//     IGST (IGST Act ss.7 and 8) and is a Rule 46(n) particular of the invoice,
//     so a customer in Goa either could not be invoiced correctly or was
//     invoiced under someone else's state.
//
//     The lever was the explicit prop: a default that is right is no protection
//     when a caller passes its own copy.
//
// WHAT IS KNOWN AND DELIBERATELY NOT CHANGED
//     app/settings/page.tsx and app/onboarding/page.tsx hold name-only arrays
//     for a FIRM's postal address — free text, no GST code, stored as typed.
//     Pointing them at the canonical names would change the spelling of stored
//     values ("Jammu & Kashmir" against "Jammu and Kashmir") and orphan what is
//     already saved, so they are named here rather than silently swept in.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const CANONICAL = "lib/constants/indianStates.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/\/\/.*$/gm, "");
}

function sources(): string[] {
  const out: string[] = [];
  const skip = new Set(["node_modules", ".next", "out", "scripts", ".turbo"]);
  (function walk(dir: string) {
    for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
      const rel = path.join(dir, e.name);
      if (e.isDirectory()) { if (!skip.has(e.name)) walk(rel); continue; }
      if (e.name.endsWith(".ts") || e.name.endsWith(".tsx")) out.push(rel);
    }
  })(".");
  return out.map((p) => p.replace(/^\.\//, ""))
            .filter((p) => !p.endsWith(".test.ts") && !p.endsWith(".test.tsx"));
}

/** Every { code: "NN", name: "…" } pair in a file. */
function statePairs(src: string): Array<[string, string]> {
  return [...src.matchAll(/\{\s*code:\s*"(\d{2})"\s*,\s*name:\s*"([^"]+)"\s*\}/g)]
    .map((m) => [m[1], m[2]] as [string, string]);
}

// ── One definition ─────────────────────────────────────────────────────────

test("only the canonical module defines a state master", () => {
  const offenders: string[] = [];
  for (const rel of sources()) {
    if (rel === CANONICAL) continue;
    // Three or more pairs is a list, not an incidental object literal or a
    // fixture of one or two rows.
    if (statePairs(code(rel)).length >= 3) offenders.push(rel);
  }
  assert.deepEqual(offenders, [],
    `import INDIAN_STATES from ${CANONICAL}. A second list is how six states ` +
    "and UTs stopped being selectable while the complete list sat unused.");
});

test("nothing overrides StateLookup's list with its own", () => {
  const offenders: string[] = [];
  for (const rel of sources()) {
    if (/<StateLookup[^>]*\bstates=\{/.test(code(rel))) offenders.push(rel);
  }
  assert.deepEqual(offenders, [],
    "StateLookup already defaults to the canonical master. Passing a list " +
    "explicitly is the exact lever that hid the incomplete copy — if a screen " +
    "genuinely needs a SUBSET, derive it from INDIAN_STATES and update this " +
    "test deliberately.");
});

// ── The list is complete, and holds nothing dead ───────────────────────────

test("every live state and union territory is offered", () => {
  const byCode = new Map(statePairs(code(CANONICAL)));
  for (const [c, name] of [
    ["26", "Dadra & Nagar Haveli and Daman & Diu"],
    ["30", "Goa"],
    ["31", "Lakshadweep"],
    ["34", "Puducherry"],
    ["35", "Andaman & Nicobar Islands"],
    ["38", "Ladakh"],
  ] as Array<[string, string]>) {
    assert.equal(byCode.get(c), name, `state code ${c} must be selectable`);
  }
  assert.equal(byCode.size, 36, "36 live GST state/UT codes");
});

test("the dead codes are not offered for a new document", () => {
  const byCode = new Map(statePairs(code(CANONICAL)));
  // 25 (Daman & Diu) merged into 26 on 26-01-2020; 28 (Andhra Pradesh) was
  // replaced by 37 in 2014. The backend still ACCEPTS both so a historical
  // document parses — offering them here would let a CA pick a code the portal
  // rejects.
  assert.equal(byCode.has("25"), false);
  assert.equal(byCode.has("28"), false);
});

// ── The frontend never offers a code the backend refuses ───────────────────

test("every offered code is one the backend accepts", () => {
  const validator = fs.readFileSync(
    path.resolve(WEB, "..", "api", "domain", "gst", "validator.py"), "utf8");
  const block = /VALID_STATE_CODES\s*=\s*\{([\s\S]*?)\}/.exec(validator);
  assert.ok(block, "VALID_STATE_CODES not found in domain/gst/validator.py");
  const accepted = new Set([...block![1].matchAll(/"(\d{2})"/g)].map((m) => m[1]));
  for (const [c] of statePairs(code(CANONICAL))) {
    assert.ok(accepted.has(c),
      `the picker offers ${c} and domain/gst/validator.py rejects it — the ` +
      "invoice would be refused after the CA had typed it.");
  }
});
