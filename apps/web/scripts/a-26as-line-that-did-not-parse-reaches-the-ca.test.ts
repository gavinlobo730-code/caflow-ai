// IT-24, the frontend half. The parser now reports what it could not read;
// this holds that the screen shows it.
//
// The failure this closes is a false CLEAN result: the drawer used to close on
// any successful response, so a file whose forty rows read as three looked
// exactly like one that read all forty. The reconciliation then reported every
// unread deductor as "missing in 26AS" and the CA chased somebody who had
// filed correctly.
//
// Run with: node --experimental-strip-types --test scripts/a-26as-line-that-did-not-parse-reaches-the-ca.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(__dirname, "..", "app", "clients", "[id]", "tax", "26as", "page.tsx");
const code = stripComments(fs.readFileSync(PAGE, "utf8"));

test("the screen reads the skipped lines off the parse response", () => {
  const handler = code.slice(code.indexOf("/api/form-26as/uploads/"));
  assert.match(handler, /\?\.skipped\?\.length|parsed\?\.skipped/,
    "the server names every line it could not read and the screen ignores it");
  assert.match(handler, /setSkipped\(/);
});

test("a partial read does not close the drawer", () => {
  const handler = code.slice(code.indexOf("/api/form-26as/uploads/"),
                             code.indexOf("async function handleReconcile"));
  const branch = handler.slice(handler.indexOf("setSkipped("));
  assert.match(branch.slice(0, 200), /\breturn;/,
    "closing on a partial read is what made this invisible");
});

test("the CA can close it, and closing clears the state", () => {
  // Inside the PANEL, not anywhere in the file: the success path also clears
  // the state, so a whole-file match passes with the dismiss button inert.
  const panel = code.slice(code.indexOf("{skipped && ("));
  const button = panel.slice(panel.indexOf("<button"), panel.indexOf("</button>"));
  assert.match(button, /setSkipped\(null\)/,
    "a panel that cannot be dismissed blocks the next upload");
  assert.match(button, /setShowUpload\(false\)/);
});

test("the rows that are not a TDS credit are shown, not just excluded", () => {
  // TDS-19. Part C (tax the client paid), Part D (a refund) and Part F
  // (s.194-IA as buyer) are left out of the 26AS-versus-books comparison
  // because they are not credits deducted from this client. Excluding them
  // and saying nothing would replace one wrong number with a missing fact.
  // The RENDER, not the type declaration. A first version matched the
  // identifier anywhere and passed with the whole panel behind `{false &&`.
  assert.match(code, /recon\.not_a_tds_credit\?\.length/,
    "the panel is not conditioned on the server's answer");
  assert.match(code, /recon\.not_a_tds_credit!\.map/,
    "the rows set aside are not listed");
  assert.match(code, /paise\(recon\.not_a_tds_credit_paise/,
    "the total set aside is what a CA checks against the portal");
});

test("the screen does not re-implement the parser", () => {
  // House rule: zero business logic in the frontend. Splitting the pasted text
  // in the browser is how the backend parser came to be bypassed elsewhere.
  for (const forbidden of ["split(\"\\t\")", "PART A", "deductor_tan =", "\\t|\\|"]) {
    assert.ok(!code.includes(forbidden),
      `${forbidden} is parsing — that belongs in apps/api`);
  }
});
