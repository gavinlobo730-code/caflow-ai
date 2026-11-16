// A staff invitation is the SERVER's: it is mailed by the server, sent again by the server, and its link signs the
// invitee in by itself (POST-A-445).
//
// The Team screen used to receive the invitation's token and ask Supabase to mail an ordinary sign-in link from the
// Partner's browser. The mail named neither the practice nor the Partner, lasted only as long as Supabase keeps a
// one-time code, and nothing could send it again. These hold the browser half from the source: the screen never holds
// the token and sends no mail of its own, Resend invite goes to the server, the join page opens the sign-in from the
// invitation's own link, and it signs somebody else out only from a button they pressed.
//
// Run with: node --experimental-strip-types --test scripts/a-staff-invitation-is-the-servers-and-its-link-signs-in-by-itself.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

const TEAM = read("app/team/page.tsx");
const JOIN = read("app/join/page.tsx");
const API = read("lib/api/index.ts");

test("the Team screen never holds the invitation's token and asks Supabase to mail nothing", () => {
  assert.doesNotMatch(TEAM, /invite_token/);
  assert.doesNotMatch(TEAM, /signInWithOtp/);
  assert.doesNotMatch(TEAM, /\/join\?token=/, "the screen builds no join link: the server's mail carries it");
});

test("Resend invite is the server's, offered by the server's state, and a second press sends nothing", () => {
  assert.match(TEAM, /api\.identity\.resendInvite\(member\.id\)/);
  assert.match(TEAM, /offersResend\(member\)/);
  assert.match(TEAM, /if \(resending\) return;/);
  assert.match(API, /resendInvite: \(userId: string\) =>\s*request<ApiResp<InvitedMember>>\(`\/api\/identity\/users\/\$\{userId\}\/resend-invite`, \{ method: "POST" \}\)/);
});

test("a withdraw or an activate reads the list again instead of patching the badge", () => {
  const handler = TEAM.slice(TEAM.indexOf("async function handleDeactivate"), TEAM.indexOf("// Summary counts"));
  assert.ok(handler.length > 50, "handleDeactivate was not found");
  assert.match(handler, /await loadTeam\(\)/);
  assert.doesNotMatch(handler, /setMembers\(/, "a local patch kept a withdrawn invitation showing Invited");
});

test("the join page opens the sign-in from the invitation's own link and redeems it", () => {
  assert.match(JOIN, /api\.identity\.inviteSession\(token\)/);
  assert.match(JOIN, /\.verifyOtp\(\{\s*token_hash: signIn\.token_hash,/);
  assert.match(JOIN, /api\.identity\.acceptInvite\(token\)/);
  assert.deepEqual([...JOIN.matchAll(/searchParams\.get\("([^"]+)"\)/g)].map((m) => m[1]), ["token"],
    "the join page reads nothing but the token from the URL: who the invitee is and where they join come from the server");
  assert.match(API, /"\/api\/identity\/accept-invite\/session"/);
});

// A mail scanner that opens links and runs their scripts would otherwise sign in, accept and use the invitation up.
test("signed out, the page signs nobody in by itself: it waits for a press", () => {
  const journey = JOIN.slice(JOIN.indexOf("async function join(token"), JOIN.indexOf("async function joinSignedOut"));
  assert.ok(journey.length > 100, "the page's own journey was not found");
  const ready = journey.indexOf('if (!session) return { kind: "ready" };');
  assert.ok(ready > 0, "a signed-out visit must stop and wait for a press");
  assert.doesNotMatch(journey, /verifyOtp|signInWith\(/, "the page's own journey signs somebody in");
  assert.doesNotMatch(journey, /openSignIn\(/, "the page's own journey opens a sign-in: merely looking must create nothing");
  assert.match(journey, /api\.identity\.inviteAddress\(token\)/);
  assert.match(JOIN, /onClick=\{\(\) => joinNow\(\)\}/);
});

test("the join page signs somebody else out only from the button they pressed, then opens a fresh sign-in", () => {
  const calls = [...JOIN.matchAll(/\bsignOut\(\)/g)].map((m) => m.index ?? 0);
  assert.equal(calls.length, 1, `signOut() should be called in one place, found ${calls.length}`);
  const switchFn = JOIN.indexOf("function switchAndJoin");
  assert.ok(switchFn > 0 && calls[0] > switchFn, "signOut() is called outside switchAndJoin");
  const body = JOIN.slice(switchFn, JOIN.indexOf("async function goToDashboard"));
  assert.ok(body.indexOf("signOut()") < body.indexOf("joinSignedOut(token)"),
    "the sign-in must be opened after the sign-out, not reused from before it");
  assert.match(JOIN, /onClick=\{\(\) => switchAndJoin\(\)\}/);
});

test("after joining, the membership is read again before the dashboard", () => {
  assert.match(JOIN, /void refreshUserContext\(\);/);
  assert.match(JOIN, /async function goToDashboard\(\) \{\s*await refreshUserContext\(\);\s*router\.replace\("\/"\);/);
});
