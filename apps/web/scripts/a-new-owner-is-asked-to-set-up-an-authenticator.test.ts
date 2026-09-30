// A Partner or Manager with no authenticator is sent to set one up, and never
// meets the backend's bare MFA sentence.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-new-owner-is-asked-to-set-up-an-authenticator.test.ts
//
// WHAT WAS WRONG
//     With REQUIRE_MFA on, mfa_guard refuses an aal1 token for the roles the
//     policy covers on Team, Payroll, Billing, firm Settings and the
//     permissions map. A new owner has no factor, so the sign-in challenge
//     rightly asks for nothing — and onboarding sent them straight to Home,
//     where buttons vanished and Settings showed "Multi-factor authentication
//     required for this action." over a blank form.
//
// THE RULES (the predicate and the translation are unit-tested beside them in
// lib/auth; the backend pins the policy and the exact sentence):
//     1. onboarding decides where it finishes through the enrolment predicate;
//     2. no screen spells the MFA sentence or re-matches it by substring;
//     3. the banner lives in the staff shell, after the bare-route return;
//     4. no permissions answer is applied except through the latest-wins gate.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8");
}
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ").replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, " ");
}
function sources(dir: string): string[] {
  const out: string[] = [];
  const walk = (d: string) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      if (e.name === "node_modules" || e.name.startsWith(".")) continue;
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.tsx?$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)) out.push(p);
    }
  };
  walk(path.join(WEB, dir));
  return out;
}

test("onboarding finishes wherever the enrolment predicate says, never at a spelled destination", () => {
  const src = code(read("app/onboarding/page.tsx"));
  assert.doesNotMatch(src, /["'`]\/\?welcome=1["'`]/,
    "onboarding names its own finishing destination instead of asking onboardingCompletionTarget");
  const finish = src.slice(src.indexOf("async function finish()"));
  const body = finish.slice(0, finish.indexOf("\n  }\n") + 4);
  assert.match(body, /resolveEnrolmentRequired\(\)/, "finish() does not ask whether enrolment is owed");
  assert.match(body, /router\.replace\(onboardingCompletionTarget\(/,
    "finish() does not route through onboardingCompletionTarget");
});

test("no screen spells the MFA refusal or re-derives it by substring", () => {
  const offenders: string[] = [];
  for (const p of [...sources("app"), ...sources("components"), ...sources("lib")]) {
    const rel = path.relative(WEB, p);
    if (rel === path.join("lib", "auth", "mfaRefusal.ts")) continue;
    const src = code(fs.readFileSync(p, "utf8"));
    if (/Multi-factor authentication required/i.test(src)) offenders.push(`${rel}: spells the sentence`);
    if (/\.includes\(\s*["'`](multi-factor|mfa)["'`]\s*\)/i.test(src)) offenders.push(`${rel}: substring match`);
  }
  assert.deepEqual(offenders, [], "the MFA refusal is lib/auth/mfaRefusal.ts's, keyed on the exact sentence");
});

test("the banner is rendered inside the staff shell, never on a bare route", () => {
  const src = code(read("components/AppShell.tsx"));
  const bare = src.indexOf("if (!showShell)");
  const banner = src.indexOf("<SecureAccountBanner");
  assert.ok(bare > 0, "AppShell's bare-route return has moved — re-read this rule");
  assert.ok(banner > bare, "the enrolment banner renders before AppShell drops the shell for portals and sign-in");
  const banners = src.match(/<SecureAccountBanner/g) ?? [];
  assert.equal(banners.length, 1, "one banner, shared by both shells");
});

test("a permissions answer is applied only through the latest-wins gate", () => {
  const src = code(read("lib/auth/AuthContext.tsx"));
  const calls = src.match(/resolvePermissions\(\)[^\n;]*/g) ?? [];
  assert.ok(calls.length >= 2, "expected the permissions map to be resolved in more than one place");
  for (const c of calls) {
    assert.doesNotMatch(c, /\.then\(\s*setPermissions\s*\)/,
      `an out-of-order answer can overwrite a newer one: ${c.trim()}`);
  }
  assert.doesNotMatch(src, /\.then\(\s*setMfaPolicy\s*\)|\.then\(\s*setHasVerifiedFactor\s*\)/,
    "the enrolment facts must be applied latest-wins too");
});
