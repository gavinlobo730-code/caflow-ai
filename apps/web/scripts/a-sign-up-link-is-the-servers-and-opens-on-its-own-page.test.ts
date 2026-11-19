// A sign-up link is kept and mailed by the SERVER, opens on its own page, signs nobody in until a press, and carries what it was asked for
// (POST-A-485, 497).
//
// Run with:
//   node --experimental-strip-types --test scripts/a-sign-up-link-is-the-servers-and-opens-on-its-own-page.test.ts
//
// WHAT WAS WRONG
//     A sign-up link was the sign-in library's own emailed one-time link. The first opener won, so a mail scanner that opens links before the
//     person does, a second click, or the link opened on a phone after the laptop left the person on a page that said it had expired
//     (POST-A-479 only softened the words). And what the link MEANT ("a NEW practice, not the existing one this address belongs to") lived in
//     a note in the browser that had sent the form, so the link opened in another browser entered an existing practice silently (POST-A-497).
//
// THE RULES (the decisions are unit-tested in lib/auth/signupContinue.test.ts; the server's half is apps/api/tests/test_a_sign_up_link_is_held_by_the_server.py)
//     1. the sign-up form, the page a lapsed link lands on and the wizard's "Email me a new link" ask the SERVER, through one helper, and none
//        of them sends an auth email of its own;
//     2. the link opens /signup/continue: it asks what the link is for, signs nobody in by itself, and signs in only at a press;
//     3. what the link was asked for reaches the wizard from the SERVER's answer, and is written BEFORE the sign-in lands;
//     4. a browser signed in as somebody else is asked before it is signed out, the sign-in is asked for BEFORE that session is ended, and
//        it is ended for this device alone (a link that has just expired costs nobody a session, and nobody's other devices);
//     5. every press asks for a fresh sign-in, in a browser signed in as the link's own address too (a session kept from before the practice
//        was closed is refused by the server, and "carrying on" with it did nothing);
//     6. the page shows the names the link was asked for before the press, and an address with no secret in it says it is incomplete and
//        not that the link expired;
//     7. the guard does not bounce a signed-in member from that page, because the page says what to do;
//     8. no call puts the secret in a path.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
function code(rel: string): string {
  return stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
}
/** The text of `async function name(...) {...}` up to the next top-level `}` at the same indent. */
function bodyOf(src: string, name: string): string {
  const start = src.search(new RegExp(`(?:async )?function ${name}\\b`));
  assert.ok(start >= 0, `${name} was not found`);
  const open = src.indexOf("{", src.indexOf(")", start));
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) return src.slice(open, i + 1);
  }
  throw new Error(`${name} has no end`);
}

test("the sign-up form asks the server through the one helper and sends no auth email of its own", () => {
  const src = code("app/signup/page.tsx");
  assert.match(src, /requestSignupLink\(\{\s*email, firmName, fullName\s*\}\)/);
  assert.doesNotMatch(src, /signInWithOtp|getSupabaseClient|emailRedirectTo|authErrorMessage/);
  assert.match(src, /setWaitLeft\(asked\.waitSeconds\)/, "the wait is the server's, not a number of the page's own");
  assert.match(src, /If this address already has an account, the link signs you in to it/);
  assert.doesNotMatch(src, /works once/i, "the link can be opened again, so the page must not say it works once");
});

test("the helper writes the address and both names to the stash before it asks", () => {
  const src = code("lib/auth/requestSignupLink.ts");
  assert.match(src, /writeSignupStash\(storage\(\), \{ firmName, fullName, email \}\)/);
  assert.ok(src.indexOf("writeSignupStash(") < src.indexOf("api.signup.requestLink("), "the stash is written first so a refusal leaves it behind");
  assert.match(src, /throw new Error\(res\.error \?\? /);
});

test("the wizard's new-link button asks the server through the same helper and no longer mails by itself", () => {
  const src = code("app/onboarding/page.tsx");
  const body = bodyOf(src, "emailNewLink");
  assert.match(body, /requestSignupLink\(/);
  assert.match(body, /canAskAgain\(stash\)/);
  assert.doesNotMatch(src, /signInWithOtp/);
  assert.match(src, /You are not signed in/);
  assert.doesNotMatch(src, /An emailed link works once/, "a new link can be opened more than once");
  assert.match(src, /canEmailNewLink && \(/);
});

test("the continue page asks what the link is for when it opens and signs nobody in by itself", () => {
  const src = code("app/signup/continue/page.tsx");
  // The one effect on mount asks; nothing that signs in runs from an effect.
  assert.match(src, /useEffect\(\(\) => \{ void ask\(\); \}, \[ask\]\)/);
  assert.equal((src.match(/api\.signup\.look\(/g) ?? []).length, 1);
  assert.equal((src.match(/api\.signup\.session\(/g) ?? []).length, 1, "the sign-in is asked for in one place");
  assert.equal((src.match(/verifyOtp\(/g) ?? []).length, 1, "and redeemed in the same place");
  const inPress = bodyOf(src, "signInAndCarryOn");
  assert.match(inPress, /api\.signup\.session\(/);
  assert.match(inPress, /verifyOtp\(/);
  for (const effect of src.match(/useEffect\([\s\S]*?\}, \[[^\]]*\]\)/g) ?? []) {
    assert.doesNotMatch(effect, /signInAndCarryOn|verifyOtp|signup\.session/, "an effect must never sign anybody in");
  }
});

test("only a press reaches the sign-in", () => {
  const src = code("app/signup/continue/page.tsx");
  const callers = [...src.matchAll(/signInAndCarryOn\(/g)].length;
  assert.equal(callers, 3, "its definition and the two presses (press, switchAndPress) and nothing else");
  assert.match(bodyOf(src, "press"), /signInAndCarryOn\(/);
  assert.match(bodyOf(src, "switchAndPress"), /signInAndCarryOn\(/);
  assert.match(src, /onClick=\{\(\) => press\(\)\}/);
  assert.match(src, /onClick=\{\(\) => switchAndPress\(\)\}/);
});

test("what the link was asked for reaches the wizard from the server's answer, before the sign-in lands (POST-A-497)", () => {
  const body = bodyOf(code("app/signup/continue/page.tsx"), "signInAndCarryOn");
  const stashed = body.indexOf("writeSignupStash(browserStorage(), stashFrom(res.data))");
  const redeemed = body.indexOf("verifyOtp(");
  assert.ok(stashed >= 0 && redeemed >= 0, "both calls are in the function");
  assert.ok(stashed < redeemed, "the intent is written before the session exists, so the wizard finds it when it opens");
  assert.match(body, /router\.replace\("\/onboarding"\)/);
  assert.match(body, /if \(error\) throw new Error\(COULD_NOT_SIGN_IN\)/);
});

test("every press asks for a fresh sign-in, in a browser already signed in as the link's own address too", () => {
  const src = code("app/signup/continue/page.tsx");
  assert.doesNotMatch(src, /pressFor|carry_on|alreadyThisAddress/, "a browser signed in as the link's address used to 'carry on' with a session that signed nobody in");
  assert.match(bodyOf(src, "press"), /signInAndCarryOn\(false\)/);
  assert.doesNotMatch(bodyOf(src, "press"), /router\./, "a press goes through the sign-in and nothing shorter");
  assert.doesNotMatch(bodyOf(src, "signInAndCarryOn"), /router\.replace\("\/onboarding"\);\s*return;/, "there is one way on, and it signs in");
  const signup = code("lib/auth/signupContinue.ts");
  assert.doesNotMatch(signup, /pressFor/, "the rule that chose 'carry on' is gone with the behaviour");
});

test("a browser signed in as somebody else is asked first, and its session is ended AFTER the sign-in is in hand and for this device only", () => {
  const src = code("app/signup/continue/page.tsx");
  assert.match(src, /view === "other_account"/);
  assert.match(src, /Sign out and continue as/);
  assert.match(src, /Stay signed in as/);
  assert.match(bodyOf(src, "switchAndPress"), /signInAndCarryOn\(true\)/);
  const body = bodyOf(src, "signInAndCarryOn");
  const asked = body.indexOf("api.signup.session(");
  const ended = body.indexOf("await endSessionHere()");
  const redeemed = body.indexOf("verifyOtp(");
  assert.ok(asked >= 0 && ended >= 0 && redeemed >= 0, "all three are in the function");
  assert.ok(asked < ended, "the sign-in is asked for before anybody is signed out: a link that has just expired costs nobody their session");
  assert.ok(ended < redeemed, "and the session is ended before the new one is redeemed");
  assert.match(body, /if \(endThisBrowsersSession\) await endSessionHere\(\)/);
  // The context's `signOut` ends the account's sessions on EVERY device; `endSessionHere` ends this one.
  assert.doesNotMatch(src, /\bsignOut\b/, "the page must not use the sign-out that ends every device");
  assert.match(src, /const \{ session, endSessionHere \} = useAuth\(\)/);
});

test("the ready page shows the firm's name and the person's name the link was asked for, before the press", () => {
  const src = code("app/signup/continue/page.tsx");
  const ready = src.slice(src.indexOf('view === "ready"'), src.indexOf('view === "other_account"'));
  assert.match(ready, /looked\.seen\.firm_name/);
  assert.match(ready, /looked\.seen\.full_name/);
  assert.match(ready, /looked\.seen\.email/);
  assert.match(ready, /nothing is created until you finish them/, "what pressing starts is said in words");
});

test("an address with no secret in it says it is incomplete and does not claim the link expired", () => {
  const src = code("app/signup/continue/page.tsx");
  const body = bodyOf(src, "lookAtLink");
  assert.match(body, /if \(!token\) return \{ state: "incomplete" \}/);
  assert.doesNotMatch(body, /if \(!token\) return \{ state: "gone" \}/);
  assert.match(src, /This sign-up link is incomplete/);
  assert.match(src, /missing the part after the # sign/);
  assert.match(src, /data-signup-continue-incomplete/);
});

test("a link that cannot be used says so in one sentence and offers a new one only where this browser kept the address and names", () => {
  const src = code("app/signup/continue/page.tsx");
  assert.match(src, /This sign-up link is no longer active/);
  assert.match(src, /canAskAgain\(stash\)/);
  assert.match(src, /requestSignupLink\(/);
  assert.match(src, /Email me a new link/);
  assert.match(src, /LINK_NOT_ACTIVE\.test\(message\)/);
  assert.match(src, /setWaitLeft\(sent\.waitSeconds\)/);
});

test("every outcome the page can reach is a view, so no state is left blank", () => {
  const src = code("app/signup/continue/page.tsx");
  for (const view of ["checking", "ready", "other_account", "gone", "incomplete", "problem"]) {
    assert.match(src, new RegExp(`view === "${view}"`), view);
  }
  assert.match(src, /Try again/);
});

test("the guard leaves a signed-in member on the page a sign-up link opens", () => {
  const guard = code("lib/auth/AuthGuard.tsx");
  assert.match(guard, /const onSignup = isSignupFormPath\(pathname\)/);
  assert.doesNotMatch(guard, /pathname\.startsWith\("\/signup\/"\)/, "the old prefix test would bounce the link's page too");
});

test("the secret is read from the fragment of the address, which no server or log sees, and never from a query", () => {
  const src = code("app/signup/continue/page.tsx");
  assert.match(src, /new URLSearchParams\(window\.location\.hash\.replace\(\/\^#\/, ""\)\)\.get\("token"\)/);
  assert.match(src, /const \[token\] = useState\(tokenFromAddress\)/);
  assert.doesNotMatch(src, /useSearchParams|location\.search/, "a query reaches the static host's log, a scanner's log and every Referer");
});

test("the three calls are on one object, the secret is in a body and the question is a named read", () => {
  const src = code("lib/api/index.ts");
  const start = src.indexOf("  signup: {");
  assert.ok(start >= 0);
  const block = src.slice(start, src.indexOf("  identity: {", start));
  assert.match(block, /"\/api\/signup\/link", \{ method: "POST", body: JSON\.stringify\(body\) \}/);
  assert.match(block, /"\/api\/signup\/link\/look", \{ method: "POST", body: JSON\.stringify\(\{ token \}\), asked: "read" \}/);
  assert.match(block, /"\/api\/signup\/link\/session", \{ method: "POST", body: JSON\.stringify\(\{ token \}\) \}/);
  assert.doesNotMatch(block, /\$\{token\}|\?token=/, "a secret in a path or a query reaches every access log");
});
