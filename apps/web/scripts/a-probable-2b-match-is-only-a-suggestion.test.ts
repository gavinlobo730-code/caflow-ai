// gst-12 — a probable match is a SUGGESTION the CA confirms, never a link.
// Run with:
//   node --experimental-strip-types --test scripts/a-probable-2b-match-is-only-a-suggestion.test.ts
//
// WHAT WAS MISSING
//   A bill under a supplier GSTIN with one character wrong came back as two
//   unrelated rows — "supplier has not filed" and "no bill in the books" — and
//   nothing said they were one invoice.
//
// THE RULES ARE THE SERVER'S — `domain/gst/itc_probable` decides which pairs are
// probable, and `apps/api/tests/test_a_probable_2b_match_is_a_suggestion_and_
// never_a_link.py` pins that it changes no verdict and no credit. This holds what
// only the screen can get wrong: the panel has no control that does anything, it
// renders the server's sentences, and a suggestion is never shown as a match.
//
// This reads source, because the web suite has no DOM.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

const PAGE = read("app/clients/[id]/compliance/gst/page.tsx");
const PROBABLE = read("components/gst/Probable2BMatches.tsx");

function tab(): string {
  const at = PAGE.indexOf("function GSTR2BTab(");
  assert.ok(at >= 0, "GSTR2BTab is gone — move this assertion with it");
  const next = PAGE.indexOf("\nfunction ", at + 1);
  return PAGE.slice(at, next === -1 ? undefined : next);
}

test("the result's list of probable matches is guarded and rendered", () => {
  const t = tab();
  assert.match(t, /objectWithLists<Recon2BResult>\(resp\.data, "defaulters", "problems", "probable_matches"\)/);
  assert.match(t, /<Probable2BMatches clientId=\{clientId\} matches=\{result\.probable_matches \?\? \[\]\}/);
});

test("the probable-match panel changes nothing and has no control that does", () => {
  assert.doesNotMatch(PROBABLE, /<button|onClick|onSubmit|<form/);
  assert.doesNotMatch(PROBABLE, /apiFetch|request\(|api\.|fetch\(/);
  assert.match(PROBABLE, /change[s]? nothing/);
  assert.match(PROBABLE, /withheld until the bill is corrected/);
});

test("the panel says what to check and holds no vocabulary of kinds", () => {
  assert.match(PROBABLE, /p\.evidence\.map/);
  assert.match(PROBABLE, /\{p\.action\}/);
  assert.doesNotMatch(PROBABLE, /supplier_gstin_differs|document_number_differs|amount_and_date_only/,
    "the server decides which pairs are probable and why; the browser keeps no list");
});

test("a suggestion is never rendered as a match", () => {
  const t = tab();
  const at = t.indexOf("<Probable2BMatches");
  assert.ok(at > t.indexOf("RECON_2B_BUCKETS.map"), "it sits beside the buckets, not inside one");
  assert.doesNotMatch(PROBABLE, /matched_count|status === "matched"/);
});
