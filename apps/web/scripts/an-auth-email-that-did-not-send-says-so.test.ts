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
  assert.ok(found.length >= 3, `only ${found.length} signInWithOtp calls found — bad roots?`);
  assert.ok(found.some((c) => c.file === path.join("app", "signup", "page.tsx")));
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
