// PUR-23 ≡ TDS-32, the frontend half. The register can name the problem
// perfectly and the CA never see it: `issueDebitNote` and `issueCreditNote`
// showed "Debit note issued." and threw the rest of the envelope away.
//
// Narrow on purpose — the panel's copy and colours will change with the design
// pass. What must not change: the gaps are READ off the issue response, they
// go through the ONE reader that words them, and they land in their own
// persistent panel rather than in a toast a CA dismisses in passing.
//
// Run with: node --experimental-strip-types --test scripts/a-purchase-return-tells-the-ca-about-the-deductee-row.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(__dirname, "..", "app", "clients", "[id]", "purchases", "page.tsx");
const NOTES = path.join(__dirname, "..", "lib", "purchases", "registerNotes.ts");
const code = stripComments(fs.readFileSync(PAGE, "utf8"));
const notes = stripComments(fs.readFileSync(NOTES, "utf8"));

function handler(name: string): string {
  const at = code.indexOf(`async function ${name}(`);
  assert.ok(at >= 0, `${name} is gone — this test is measuring nothing`);
  return code.slice(at, code.indexOf("\n  }", at));
}

test("issuing a purchase return reads the register's answer", () => {
  assert.match(handler("issueDebitNote"), /setRegisterNotes\(/,
    "the note is issued and the CA is never told the deductee row is stale");
});

test("issuing a supplier credit note does the same", () => {
  // §34(3) INCREASES what was credited, so the deduction may be SHORT — the
  // §201(1A) direction, and the expensive one.
  assert.match(handler("issueCreditNote"), /setRegisterNotes\(/);
});

test("both go through the one reader, so one gap has one wording", () => {
  for (const fn of ["issueDebitNote", "issueCreditNote"]) {
    assert.match(handler(fn), /topLevelNotesFrom\(result\.data\)/,
      `${fn} words the gap itself instead of using the shared reader`);
  }
  // And the reader is named for the SHAPE it reads, not for one of its callers.
  assert.match(notes, /export function topLevelNotesFrom\(/);
  assert.doesNotMatch(notes, /export function paymentNotesFrom\(/,
    "a helper named after one of its three callers is how the fourth ends up " +
    "with a hand-rolled copy");
});

test("the warning is a panel, not a toast", () => {
  // A statutory warning inside the green "issued" banner is one the CA
  // dismisses without reading. Each note tab renders its own amber block.
  const panels = code.match(/\{registerNotes\.length > 0 && \(/g) ?? [];
  assert.ok(panels.length >= 3,
    `expected the bills tab and both note tabs to render the panel, found ${panels.length}`);
});

test("each note tab holds its own register-notes state", () => {
  const decls = code.match(/const \[registerNotes, setRegisterNotes\] = useState/g) ?? [];
  assert.ok(decls.length >= 3,
    "a shared state across tabs would carry one tab's warning onto another");
});

test("the panel can be dismissed, so it is not a trap", () => {
  assert.match(code, /onClick=\{\(\) => setRegisterNotes\(\[\]\)\}/);
});
