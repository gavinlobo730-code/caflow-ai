// node --experimental-strip-types --test lib/auth/authErrorMessage.test.ts
//
// The codes below are the ones Supabase Auth actually sends — the union in
// @supabase/auth-js lib/error-codes.d.ts — and the two the production auth log
// recorded on 27-09-2026 against sign-up (over_email_send_rate_limit, 429, and
// email_address_invalid, 400) are asserted with the exact message the SDK
// carried, because that message is what the CA used to see.
import test from "node:test";
import assert from "node:assert/strict";
import {
  authErrorMessage,
  knownAuthErrorMessage,
  AUTH_ERROR_SENTENCES,
  PASSWORD_BREACHED,
  inviteEmailNotSentMessage,
} from "./authErrorMessage.ts";

// The shape of an AuthApiError as auth-js builds it: an Error with code/status.
function authApiError(message: string, status: number, code?: string) {
  const e = new Error(message) as Error & { status: number; code?: string; __isAuthError: true };
  e.name = "AuthApiError";
  e.status = status;
  if (code) e.code = code;
  e.__isAuthError = true;
  return e;
}

test("the email rate limit Supabase answered sign-up with becomes a sentence a CA can act on", () => {
  const raw = authApiError("email rate limit exceeded", 429, "over_email_send_rate_limit");
  const shown = authErrorMessage(raw);
  assert.notEqual(shown, "email rate limit exceeded");
  assert.match(shown, /too many/i);
  assert.match(shown, /last hour/i);
  // The limit is the app's, not the address's: a first-time sign-up can hit it.
  assert.doesNotMatch(shown, /this address/i);
});

test("an address Supabase refuses is not shown as the SDK's quoted string", () => {
  const raw = authApiError('Email address "x" is invalid', 400, "email_address_invalid");
  const shown = authErrorMessage(raw);
  assert.doesNotMatch(shown, /"x"/);
  assert.match(shown, /email address/i);
  assert.match(shown, /check it/i);
});

test("every mapped code is a real auth-js ErrorCode, so a typo cannot silently never match", async () => {
  const { readFileSync, realpathSync } = await import("node:fs");
  const { join, dirname } = await import("node:path");
  const { createRequire } = await import("node:module");
  const require = createRequire(join(process.cwd(), "package.json"));
  const supabaseJs = dirname(require.resolve("@supabase/supabase-js/package.json"));
  const requireFromSupabase = createRequire(join(realpathSync(supabaseJs), "package.json"));
  const authJs = dirname(requireFromSupabase.resolve("@supabase/auth-js/package.json"));
  const union = readFileSync(join(authJs, "dist/module/lib/error-codes.d.ts"), "utf8");
  const known = new Set([...union.matchAll(/'([a-z_]+)'/g)].map((m) => m[1]));
  assert.ok(known.size > 50, "the ErrorCode union was not read");
  for (const code of Object.keys(AUTH_ERROR_SENTENCES)) {
    assert.ok(known.has(code), `${code} is not an auth-js ErrorCode`);
  }
});

test("the rest of the codes the sign-up and password screens meet each have their own sentence", () => {
  const cases: [string, number, RegExp][] = [
    ["over_request_rate_limit", 429, /too many attempts/i],
    ["otp_expired", 403, /expired/i],
    ["same_password", 422, /different from your current/i],
    ["reauthentication_not_valid", 400, /code is incorrect or has expired/i],
    ["reauthentication_needed", 400, /confirm it is you/i],
    ["invalid_credentials", 400, /email or password is incorrect/i],
    ["email_not_confirmed", 400, /confirm your email/i],
    ["session_expired", 403, /session has ended/i],
    ["mfa_verification_failed", 422, /code is incorrect.*authenticator app/i],
    ["mfa_challenge_expired", 422, /too late.*authenticator app/i],
  ];
  for (const [code, status, want] of cases) {
    assert.match(authErrorMessage(authApiError(`raw ${code}`, status, code)), want, code);
  }
});

test("AuthSessionMissingError carries no code and is still recognised by its name", () => {
  const e = new Error("Auth session missing!");
  e.name = "AuthSessionMissingError";
  assert.match(authErrorMessage(e), /session has ended/i);
});

test("a lost session is not answered with sign-in alone, because some screens have no password yet", () => {
  // auth-js raises AuthSessionMissingError from reauthenticate() and turns a
  // server session_not_found into it, on onboarding and reset-password too.
  const missing = new Error("Auth session missing!");
  missing.name = "AuthSessionMissingError";
  for (const err of [missing, authApiError("Session not found", 403, "session_not_found")]) {
    const shown = authErrorMessage(err);
    assert.match(shown, /fresh link/i);
    assert.doesNotMatch(shown, /^[^.]*\. Please sign in again\.$/);
  }
});

// auth-js AuthWeakPasswordError: code weak_password, the server's own message,
// and `reasons` naming which rule failed ("length" | "characters" | "pwned").
function weakPassword(message: string, reasons: string[]) {
  const e = authApiError(message, 422, "weak_password") as ReturnType<typeof authApiError> & { reasons: string[] };
  e.name = "AuthWeakPasswordError";
  e.reasons = reasons;
  return e;
}

test("a password missing a required character group is told which groups, from the groups the server names", () => {
  const server =
    "Password should contain at least one character of each: abcdefghijklmnopqrstuvwxyz, ABCDEFGHIJKLMNOPQRSTUVWXYZ, 0123456789.";
  assert.equal(
    authErrorMessage(weakPassword(server, ["characters"])),
    "Your password needs a lowercase letter, a capital letter and a digit.",
  );
});

// The refusal as the live sign-in log recorded it on 18-11-2026 (PUT /user, 422): NO error code.
const LIVE_CHARACTERS_REFUSAL =
  "Password should contain at least one character of each: abcdefghijklmnopqrstuvwxyz, ABCDEFGHIJKLMNOPQRSTUVWXYZ, 0123456789, !@#$%^&*()_+-=[]{};'\\:\"|<>?,./`~.";

test("the character-group refusal that arrives with no code is worded in plain English too (POST-A-477)", () => {
  const raw = authApiError(LIVE_CHARACTERS_REFUSAL, 422);
  const shown = authErrorMessage(raw);
  assert.equal(shown, "Your password needs a lowercase letter, a capital letter, a digit and a symbol (for example ! @ # $ %).");
  assert.doesNotMatch(shown, /abcdefghij|ABCDEFGH|0123456789/);
});

test("the same refusal with the code the SDK adds for a weak password is worded the same way", () => {
  const shown = authErrorMessage(weakPassword(LIVE_CHARACTERS_REFUSAL, ["characters"]));
  assert.equal(shown, "Your password needs a lowercase letter, a capital letter, a digit and a symbol (for example ! @ # $ %).");
});

test("a character-group refusal that names groups in words is worded from those words", () => {
  const raw = authApiError("Password should contain at least one character of each: lowercase, uppercase, digit, symbol", 422);
  assert.equal(authErrorMessage(raw), "Your password needs a lowercase letter, a capital letter, a digit and a symbol (for example ! @ # $ %).");
});

test("a character-group refusal that names nothing it recognises still says what kind of problem it is", () => {
  const raw = authApiError("Password should contain at least one character of each: group one, group two", 422);
  assert.match(authErrorMessage(raw), /at least one character from each group/i);
});

test("a same-password refusal, as the live log recorded it, is the plain sentence", () => {
  const raw = authApiError("New password should be different from the old password.", 422, "same_password");
  assert.equal(authErrorMessage(raw), AUTH_ERROR_SENTENCES.same_password);
});

test("a password that is too short is told the minimum length the server asked for", () => {
  const shown = authErrorMessage(weakPassword("Password should be at least 12 characters.", ["length"]));
  assert.equal(shown, "Use at least 12 characters.");
  assert.match(authErrorMessage(weakPassword("", ["length"])), /too short/i);
});

test("a password found in a breach says so rather than calling it weak", () => {
  const shown = authErrorMessage(
    weakPassword("Password is known to be weak and easy to guess, please choose a different one.", ["pwned"]));
  assert.equal(shown, PASSWORD_BREACHED);
  assert.match(shown, /data breach/i);
});

test("two failed rules are both named, and no reasons at all keeps the server's words", () => {
  const both = authErrorMessage(weakPassword("Password should be at least 12 characters.", ["length", "pwned"]));
  assert.match(both, /at least 12 characters/);
  assert.match(both, /data breach/);
  assert.equal(authErrorMessage(weakPassword("Some new rule failed.", [])), "Some new rule failed.");
  assert.equal(authErrorMessage(weakPassword("", [])), AUTH_ERROR_SENTENCES.weak_password);
});

test("a 429 from a server that sends no code is still read as a rate limit", () => {
  assert.match(authErrorMessage(authApiError("Too Many Requests", 429)), /too many attempts/i);
});

test("an unknown code keeps Supabase's own words rather than hiding them", () => {
  const raw = authApiError("Something specific happened", 400, "saml_idp_not_found");
  assert.equal(authErrorMessage(raw), "Something specific happened");
  assert.equal(knownAuthErrorMessage(raw), null);
});

test("an Error the page threw itself passes through unchanged", () => {
  const own = new Error("This sign-up link has expired or you are not signed in.");
  assert.equal(authErrorMessage(own, "fallback"), own.message);
});

test("nothing to say falls back to the caller's sentence", () => {
  assert.equal(authErrorMessage(null, "Could not set your password."), "Could not set your password.");
  assert.equal(authErrorMessage(undefined), "Something went wrong. Please try again.");
  assert.equal(authErrorMessage({ message: "   " }, "fb"), "fb");
  assert.equal(authErrorMessage("", "fb"), "fb");
  assert.equal(authErrorMessage("typed words", "fb"), "typed words");
});

test("knownAuthErrorMessage answers only for what it recognises", () => {
  assert.equal(knownAuthErrorMessage(new Error("plain")), null);
  assert.equal(knownAuthErrorMessage(null), null);
  assert.equal(
    knownAuthErrorMessage(authApiError("email rate limit exceeded", 429, "over_email_send_rate_limit")),
    AUTH_ERROR_SENTENCES.over_email_send_rate_limit,
  );
});

test("a network failure says the service could not be reached, whichever way auth-js reports it", () => {
  const thrown = new TypeError("Failed to fetch");
  assert.match(authErrorMessage(thrown), /could not be reached/);
  const retryable = Object.assign(new Error(""), { name: "AuthRetryableFetchError", status: 0 });
  assert.match(authErrorMessage(retryable), /could not be reached/);
  // A TypeError that is not about the network is a bug and keeps its own words.
  assert.equal(knownAuthErrorMessage(new TypeError("x is not a function")), null);
});

test("the mail server refusing is not reported as the address being wrong", () => {
  const smtp = authApiError("Error sending magic link email", 500, "unexpected_failure");
  const bad = authApiError("Email address is invalid", 400, "email_address_invalid");
  assert.notEqual(authErrorMessage(smtp), authErrorMessage(bad));
  assert.match(authErrorMessage(smtp), /mail server/i);
});

test("the Team screen's sentence says the row exists and the email did not go", () => {
  const s = inviteEmailNotSentMessage("Priya Sharma", "priya@firm.test",
    AUTH_ERROR_SENTENCES.over_email_send_rate_limit);
  assert.match(s, /^The invite for Priya Sharma was created, but the email to priya@firm\.test could not be sent\./);
  assert.match(s, /last hour/);
  assert.doesNotMatch(s, /\bsent!/);
});

test("the groups are told apart by their own alphabet, and the words are read in any case", () => {
  // only the capital alphabet is named: it must not be read as asking for lowercase too
  assert.equal(authErrorMessage(authApiError("Password should contain at least one character of each: ABCDEFGHIJKLMNOPQRSTUVWXYZ, 0123456789", 422)),
    "Your password needs a capital letter and a digit.");
  assert.equal(authErrorMessage(authApiError("Password should contain at least one character of each: Lowercase, Uppercase, Digit, Symbol", 422)),
    "Your password needs a lowercase letter, a capital letter, a digit and a symbol (for example ! @ # $ %).");
});

test("the throttle on a repeat link request says how long to wait, not that the hour's emails are used up (POST-A-479)", () => {
  // As the live sign-in log recorded it on 18-11-2026: 429, code over_email_send_rate_limit.
  const raw = authApiError("For security purposes, you can only request this after 7 seconds.", 429, "over_email_send_rate_limit");
  const shown = authErrorMessage(raw);
  assert.equal(shown, "Please wait 7 seconds before asking again.");
  assert.doesNotMatch(shown, /last hour/i);
  // the hourly limit keeps its own sentence
  assert.match(authErrorMessage(authApiError("email rate limit exceeded", 429, "over_email_send_rate_limit")), /last hour/i);
});
