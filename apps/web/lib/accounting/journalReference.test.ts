// Run with: node --experimental-strip-types --test lib/accounting/journalReference.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { JOURNAL_REFERENCE_NOT_REMOVED, editedJournalReference, removedJournalReferenceProblem } from "./journalReference.ts";

test("an emptied reference over one on file is refused, in the one sentence", () => {
  assert.equal(removedJournalReferenceProblem("MJ-1A2B3C4D", ""), JOURNAL_REFERENCE_NOT_REMOVED);
  assert.equal(removedJournalReferenceProblem("JV/2026/014", "   "), JOURNAL_REFERENCE_NOT_REMOVED);
  assert.equal(removedJournalReferenceProblem("JV/2026/014", null), JOURNAL_REFERENCE_NOT_REMOVED);
});

test("a changed reference, the same reference and an empty box over nothing are not refused", () => {
  assert.equal(removedJournalReferenceProblem("MJ-1A2B3C4D", "JV/2026/014"), null);
  assert.equal(removedJournalReferenceProblem("MJ-1A2B3C4D", "MJ-1A2B3C4D"), null);
  assert.equal(removedJournalReferenceProblem("", ""), null);
  assert.equal(removedJournalReferenceProblem(null, undefined), null);
});

test("an edit sends the typed reference trimmed, and nothing at all for an empty box: never null, never a blank", () => {
  assert.equal(editedJournalReference("  JV/2026/014 "), "JV/2026/014");
  assert.equal(editedJournalReference(""), undefined);
  assert.equal(editedJournalReference("   "), undefined);
  assert.equal(editedJournalReference(null), undefined);
});

test("the journal edit page refuses before it sends, and sends the reference through the one function", () => {
  const src = readFileSync(new URL("../../app/clients/[id]/accounting/journal/[entryId]/edit/_page.tsx", import.meta.url), "utf8");
  const start = src.indexOf("// A reference is changed and never removed");
  assert.ok(start >= 0, "the edit branch's note about the reference was not found");
  const edit = src.slice(start);
  const refusal = edit.indexOf("removedJournalReferenceProblem(entry?.reference_no, payload.reference_no)");
  const send = edit.indexOf("api.accounting.updateJournalEntry(");
  assert.ok(refusal >= 0, "the edit branch does not ask whether the reference was emptied");
  assert.ok(send > refusal, "the request is sent before the refusal is asked");
  assert.match(edit, /reference_no: editedJournalReference\(payload\.reference_no\)/);
  assert.doesNotMatch(edit, /reference_no: payload\.reference_no \|\| null/);
});
