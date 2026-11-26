// Every screen that sets a password shows the rules, checks them before it sends
// anything, and the sign-up wizard keeps its place when the sign-in service
// announces the change.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-password-screen-shows-its-rules-and-keeps-its-place.test.ts
//
// WHAT WAS WRONG (POST-A-477, POST-A-478; the owner's live test of 18-11-2026)
//     The sign-in service refuses a password without a lowercase letter, a
//     capital, a digit and a symbol, and every password screen said only "At
//     least 10 characters" and checked only the length, so a person was refused
//     for a rule they were never shown (422, no error code). And saving the
//     password made AuthGuard unmount the sign-up wizard for a round trip, so it
//     came back at step 1, empty, having just saved the password, with no way
//     forward: the same password is refused as the same password.
//
// THE RULES (the rule list and the store are unit-tested beside them in lib/auth)
//     1. a page that calls updateUser({ password … }) checks passwordProblem()
//        and renders <PasswordRules> — the RULE, found by what the page does,
//        not by a list of pages, so a fifth password screen cannot skip it;
//     2. no page checks a password's length by hand (`pw.length <`): that is
//        the one rule the service does not stop at;
//     3. the sign-up wizard's memory (password set, firm created, a code pending) lives in the progress store,
//        is written before the wizard moves on, is read on mount through restoredStep() (whose behaviour is
//        unit-tested in lib/auth), and is cleared when the wizard finishes;
//     4. a same-password refusal on the wizard is "already set", never an error, on the direct path and on the
//        emailed-code path;
//     5. the aria-describedby of a password box names a rules block that is rendered.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ").replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, " ");
}
function pages(dir: string): string[] {
  const out: string[] = [];
  const walk = (d: string) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      if (e.name === "node_modules" || e.name.startsWith(".")) continue;
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.(tsx|ts)$/.test(e.name) && !/\.test\./.test(e.name)) out.push(p);
    }
  };
  walk(dir);
  return out;
}

// A screen that saves a password calls updateUser({ password ... }) itself or through the helper that adds the nonce.
const SETS_A_PASSWORD = /updateUser\(\s*\{\s*password\b|setPasswordWithReauthNonce\(/;
const setters = [...pages(path.join(WEB, "app")), ...pages(path.join(WEB, "components"))]
  .map((f) => ({ rel: path.relative(WEB, f), src: code(fs.readFileSync(f, "utf8")) }))
  .filter((f) => SETS_A_PASSWORD.test(f.src));

test("the finder sees the five screens that set a password, so the rules below are not vacuous", () => {
  const rels = setters.map((s) => s.rel).sort();
  for (const must of [
    "app/onboarding/page.tsx",
    "app/auth/reset-password/page.tsx",
    "app/portal/activate/page.tsx",
    "app/portal/employee/activate/page.tsx",
    "app/settings/security/page.tsx",
  ]) {
    assert.ok(rels.includes(must), `${must} no longer calls updateUser({ password }) — update this guard if it moved`);
  }
});

test("every screen that sets a password checks the rules and shows them", () => {
  const bad: string[] = [];
  for (const s of setters) {
    if (!/passwordProblem\(/.test(s.src)) bad.push(`${s.rel} does not check passwordProblem() before it sends`);
    if (!/<PasswordRules\b/.test(s.src)) bad.push(`${s.rel} does not render <PasswordRules>`);
  }
  assert.deepEqual(bad, []);
});

test("no screen that sets a password checks its length by hand", () => {
  const bad = setters.filter((s) => /\b(?:pw|next|password)\.length\s*</.test(s.src)).map((s) => s.rel);
  assert.deepEqual(bad, []);
});

test("the wizard keeps its memory in the store, writes it before it moves on, restores through restoredStep, and clears at the end", () => {
  const src = code(fs.readFileSync(path.join(WEB, "app/onboarding/page.tsx"), "utf8"));
  assert.match(src, /useSyncExternalStore\(\s*onboardingProgress\.subscribe\s*,\s*onboardingProgress\.get/);
  // the step is SEEDED from the memory (no frame of step 1) and RESTORED by the effect, both through the pure rule
  assert.ok((src.match(/restoredStep\(/g) ?? []).length >= 2, "restoredStep must seed the step and drive the restore effect");
  // each thing the person has done is written to the store
  assert.match(src, /function rememberPasswordSet\(\)\s*\{[\s\S]*?onboardingProgress\.markPasswordSet\(/);
  assert.match(src, /onboardingProgress\.markFirmCreated\(/);
  assert.match(src, /onboardingProgress\.markReauthPending\(/);
  // ... before the page goes on, on every success path (direct, same password, emailed code)
  const successPaths = src.match(/rememberPasswordSet\(\);\s*goNext\(\);/g) ?? [];
  assert.ok(successPaths.length >= 3, `rememberPasswordSet(); goNext(); expected on the direct save, the same-password answer and the code-verified save, found ${successPaths.length}`);
  // the memory is dropped when the wizard finishes
  assert.match(src, /async function finish\(\)[\s\S]*?onboardingProgress\.clear\(\)/);
});

test("a same-password answer is treated as already set on the direct path and on the emailed-code path", () => {
  const src = code(fs.readFileSync(path.join(WEB, "app/onboarding/page.tsx"), "utf8"));
  const guards = src.match(/isSamePasswordError\(upErr\)/g) ?? [];
  assert.ok(guards.length >= 2, `isSamePasswordError(upErr) expected on both paths, found ${guards.length}`);
});

test("the first step's button is decided by lib/auth/passwordStep, whose behaviour is unit-tested", () => {
  const src = code(fs.readFileSync(path.join(WEB, "app/onboarding/page.tsx"), "utf8"));
  assert.match(src, /passwordStepMode\(\{/);
  assert.match(src, /passwordStepButtonEnabled\(\{/);
});

test("the aria-describedby of a password box names a rules block the screen renders", () => {
  const bad: string[] = [];
  for (const s of setters) {
    const rendered = new Set([...s.src.matchAll(/<PasswordRules\b[^>]*\bid="([^"]+)"/g)].map((m) => m[1]));
    // The attribute may be a plain string or an expression; the id it names is the "...-rules" string just after it.
    for (const m of s.src.matchAll(/aria-describedby=/g)) {
      const near = s.src.slice(m.index!, m.index! + 160);
      const id = /"([a-z0-9-]+-rules)"/.exec(near)?.[1];
      if (!id) { bad.push(`${s.rel}: an aria-describedby that names no "...-rules" id`); continue; }
      if (!rendered.has(id)) bad.push(`${s.rel}: aria-describedby="${id}" names no rendered <PasswordRules id>`);
    }
  }
  assert.deepEqual(bad, []);
});
