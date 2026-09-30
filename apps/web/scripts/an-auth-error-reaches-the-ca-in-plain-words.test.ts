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
//     A binding that is RETHROWN (`if (error) throw error;`) is judged by the
//     catch that receives it: the enclosing try's catch may not render its
//     parameter's `.message`, and a rethrow no try in the file encloses leaves
//     the file still carrying the SDK's words. The binding is found by its
//     shape (one level of nested destructuring included), so a new sign-in
//     screen is covered the day it is written.
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
  // One level of nested braces, so `const { data: { user }, error } = …` is seen.
  const re = /const\s*\{((?:[^{}]|\{[^{}]*\})*)\}\s*=\s*await\s+([^;\n]*)/g;
  for (const m of src.matchAll(re)) {
    const call = m[2];
    if (!/\.auth\.[\w.]*\s*\(|\bsetPasswordWithReauthNonce\s*\(/.test(call)) continue;
    const topLevel = m[1].replace(/\{[^{}]*\}/g, "").trim();
    const b = /(?:^|,)\s*error\s*(?::\s*([A-Za-z_$][\w$]*))?\s*(?:,|$)/.exec(topLevel);
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

function esc(name: string): string {
  return name.replace(/\$/g, "\\$");
}

/** `<name>.message` reads that are neither a detection nor a log line. */
function rawMessageReads(code: string, name: string, from = 0, to = code.length): boolean {
  const logged = spansOf(code, /\botpTrace\s*\(/g);
  const re = new RegExp(`(?<![\\w$.])${esc(name)}\\s*\\??\\.\\s*message\\b`, "g");
  for (const m of code.slice(from, to).matchAll(re)) {
    const at = from + (m.index ?? 0);
    const after = code.slice(at + m[0].length);
    if (/^\s*\??\.\s*toLowerCase\s*\(/.test(after)) continue;
    if (logged.some(([a, b]) => at > a && at < b)) continue;
    return true;
  }
  return false;
}

/** Index of the `}` closing the `{` at `open`. */
function closingBrace(code: string, open: number): number {
  let depth = 0;
  for (let i = open; i < code.length; i++) {
    if (code[i] === "{") depth++;
    else if (code[i] === "}" && --depth === 0) return i;
  }
  return code.length;
}

/**
 * A rethrown auth error reaches the screen through the catch that receives
 * it, so `throw error` is a raw render when the enclosing try's catch reads
 * its parameter's `.message`, or when no try in this file encloses it at all
 * (it leaves the file still carrying the SDK's words).
 */
function rawRethrows(code: string, name: string): boolean {
  const tries: [number, number][] = [];
  for (const m of code.matchAll(/\btry\s*\{/g)) {
    const open = (m.index ?? 0) + m[0].length - 1;
    tries.push([open, closingBrace(code, open)]);
  }
  const throwRe = new RegExp(`\\bthrow\\s+${esc(name)}\\s*(?:;|\\n|\\})`, "g");
  for (const t of code.matchAll(throwRe)) {
    const at = t.index ?? 0;
    const enclosing = tries
      .filter(([a, b]) => at > a && at < b)
      .sort((x, y) => y[0] - x[0])[0];
    if (!enclosing) return true;
    const rest = code.slice(enclosing[1] + 1);
    const c = /^\s*catch\s*(?:\(\s*([A-Za-z_$][\w$]*)[^)]*\))?\s*\{/.exec(rest);
    if (!c) return true;
    if (!c[1]) continue;
    const bodyOpen = enclosing[1] + 1 + c[0].length - 1;
    if (rawMessageReads(code, c[1], bodyOpen, closingBrace(code, bodyOpen))) return true;
  }
  return false;
}

/** Every auth-error binding whose SDK message can reach a screen, and how. */
function rawRenders(src: string): string[] {
  const code = stripComments(src);
  const found = new Set<string>();
  for (const name of authErrorBindings(code)) {
    if (rawMessageReads(code, name)) found.add(`${name}.message`);
    if (rawRethrows(code, name)) found.add(`throw ${name}`);
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

test("a nested destructuring still yields its error binding", () => {
  const sample = `const { data: { user }, error: getErr } = await supabase.auth.getUser();`;
  assert.deepEqual(authErrorBindings(sample), ["getErr"]);
  assert.deepEqual(
    authErrorBindings(`const { data: { session } } = await supabase.auth.getSession();`),
    [],
  );
});

test("a rethrown auth error is judged by the catch that receives it", () => {
  const raw = `
    async function f() {
      try {
        const { error } = await supabase.auth.mfa.enroll({ factorType: "totp" });
        if (error) throw error;
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not start enrolment.");
      }
    }`;
  assert.deepEqual(rawRenders(raw), ["throw error"]);

  const mapped = raw.replace(
    'e instanceof Error ? e.message : "Could not start enrolment."',
    'authErrorMessage(e, "Could not start enrolment.")',
  );
  assert.deepEqual(rawRenders(mapped), []);

  const swallowed = `
    try {
      const { error: verifyErr } = await supabase.auth.verifyOtp(p);
      if (verifyErr) throw verifyErr;
    } catch {
      setStage("invalid");
    }`;
  assert.deepEqual(rawRenders(swallowed), []);

  const inner = `
    try {
      try { x(); } catch (inner) { log(inner.message); }
      const { error } = await supabase.auth.mfa.unenroll(p);
      if (error) throw error;
    } catch (outer) {
      setError(outer.message);
    }`;
  assert.deepEqual(rawRenders(inner), ["throw error"]);

  const escapes = `
    const { error } = await supabase.auth.updateUser(p);
    if (error) throw error;`;
  assert.deepEqual(rawRenders(escapes), ["throw error"]);
});

// Where the visitor may have no password yet, "sign in again" is not
// something they can do. auth-js answers a missing session with
// AuthSessionMissingError from updateUser() AND reauthenticate(), so every
// auth error these screens hand to the generic mapping must first have been
// asked isSessionMissingError(), which routes it to the screen's own sentence.
const NO_PASSWORD_YET = ["app/onboarding/page.tsx", "app/auth/reset-password/page.tsx"];

function unguardedSessionErrors(src: string): string[] {
  const code = stripComments(src);
  const out: string[] = [];
  for (const name of authErrorBindings(code)) {
    const decl = new RegExp(
      name === "error" ? "\\{\\s*error\\s*[,}]" : `\\berror\\s*:\\s*${esc(name)}\\b`, "g");
    const declAt = [...code.matchAll(decl)].map((m) => m.index ?? 0);
    const use = new RegExp(`\\b(?:knownAuthErrorMessage|authErrorMessage)\\s*\\(\\s*${esc(name)}\\s*[,)]`, "g");
    const asked = new RegExp(`\\bisSessionMissingError\\s*\\(\\s*${esc(name)}\\s*\\)`);
    for (const u of code.matchAll(use)) {
      const at = u.index ?? 0;
      const from = Math.max(-1, ...declAt.filter((d) => d < at));
      if (from < 0 || !asked.test(code.slice(from, at))) out.push(name);
    }
  }
  return out;
}

test("the lost-session check sees a mapping with no session question before it", () => {
  const bad = `
    const { error: raErr } = await supabase.auth.reauthenticate();
    if (raErr) throw new Error(knownAuthErrorMessage(raErr) ?? "x");`;
  assert.deepEqual(unguardedSessionErrors(bad), ["raErr"]);
  const good = `
    const { error: raErr } = await supabase.auth.reauthenticate();
    if (raErr && isSessionMissingError(raErr)) throw new Error(MSG);
    if (raErr) throw new Error(knownAuthErrorMessage(raErr) ?? "x");`;
  assert.deepEqual(unguardedSessionErrors(good), []);
  const earlierAskDoesNotCount = `
    const { error: raErr } = await supabase.auth.reauthenticate();
    if (raErr && isSessionMissingError(raErr)) throw new Error(MSG);
    const { error: raErr } = await supabase.auth.reauthenticate();
    if (raErr) throw new Error(knownAuthErrorMessage(raErr) ?? "x");`;
  assert.deepEqual(unguardedSessionErrors(earlierAskDoesNotCount), ["raErr"]);
});

test("a screen reached before any password exists answers a lost session with its own sentence", () => {
  const offenders = NO_PASSWORD_YET.flatMap((rel) =>
    unguardedSessionErrors(fs.readFileSync(path.join(WEB, rel), "utf8")).map((n) => `${rel} ${n}`));
  assert.deepEqual(offenders, []);
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
