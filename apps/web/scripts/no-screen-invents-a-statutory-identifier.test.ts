/**
 * NO SCREEN MINTS A TAN, A PAN, A GSTIN OR A CIN.
 *
 * WHAT HAPPENED
 *
 * `app/tds/returns/page.tsx` assembled a whole quarterly TDS statement in the
 * browser, and it had nowhere to read the deductor's identity from, so it
 * wrote one:
 *
 *     const tan = "MUMB00000A";  // placeholder — must be configured per client
 *     deductor_pan: "AAAAA0000A",
 *     deductor_address: "Address not configured",
 *
 * Both literals are the RIGHT SHAPE — four letters, five digits, one letter;
 * five letters, four digits, one letter — so every validator on the way
 * through accepted them, the payload came back clean, and the return was
 * saved as "prepared" under a TAN belonging to nobody. The comment says
 * "placeholder" and that is exactly the problem: a placeholder that validates
 * is indistinguishable from an answer.
 *
 * A quarter filed under a wrong TAN credits somebody else's deductees, while
 * §200/§201 exposure stays with the deductor who actually withheld. The
 * platform HAS the right value — `client_statutory_identity.tan`, migration
 * 325, created for precisely this — and the fix was to read it and refuse by
 * name when it is absent (`apps/api/domain/tds/deductor.py`).
 *
 * WHY A GUARD ON THE SHAPE AND NOT ON THE VALUE
 *
 * The rule is "a statutory identifier is a fact somebody recorded, never one
 * this code produced", and there is no way to test that directly from source.
 * What CAN be tested is the tell: a string literal in the shape of a
 * registration number. Every legitimate use of such a shape is a REGEX, a
 * test fixture, or an example inside a comment or a placeholder attribute —
 * all of which this skips. What is left is a value the code could send.
 *
 * The same rule on the backend is stated where the value is resolved rather
 * than by scanning: `resolve()` returns None and names the gap.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

/** The four identifier shapes, as they appear inside a string literal. */
const SHAPES: { name: string; re: RegExp }[] = [
  // TAN — IT Act s.203A. AAAA99999A
  { name: "TAN", re: /"[A-Z]{4}[0-9]{5}[A-Z]"|'[A-Z]{4}[0-9]{5}[A-Z]'/g },
  // PAN — IT Act s.139A. AAAAA9999A
  { name: "PAN", re: /"[A-Z]{5}[0-9]{4}[A-Z]"|'[A-Z]{5}[0-9]{4}[A-Z]'/g },
  // GSTIN — CGST s.25 with Rule 8. 99AAAAA9999A9Z9
  { name: "GSTIN", re: /"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]"/g },
  // CIN — Companies Act s.7(3). L99999AA9999AAA999999
  { name: "CIN", re: /"[LUu][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}"/g },
];

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)) out.push(p);
  }
  return out;
}

/** Source with comments, placeholder attributes and example prose removed.
 *
 *  An identifier in a `placeholder="MUMD12345E"` is a HINT — it is shown to
 *  the CA so they know the shape to type, it is never a value, and React does
 *  not submit it. An identifier in a comment is documentation. Stripping both
 *  is what keeps this guard from being answered with `// eslint-disable`. */
function submittable(file: string): string {
  return fs.readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/\/\/.*$/gm, "")
    .replace(/placeholder\s*=\s*(["'`])[\s\S]*?\1/g, "")
    .replace(/placeholder:\s*(["'`])[\s\S]*?\1/g, "");
}

test("no screen carries a statutory identifier as a literal it could send", () => {
  const found: string[] = [];
  for (const file of walk(WEB)) {
    const src = submittable(file);
    for (const { name, re } of SHAPES) {
      for (const m of src.match(re) ?? []) {
        found.push(`${path.relative(WEB, file)}: ${name} ${m}`);
      }
    }
  }
  assert.deepEqual(
    found, [],
    "A statutory identifier is a fact somebody recorded, never one this code " +
    "produced. `/tds/returns` sent const tan = \"MUMB00000A\" and " +
    "deductor_pan: \"AAAAA0000A\" — both well-formed, so every validator " +
    "passed and the quarter saved under a TAN belonging to nobody. Read it " +
    "(client_statutory_identity, the client's own PAN) and refuse by name " +
    "when it is not recorded:\n  " + found.join("\n  "),
  );
});

test("the TDS returns screen gets its deductor from the server", () => {
  const src = fs.readFileSync(path.join(WEB, "app/tds/returns/page.tsx"), "utf8");
  // It must not send a deductor block at all — a screen that could pass one
  // could pass a wrong one, and this one did.
  for (const field of ["deductor_pan", "deductor_address", "deductor_name"]) {
    assert.ok(
      !new RegExp(`${field}\\s*:`).test(src.replace(/^\s*\/\/.*$/gm, "")),
      `${field} is being sent from the browser again. The server reads it ` +
      "from client_statutory_identity and the client's own columns, and " +
      "refuses by name when it is absent (domain/tds/deductor.py).",
    );
  }
  assert.match(src, /computeReturnFromBooks/,
    "the statement is built server-side from the posted books, not assembled here");
});

test("nothing in the browser says a deduction was deposited", () => {
  // TDS-29. The assembly sent
  //     tds_deducted_paise:  Number(d.tds_paise ?? 0),
  //     tds_deposited_paise: Number(d.tds_paise ?? 0),
  // — the SAME expression twice — so `total_deducted − total_deposited` was
  // zero by construction and the engine's own shortfall check (which raises
  // only on a positive gap) could never fire. The screen told the CA every
  // quarter was fully deposited. §201(1A) charges 1.5% for every month or
  // part of a month from the date of DEDUCTION on exactly that gap.
  //
  // The rule, not a spelling of it: the two columns may never be assigned the
  // same expression. What was deposited is decided by which challan paid which
  // deduction — FIFO within the section and month,
  // apps/api/domain/tds/challan_mapping.py — and no screen holds that. Passing
  // the SERVER's own two figures through (saveTDSReturn) is untouched by this,
  // because those are two different reads of one computed payload.
  const PAIR = /tds_deducted_paise\s*:\s*([^,\n}]+)[,\n][\s\S]{0,200}?tds_deposited_paise\s*:\s*([^,\n}]+)/g;
  for (const file of walk(WEB)) {
    const src = submittable(file);
    for (const m of src.matchAll(PAIR)) {
      const deducted = m[1].trim().replace(/\s+/g, " ");
      const deposited = m[2].trim().replace(/\s+/g, " ");
      // An interface declares both as `number;`, which is the same text and
      // not an assignment. A type is not a value.
      if (/^(number|string|boolean|bigint|any|unknown)\b/.test(deducted)) continue;
      assert.notEqual(
        deposited, deducted,
        `${path.relative(WEB, file)} sets tds_deposited_paise to the same ` +
        `expression as tds_deducted_paise (${deducted}). That makes the ` +
        "shortfall zero by construction and hides a §201(1A) exposure. Let " +
        "the server match the challans (/api/tds/{26q,24q,27q}/from-books).",
      );
    }
  }
});
