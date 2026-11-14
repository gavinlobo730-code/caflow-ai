/**
 * The supplier form says who put a no-PE declaration on file, in the server's words (POST-A-407).
 *
 * `vendors.no_pe_declaration_by` is the member whose save recorded the declaration (POST-A-401), and since POST-A-407 only a member who may
 * approve TDS is named. Nothing showed it, so a CA opening a foreign supplier could not see who had vouched for the evidence a nil withholding
 * rests on. The form now reads the NAME from `GET /api/vendors/{id}` (`no_pe_declarant`, read on the server under the firm), and says in words
 * when nobody is named, when the name could not be read and when the member is no longer in the practice. The browser never reads `users`.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = fs.readFileSync(path.join(HERE, "..", "app", "clients", "[id]", "purchases", "page.tsx"), "utf8");

test("the name is the server's, read when an edit opens, and a late answer for another supplier is dropped", () => {
  assert.ok(/apiGet\(`\/api\/vendors\/\$\{v\.id\}`, await getAuthToken\(\)\)/.test(PAGE), "the form does not ask the server for the supplier");
  assert.ok(/d\?\.no_pe_declarant/.test(PAGE), "the form does not read the server's no_pe_declarant");
  assert.ok(/if \(declarantFor\.current === v\.id\) setDeclarant\(said\);/.test(PAGE), "an answer for a supplier no longer open replaces the open one's");
  assert.ok(!/\.from\("users"\)/.test(PAGE), "the page reads members itself");
});

test("each state of the declarant is said in words, and nobody named is a gap the register reports", () => {
  for (const words of [
    "Recorded here by a member (reading the name…).",
    "Recorded here by a member whose name could not be read just now.",
    "Recorded here by a member who is no longer in this practice.",
    "Recorded here by ${declarant.name}.",
    "Not yet recorded by a member who can approve TDS, so the TDS register names this declaration as a gap. ",
  ]) {
    assert.ok(PAGE.includes(words), `the form does not say: ${words}`);
  }
});
