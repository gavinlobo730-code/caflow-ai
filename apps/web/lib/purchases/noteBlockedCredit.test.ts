import { test } from "node:test";
import assert from "node:assert/strict";
import { blockedCreditFromStored, blockedCreditPayload, blockedCreditProblem, noteLineIsBlocked } from "./noteBlockedCredit.ts";

test("an eligible line sends no new key, so a note with no blocked line is sent as before", () => {
  assert.deepEqual(blockedCreditPayload({}), {});
  assert.deepEqual(blockedCreditPayload({ itc_eligible: true, blocked_credit_reason: "stale" }), {});
});

test("a blocked line sends the mark and its clause", () => {
  assert.deepEqual(blockedCreditPayload({ itc_eligible: false, blocked_credit_reason: " 17_5_b_club_membership " }),
    { itc_eligible: false, blocked_credit_reason: "17_5_b_club_membership" });
});

test("a stored mark comes back for an edit, and a stored eligible line carries none", () => {
  assert.deepEqual(blockedCreditFromStored({ itc_eligible: false, blocked_credit_reason: "other" }),
    { itc_eligible: false, blocked_credit_reason: "other" });
  assert.deepEqual(blockedCreditFromStored({ itc_eligible: true, blocked_credit_reason: null }), {});
  assert.deepEqual(blockedCreditFromStored({}), {});
  assert.equal(noteLineIsBlocked(blockedCreditFromStored({ itc_eligible: false })), true);
});

test("a blocked line with no clause is named, by its number", () => {
  assert.equal(blockedCreditProblem([{}, { itc_eligible: false, blocked_credit_reason: " " }]),
    "Line 2 is marked ITC blocked: choose the section 17(5) clause it is blocked under.");
  assert.equal(blockedCreditProblem([{}, { itc_eligible: false, blocked_credit_reason: "other" }]), null);
});
