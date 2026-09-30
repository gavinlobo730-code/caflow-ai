// A Supabase Auth error is shown to a CA in plain words, never as the SDK's own
// message.
//
// Run with:
//   node --experimental-strip-types --test scripts/an-auth-error-reaches-the-ca-in-plain-words.test.ts
//
// WHY
//     The production auth log of 27-09-2026 recorded sign-up answered with
//     `over_email_send_rate_limit` ("email rate limit exceeded") and
//     `email_address_invalid` ('Email address "x" is invalid'), and the sign-up
//     page put `otpErr.message` straight on the screen. Onboarding's password
//     step and the reset-password page did the same with `upErr.message`.
//     `lib/auth/authErrorMessage.ts` maps the error's CODE to a sentence.
//
// THE RULE, NOT A SPELLING OF IT
//     Wherever a file destructures `error` out of an awaited Supabase Auth call
//     (`… = await x.auth.<method>(…)`, or the reauth helper that wraps one), the
//     `.message` of that binding may be READ to detect a case
//     (`.message.toLowerCase()`) or LOGGED (inside `otpTrace(…)`), and nowhere
//     else — a `.message` that flows anywhere else is on its way to a screen.
//     The binding is found by its shape, so a new sign-in screen is covered the
//     day it is written.
//
//     STILL_RAW is the frozen list of screens outside the sign-up / sign-in /
//     password-reset path that have not been converted yet. It is asserted as an
//     EQUALITY, so it can only shrink: a fix that leaves its entry behind fails
//     as loudly as a new offender.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const ROOTS = ["app", "lib", "components"];

// Screens not on the sign-up / sign-in path, recorded rather than swept in the
// change that introduced this rule. Remove an entry when its screen is fixed.
const STILL_RAW = new Set<string>([
  "app/clients/[id]/portal/page.tsx otpErr.message",
  "app/platform/page.tsx cErr.message",
  "app/platform/page.tsx fErr.message",
  "app/portal/activate/page.tsx upErr.message",
  "app/portal/employee/activate/page.tsx err.message",
  "app/settings/security/page.tsx upErr.message",
  "components/payroll/PortalAccessModal.tsx otpErr.message",
]);

// The screens a new CA passes through on the way in. These must be clean
// whatever STILL_RAW says.
const SIGN_UP_PATH = [
  "app/signup/page.tsx",
  "app/onboarding/page.tsx",
  "app/login/page.tsx",
  "app/login/forgot-password/page.tsx",
  "app/auth/reset-password/page.tsx",
  "lib/auth/AuthContext.tsx",
];

function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === "node_modules" || e.name.startsWith(".")) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.tsx?$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)) out.push(p);
    }
  };
  for (const r of ROOTS) walk(path.join(WEB, r));
  return out;
}

/** Names bound to the `error` of an awaited Supabase Auth call. */
function authErrorBindings(src: string): string[] {
  const names = new Set<string>();
  const re = /const\s*\{([^}]*)\}\s*=\s*await\s+([^;\n]*)/g;
  for (const m of src.matchAll(re)) {
    const call = m[2];
    if (!/\.auth\.[\w.]*\s*\(|\bsetPasswordWithReauthNonce\s*\(/.test(call)) continue;
    const b = /(?:^|,)\s*error\s*(?::\s*([A-Za-z_$][\w$]*))?\s*(?:,|$)/.exec(m[1].trim());
    if (b) names.add(b[1] ?? "error");
  }
  return [...names];
}

function spansOf(src: string, opener: RegExp): [number, number][] {
  const spans: [number, number][] = [];
  for (const m of src.matchAll(opener)) {
    let depth = 0;
    let i = (m.index ?? 0) + m[0].length - 1;
    for (; i < src.length; i++) {
      if (src[i] === "(") depth++;
      else if (src[i] === ")" && --depth === 0) break;
    }
    spans.push([m.index ?? 0, i]);
  }
  return spans;
}

/** Every `<binding>.message` that is neither a detection nor a log line. */
function rawRenders(src: string): string[] {
  const code = stripComments(src);
  const logged = spansOf(code, /\botpTrace\s*\(/g);
  const found = new Set<string>();
  for (const name of authErrorBindings(code)) {
    const re = new RegExp(`(?<![\\w$.])${name.replace(/\$/g, "\\$")}\\s*\\??\\.\\s*message\\b`, "g");
    for (const m of code.matchAll(re)) {
      const at = m.index ?? 0;
      const after = code.slice(at + m[0].length);
      if (/^\s*\??\.\s*toLowerCase\s*\(/.test(after)) continue;
      if (logged.some(([a, b]) => at > a && at < b)) continue;
      found.add(`${name}.message`);
    }
  }
  return [...found];
}

test("the rule finds bindings and renders in the shapes the product writes", () => {
  const sample = `
    const { error: otpErr } = await supabase.auth.signInWithOtp({ email });
    if (otpErr) throw new Error(otpErr.message);
    const { error } = await getSupabaseClient().auth.signInWithPassword(c);
    return { error: error?.message ?? null };
    const { error: upErr } = await setPasswordWithReauthNonce(supabase.auth, pw, n);
    if (upErr.message.toLowerCase().includes("x")) {}
    otpTrace("t", { message: upErr.message });
    const { data, error: other } = await api.get("/x");
    setError(other.message);
  `;
  assert.deepEqual(authErrorBindings(sample).sort(), ["error", "otpErr", "upErr"]);
  assert.deepEqual(rawRenders(sample).sort(), ["error.message", "otpErr.message"]);
});

test("the sign-up, sign-in and password screens render no raw Supabase Auth message", () => {
  const offenders = SIGN_UP_PATH.flatMap((rel) =>
    rawRenders(fs.readFileSync(path.join(WEB, rel), "utf8")).map((r) => `${rel} ${r}`));
  assert.deepEqual(offenders, []);
});

test("the sign-up path imports the one helper that turns a code into words", () => {
  for (const rel of ["app/signup/page.tsx", "app/onboarding/page.tsx", "app/login/page.tsx",
    "app/auth/reset-password/page.tsx", "lib/auth/AuthContext.tsx"]) {
    const src = stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
    assert.match(src, /from\s+["']@\/lib\/auth\/authErrorMessage["']/, rel);
  }
});

test("no other screen renders a raw Supabase Auth message beyond the frozen list", () => {
  const found = new Set<string>();
  for (const p of sourceFiles()) {
    for (const r of rawRenders(fs.readFileSync(p, "utf8"))) {
      found.add(`${path.relative(WEB, p).split(path.sep).join("/")} ${r}`);
    }
  }
  assert.deepEqual([...found].sort(), [...STILL_RAW].sort());
});
