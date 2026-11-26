// An auth email the browser asked Supabase to send is either sent or the
// screen says why not.
//
// `signInWithOtp` does not THROW when the email fails — it RESOLVES with
// `{ error }`. The Team screen awaited it with `.catch(() => {})` and read
// nothing, so a rate limit, an SMTP refusal or an unauthorised address all
// showed "Invite sent!" and the invitee simply never heard anything.
//
// The rule, over every file rather than the one that broke: a signInWithOtp
// call destructures `error` on the line it is made. The Team-screen half holds
// that the server's answer about its invitation email reaches the modal: since
// POST-A-445 the server sends that email, so the screen sends none of its own.
//
// Run with: node --experimental-strip-types --test scripts/an-auth-email-that-did-not-send-says-so.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const ROOTS = ["app", "components", "lib"].map((d) => path.join(WEB, d));

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sources(full));
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) out.push(full);
  }
  return out;
}

const CALL = /\.signInWithOtp\s*\(/;

function calls() {
  const found: { file: string; line: string }[] = [];
  for (const root of ROOTS) {
    for (const file of sources(root)) {
      const code = stripComments(fs.readFileSync(file, "utf8"));
      for (const line of code.split("\n")) {
        if (CALL.test(line)) found.push({ file: path.relative(WEB, file), line: line.trim() });
      }
    }
  }
  return found;
}

test("the sweep finds the calls it is about", () => {
  const found = calls();
  // POST-A-485: the SERVER mails the sign-up link, so the sign-up form and the wizard no longer call it (the second test below holds that).
  // POST-A-552: the SERVER mails an employee's portal invitation too, and returns its link to nobody, so the payroll dialog no longer
  // calls it either (the test below holds that). What is left is the one screen that mails a client's portal sign-in from the browser.
  assert.ok(found.length >= 1, `only ${found.length} signInWithOtp calls found — bad roots?`);
  assert.ok(found.some((c) => c.file === path.join("app", "clients", "[id]", "portal", "page.tsx")));
});

test("the employee portal dialog mails nothing of its own and holds no link: the server mails the invitation and says whether it went", () => {
  const rel = path.join("components", "payroll", "PortalAccessModal.tsx");
  const src = stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
  // The link signs its holder in as the invitation's address (POST-A-552). A browser-sent sign-in mail needed the link in the browser
  // to come back to, which is how the dialog came to hold it.
  assert.doesNotMatch(src, CALL, `${rel} sends an auth email itself: that needs the invitation's link in the browser`);
  assert.doesNotMatch(src, /activation_url|\.token\b|clipboard/, `${rel} reads the invitation's link or token, or offers something to copy`);
  // What it shows is the server's answer about the mail: only the server's own yes is "sent", and its sentence is shown when it is not.
  assert.match(src, /mail\?\.sent !== true/, `${rel} does not ask the server's answer whether the mail went`);
  assert.match(src, /mail\?\.problem/, `${rel} does not show the server's sentence when the mail did not go`);
});

test("the sign-up form and the wizard mail nothing of their own: the server keeps and mails the sign-up link", () => {
  for (const rel of [path.join("app", "signup", "page.tsx"), path.join("app", "onboarding", "page.tsx"),
    path.join("app", "signup", "continue", "page.tsx")]) {
    const src = stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
    assert.doesNotMatch(src, CALL, `${rel} sends an auth email itself; a second, browser-sent one would be a rival to the server's`);
  }
});

test("every signInWithOtp call reads the error it resolves with", () => {
  const discarded = calls().filter((c) => !/const\s*\{\s*error\b/.test(c.line));
  assert.deepEqual(discarded, [],
    "these signInWithOtp calls do not destructure `error` — a failed email would read as sent");
});

// POST-A-445: the staff invitation is mailed by the SERVER, which answers what the mail service did with it, so the
// Team screen sends no auth email of its own. What it must do is hand the server's answer to the modal: an answer
// that does not say the mail went is never read as sent.
test("the Team screen sends no invitation email itself and hands the server's answer to the modal", () => {
  const page = stripComments(fs.readFileSync(path.join(WEB, "app", "team", "page.tsx"), "utf8"));
  assert.doesNotMatch(page, CALL, "the server mails the invitation; a second, browser-sent email would be a rival");
  assert.doesNotMatch(page, /invite_token/, "the screen never holds the invitation's token");
  assert.doesNotMatch(page, /\.catch\(\s*\(\s*\)\s*=>\s*\{\s*\}\s*\)/,
    "an empty .catch swallows the one failure this screen must report");
  assert.match(page, /invite_mail/);
  assert.match(page, /mail\?\.sent === true \? null :/, "anything but a plain 'sent' is a problem to show");
  assert.match(page, /onInvite:\s*\([^)]*\)\s*=>\s*Promise<InviteOutcome>/);
  assert.match(page, /inviteEmailNotSentMessage\(/);
});
