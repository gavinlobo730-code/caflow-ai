// The staff portal screen goes through the API, so the server can tell the
// client — and it shows the firm who has written. Run with:
//   node --experimental-strip-types --test scripts/the-portal-screen-tells-the-client-and-the-firm.test.ts
//
// WHY THIS EXISTS (practice_management-02 and -03)
//     The screen created a document request by inserting `document_requests`
//     STRAIGHT OVER POSTGREST, because the API door for it named a column the
//     table never had and failed on every call (migration 450 repaired it). A
//     write the browser makes itself is a write the server cannot send a mail
//     for and rbac() never saw, so "tell the client" had nowhere to live. It is
//     the rule — no direct write of this table from this screen — and not a
//     spelling of the call that is asserted here.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PORTAL = "app/client-portal/page.tsx";
const PANEL = "components/notifications/EmailPreferencesPanel.tsx";
const NOTIFICATIONS = "app/notifications/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the portal screen does not write document_requests itself", () => {
  const src = code(PORTAL);
  const writes = [...src.matchAll(/\.from\(\s*"document_requests"\s*\)\s*\.\s*(insert|upsert|update)\b/g)];
  assert.deepEqual(writes.map((m) => m[0]), [],
    "creating a request must go through POST /api/portal/document-requests — the " +
    "server is what mails the client and what puts rbac() in front of the write");
  assert.match(src, /api\.portal\.createDocumentRequest\(/);
});

test("a created request or a sent message says whether the CLIENT was told", () => {
  const src = code(PORTAL);
  assert.match(src, /client_notice/, "the server's answer about the client is read");
  assert.match(src, /was not emailed/,
    "created and 'the client knows' are two facts; the CA is told when only the first is true");
});

test("the firm-wide unread count is shown, and opening a thread clears it", () => {
  const src = code(PORTAL);
  assert.match(src, /api\.portal\.unreadMessages\(/, "the count is the server's");
  assert.match(src, /api\.portal\.markThreadRead\(/, "reading a thread is what clears it");
  assert.match(src, /unread client message/);
});

test("the unread payload is checked before it is read as a list", () => {
  const src = code(PORTAL);
  assert.match(src, /arrayOrEmpty<PortalUnreadSummary/,
    "a field that is not a list must not reach a .map");
});

test("a notification's link can open the thread it is about", () => {
  const src = code(PORTAL);
  assert.match(src, /new URLSearchParams\(window\.location\.search\)/);
  assert.match(src, /q\.get\("client"\)/);
  assert.match(src, /q\.get\("tab"\)/);
});

test("the email settings are served, not spelled", () => {
  const src = code(PANEL);
  assert.match(src, /api\.notifications\.emailPreferences\(/);
  assert.match(src, /api\.notifications\.setEmailPreference\(/);
  assert.match(src, /api\.notifications\.emailLog\(/,
    "what was sent is shown beside the switches");
  // The vocabulary is the server's (domain/practice_notices): no event name is
  // written into this file.
  for (const event of ["task_assigned", "task_overdue", "compliance_deadline", "escalation", "portal_message"]) {
    assert.doesNotMatch(src, new RegExp(`["']${event}["']`),
      `${event} is a server-owned event type`);
  }
});

test("the notifications screen offers the email settings", () => {
  const src = code(NOTIFICATIONS);
  assert.match(src, /EmailPreferencesPanel/);
});
