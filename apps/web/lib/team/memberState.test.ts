import { test } from "node:test";
import assert from "node:assert/strict";
import {
  countsAsActive, hasJoined, memberBadge, memberState, offersResend, resendNotice, switchActionLabel,
} from "./memberState.ts";

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

// POST-A-445: Resend invite is offered to somebody still waiting to join, and what came of it is the server's answer.
test("resend is offered for a live or lapsed invitation and for nobody else", () => {
  assert.equal(offersResend({ member_state: "invited" }), true);
  assert.equal(offersResend({ member_state: "invite_expired" }), true);
  assert.equal(offersResend({ member_state: "active" }), false);
  assert.equal(offersResend({ member_state: "inactive" }), false, "a withdrawn invitation is switched back on first");
  assert.equal(offersResend({}), false, "a row the server said nothing about is not offered a resend");
});

test("a resend that went says the earlier link stopped working and until when the new one works", () => {
  const n = resendNotice("Nitin", "nitin@firm.in",
    { invite_mail: { sent: true, problem: null }, invite_expires_at: "2026-11-23T00:48:00Z" }, () => "23 Nov 2026");
  assert.equal(n.tone, "ready");
  assert.equal(n.text, "A new invitation went to nitin@firm.in. The link in any earlier email no longer works. It can be used until 23 Nov 2026.");
});

test("a resend whose mail did not go, or whose answer says nothing, is never read as sent", () => {
  const failed = resendNotice("Nitin", "nitin@firm.in", { invite_mail: { sent: false, problem: "The mail service did not accept it." } }, String);
  assert.equal(failed.tone, "problem");
  assert.match(failed.text, /did not go, and the link in any earlier email no longer works\. The mail service did not accept it\.$/);
  const silent = resendNotice("Nitin", "nitin@firm.in", {}, String);
  assert.equal(silent.tone, "problem");
  assert.match(silent.text, /The server did not say whether the email went\.$/);
});

test("a resend whose mail did not go and whose earlier invitation was kept says the earlier link still works", () => {
  const n = resendNotice("Nitin", "nitin@firm.in",
    { invite_mail: { sent: false, problem: "The mail service did not accept it.", kept_previous: true } }, String);
  assert.equal(n.tone, "problem");
  assert.match(n.text, /earlier invitation was kept: the link in it still works until it expires\. The mail service did not accept it\.$/);
  assert.doesNotMatch(n.text, /no longer works/);
});
