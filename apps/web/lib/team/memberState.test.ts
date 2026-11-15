import { test } from "node:test";
import assert from "node:assert/strict";
import { countsAsActive, hasJoined, memberBadge, memberState, switchActionLabel } from "./memberState.ts";

// PRE-A-020. A staff invitation creates the member's row before they sign in, and the Team screen read
// `is_active` alone, so a member who had never accepted showed as Active. The server now says which of four
// states a member is in; this module only words it, and it never turns an invitation into "Active".

const day = (iso: string) => `D(${iso.slice(0, 10)})`;

test("an outstanding invitation is Invited, with the day its link stops working, never Active", () => {
  const row = { member_state: "invited", is_active: true, invite_expires_at: "2026-11-22T21:00:00+00:00" };
  assert.deepEqual(memberBadge(row, day), { label: "Invited · link valid until D(2026-11-22)", tone: "attention" });
  assert.equal(countsAsActive(row), false);
  assert.equal(hasJoined(row), false);
  assert.equal(switchActionLabel(row), "Withdraw invite");
});

test("an invitation past its expiry is Invite expired and is not counted", () => {
  const row = { member_state: "invite_expired", is_active: true };
  assert.deepEqual(memberBadge(row, day), { label: "Invite expired", tone: "attention" });
  assert.equal(countsAsActive(row), false);
  assert.equal(hasJoined(row), false);
});

test("a member who accepted is Active and counts", () => {
  const row = { member_state: "active", is_active: true, auth_user_id: "u" };
  assert.deepEqual(memberBadge(row, day), { label: "Active", tone: "ready" });
  assert.equal(countsAsActive(row), true);
  assert.equal(hasJoined(row), true);
  assert.equal(switchActionLabel(row), "Deactivate");
});

test("a deactivated colleague joined; a withdrawn invitation never did", () => {
  const colleague = { member_state: "inactive", is_active: false, auth_user_id: "u" };
  const withdrawn = { member_state: "inactive", is_active: false, auth_user_id: null };
  assert.equal(memberBadge(colleague, day).label, "Inactive");
  assert.equal(countsAsActive(colleague), false);
  assert.equal(hasJoined(colleague), true);
  assert.equal(hasJoined(withdrawn), false);
  assert.equal(switchActionLabel(colleague), "Activate");
});

test("a row the server said nothing about is not guessed at: a dash, and the old flag for the counts", () => {
  const older = { is_active: true };
  assert.equal(memberState(older), null);
  assert.deepEqual(memberBadge(older, day), { label: "—", tone: "unknown" });
  assert.equal(countsAsActive(older), true);
  assert.equal(countsAsActive({ is_active: false }), false);
  assert.equal(memberState({ member_state: "promoted" }), null);
});
