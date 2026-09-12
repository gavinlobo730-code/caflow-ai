// PUR-32, the frontend half. The rule can be perfect and still be worth
// nothing: the create response carries `near_duplicates`, and until this
// landed the editor closed on save and threw the whole envelope away.
//
// What these hold is narrow on purpose — the panel's wording will change with
// the design pass, and a test that pins copy is a test somebody deletes. What
// must not change is that the field is READ, that the editor STAYS OPEN when
// it is present, and that no arithmetic about duplicates happens here.
//
// Run with: node --experimental-strip-types --test scripts/a-near-duplicate-bill-is-shown-to-the-ca.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const EDITOR = path.join(__dirname, "..", "components", "purchases", "PurchaseBillEditor.tsx");
const src = fs.readFileSync(EDITOR, "utf8");
const code = stripComments(src);

test("the editor reads near_duplicates off the create response", () => {
  // The ACCESS, not the type annotation. A first draft of this test matched
  // the identifier anywhere, and passed happily with the read renamed to a
  // field the server does not send — the cast still mentioned it.
  const save = code.slice(code.indexOf("async function save()"));
  assert.match(save, /\?\.\s*near_duplicates\b/,
    "the server's warning is dropped — the CA is never told");
});

test("a warned save does not close the editor", () => {
  // The bill IS saved; the warning is the point of staying. `return` before
  // onDone is what keeps the drawer open.
  const save = code.slice(code.indexOf("async function save()"));
  const warnBlock = save.slice(save.indexOf("near_duplicates"), save.indexOf("const label"));
  assert.match(warnBlock, /setNearDupes\(/);
  assert.match(warnBlock, /\breturn;/,
    "without the early return the editor closes and the warning is invisible");
});

test("the CA can still close it, so the warning is not a trap", () => {
  assert.match(code, /onDone\(`\$\{billNo\.trim\(\) \|\| "Purchase bill"\}/,
    "a panel with no way past it blocks a legitimate bill, which is exactly " +
    "what this warning exists NOT to do");
});

test("the CA is warned BEFORE the save, not only after", () => {
  // Telling somebody they have booked a bill twice is worth much less than
  // telling them they are about to. The preflight endpoint exists for this;
  // without a caller it is one more endpoint no screen reaches.
  assert.match(code, /"\/api\/purchase-bills\/near-duplicates"/,
    "the preflight endpoint has no caller");
  assert.match(code, /setDupeAhead\(/);
});

test("the preflight is debounced, so typing a bill number is not a request per keystroke", () => {
  const effect = code.slice(code.indexOf("/api/purchase-bills/near-duplicates") - 900,
                            code.indexOf("/api/purchase-bills/near-duplicates") + 900);
  assert.match(effect, /setTimeout\(/);
  assert.match(effect, /clearTimeout\(/);
});

test("a failed preflight is silence, never a blocked save", () => {
  const effect = code.slice(code.indexOf("/api/purchase-bills/near-duplicates"),
                            code.indexOf("/api/purchase-bills/near-duplicates") + 700);
  assert.match(effect, /catch\b/,
    "an unreachable warning must not stop a legitimate bill being recorded");
});

test("no duplicate arithmetic happens in the browser", () => {
  // House rule: zero business logic in the frontend. The confusion set, the
  // date window and the amount test all live in
  // apps/api/domain/purchases/near_duplicate.py.
  for (const forbidden of ["_CONFUSABLE", "normalise_number", "levenshtein", "window_days"]) {
    assert.ok(!code.includes(forbidden),
      `${forbidden} belongs in the backend rule, not in the editor`);
  }
});
