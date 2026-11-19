// An emailed link that lands already used says so and offers a new one; a new-firm sign-up with an address that
// already has a practice says so and never opens that practice silently; a staff invitation asks for a password and a
// repeat of it is answered.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-link-that-lands-used-or-for-an-existing-practice-says-so.test.ts
//
// WHAT WAS WRONG (POST-A-479, 480, 481; the owner's live test of 18-11-2026)
//     The emailed sign-up link works once, and a second click left the person on an "expired" page that made them type
//     everything again. The owner started a NEW-firm sign-up with an address that already belonged to a Manager of an
//     existing practice and was taken straight into that practice, with no word that it was an existing account. A
//     staff invitation signed the person in and never asked for a password, and a repeat of its accept was refused as
//     a spent token although they had just joined.
//
// POST-A-485 changed the first and the third: the link is now kept by the SERVER and works until it expires or the practice is created
// (scripts/a-sign-up-link-is-the-servers-and-opens-on-its-own-page.test.ts holds that half), so the page that has no sign-in says so
// without claiming that a link "works once".
//
// THE RULES (the decisions are unit-tested beside them in lib/auth)
//     1. the sign-up page keeps the address in the stash (through the one helper) and says the link signs in to an existing account;
//     2. the onboarding page decides through signupLanding(), renders the notice, and its "already onboarded"
//        redirect to "/" is taken ONLY for a member who did not start a sign-up;
//     3. a person with no sign-in on the wizard's page is offered "Email me a new link", from the stashed address and names, with a wait;
//     4. the join page asks for a password with the rules, and offers the dashboard only once one is set (or, for a
//        repeat, a way to say one already exists).
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
function code(rel: string): string {
  const src = fs.readFileSync(path.join(WEB, rel), "utf8");
  return src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ").replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, " ");
}

test("the sign-up page keeps the address beside the names and says the link signs in to an existing account", () => {
  const src = code("app/signup/page.tsx");
  // The stash is written by the one helper every ask goes through, before the request.
  assert.match(src, /requestSignupLink\(\{\s*email, firmName, fullName\s*\}\)/);
  const helper = code("lib/auth/requestSignupLink.ts");
  assert.match(helper, /writeSignupStash\(storage\(\), \{ firmName, fullName, email \}\)/);
  assert.match(src, /If this address already has an account, the link signs you in to it/);
  assert.match(src, /Send it again/);
});

test("the onboarding page decides through signupLanding and shows the notice for a practice that already exists", () => {
  const src = code("app/onboarding/page.tsx");
  assert.match(src, /signupLanding\(\{\s*hasSession: !!session, hasFirm, signupStarted, createdHere\s*\}\)/);
  assert.match(src, /landing === "existing-practice"[\s\S]{0,200}data-existing-practice/);
  assert.match(src, /Sign out and use another address/);
  assert.match(src, /Continue to \$\{existingFirmName\}/);
  assert.match(src, /setCreatedHere\(true\)/);
});

test("the silent redirect to the dashboard is taken only for a member who did not start a sign-up", () => {
  const src = code("app/onboarding/page.tsx");
  // Every router.replace("/") inside checkAlreadyOnboarded is behind landing === "go-home".
  const body = /async function checkAlreadyOnboarded\(\) \{([\s\S]*?)\n    \}\n    checkAlreadyOnboarded\(\)/.exec(src);
  assert.ok(body, "checkAlreadyOnboarded was not found");
  const replaces = body[1].match(/router\.replace\("\/"\)/g) ?? [];
  assert.equal(replaces.length, 1);
  assert.match(body[1], /else if \(landing === "go-home"\) router\.replace\("\/"\)/);
});

test("a person with no sign-in offers a new link from the stashed address and names, with the server's wait, and does not say it works once", () => {
  const src = code("app/onboarding/page.tsx");
  assert.match(src, /You are not signed in/);
  assert.match(src, /canEmailNewLink && \(/);
  assert.match(src, /Email me a new link/);
  assert.match(src, /setLinkWait\(sent\.waitSeconds\)/);
  assert.match(src, /requestSignupLink\(\{ email: stash\.email \?\? "", firmName: stash\.firmName \?\? "", fullName: stash\.fullName \?\? "" \}\)/);
  assert.doesNotMatch(src, /signInWithOtp/);
  assert.doesNotMatch(src, /An emailed link works once/);
});

test("the join page asks for a password with the rules, and the dashboard waits for one", () => {
  const src = code("app/join/page.tsx");
  assert.match(src, /<PasswordRules\b/);
  assert.match(src, /passwordProblem\(pw\)/);
  assert.match(src, /onboardingProgress\.markPasswordSet\(/);
  assert.match(src, /isSamePasswordError\(error\)/);
  // "Go to Dashboard →" is inside the passwordSet branch, never unconditional
  const set = /\{passwordSet && \(([\s\S]*?)\n            \)\}/.exec(src);
  assert.ok(set && /Go to Dashboard/.test(set[1]), "the dashboard button must be inside {passwordSet && (...)}");
  assert.equal((src.match(/Go to Dashboard/g) ?? []).length, 1);
});

test("the join page names a repeat as already joined and carries on", () => {
  const src = code("app/join/page.tsx");
  assert.match(src, /res\.data\.already_joined === true/);
  // Said of the person, never of the practice in the link: a dead token cannot be related to a firm, so "already joined THIS
  // practice" would be untrue for an invitation to another one (found by the independent review).
  assert.match(src, /You are already a member of a practice/);
  assert.doesNotMatch(src, /already joined this practice/);
});

test("the join page always offers the way past the password step, and says what to do when the sign-in is a day old", () => {
  const src = code("app/join/page.tsx");
  assert.doesNotMatch(src, /\{result\?\.alreadyJoined && \(\s*<button/, "the skip is not only for a repeat accept");
  assert.match(src, /I already have a password: go to the dashboard/);
  assert.match(src, /reauthentication_needed/);
  assert.match(src, /Open the invitation link in your email again/);
});
