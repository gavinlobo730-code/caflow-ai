// PRE-A-018 — what a fee screen knows about the practice's own books, three answers
// that are never interchangeable. Run with:
//   node --experimental-strip-types --test lib/invoices/practiceBooks.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { readPracticeBooks } from "./practiceBooks.ts";

const ok = (data: unknown) => ({ success: true, data, error: null });

test("a practice client the server named is known", () => {
  assert.deepEqual(readPracticeBooks(ok({ internal_client_id: "abc" })), { state: "known", clientId: "abc" });
  // The rest of GET /api/practice rides along untouched.
  assert.deepEqual(
    readPracticeBooks(ok({ internal_client_id: "abc", pan: "x", gstin: "y" })),
    { state: "known", clientId: "abc" },
  );
});

test("an explicit null is the server saying the practice is not provisioned", () => {
  assert.deepEqual(readPracticeBooks(ok({ internal_client_id: null })), { state: "not_provisioned" });
});

test("anything else is unknown, and unknown is never read as 'not provisioned'", () => {
  const unknown = { state: "unknown" };
  // The call threw (the caller passes undefined for a rejected request).
  assert.deepEqual(readPracticeBooks(undefined), unknown);
  assert.deepEqual(readPracticeBooks(null), unknown);
  assert.deepEqual(readPracticeBooks("nope"), unknown);
  assert.deepEqual(readPracticeBooks([]), unknown);
  // A refusal answered inside HTTP 200 carries success: false and no id.
  assert.deepEqual(readPracticeBooks({ success: false, data: null, error: "forbidden" }), unknown);
  assert.deepEqual(readPracticeBooks({ success: false, data: { internal_client_id: "abc" } }), unknown);
  // An envelope with no success flag is not an answer.
  assert.deepEqual(readPracticeBooks({ data: { internal_client_id: "abc" } }), unknown);
  // A payload of the wrong kind, or one that does not say.
  assert.deepEqual(readPracticeBooks(ok(null)), unknown);
  assert.deepEqual(readPracticeBooks(ok([])), unknown);
  assert.deepEqual(readPracticeBooks(ok({})), unknown);
  assert.deepEqual(readPracticeBooks(ok({ internal_client_id: undefined })), unknown);
  assert.deepEqual(readPracticeBooks(ok({ internal_client_id: 7 })), unknown);
  // An id the sales link would refuse is not a client that can be opened.
  assert.deepEqual(readPracticeBooks(ok({ internal_client_id: "" })), unknown);
  assert.deepEqual(readPracticeBooks(ok({ internal_client_id: "  " })), unknown);
  assert.deepEqual(readPracticeBooks(ok({ internal_client_id: "_placeholder" })), unknown);
});

test("the three answers are three different answers", () => {
  const states = [
    readPracticeBooks(ok({ internal_client_id: "abc" })).state,
    readPracticeBooks(ok({ internal_client_id: null })).state,
    readPracticeBooks(undefined).state,
  ];
  assert.equal(new Set(states).size, 3);
});
