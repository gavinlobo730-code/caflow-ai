// Run with: node --experimental-strip-types --test lib/auth/authErrorSentence.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  AUTH_ERROR_SENTENCES,
  authErrorSentence,
  inviteEmailNotSentMessage,
} from "./authErrorSentence.ts";

test("no error is no sentence", () => {
  assert.equal(authErrorSentence(null), null);
  assert.equal(authErrorSentence(undefined), null);
});

test("a known Supabase code reads as its own sentence", () => {
  const e = { name: "AuthApiError", code: "over_email_send_rate_limit", status: 429,
              message: "email rate limit exceeded" };
  assert.equal(authErrorSentence(e), AUTH_ERROR_SENTENCES.over_email_send_rate_limit);
  assert.match(authErrorSentence(e)!, /Wait an hour/);
});

test("the mail server refusing is not reported as the address being wrong", () => {
  const smtp = { code: "unexpected_failure", status: 500, message: "Error sending magic link email" };
  const bad = { code: "email_address_invalid", status: 400, message: "Email address is invalid" };
  assert.notEqual(authErrorSentence(smtp), authErrorSentence(bad));
});

test("a 429 with no code still reads as a rate limit", () => {
  assert.equal(authErrorSentence({ status: 429, message: "Too many" }),
               AUTH_ERROR_SENTENCES.over_request_rate_limit);
});

test("a thrown network failure says the service could not be reached", () => {
  assert.match(authErrorSentence(new TypeError("Failed to fetch"))!, /could not be reached/);
  assert.match(authErrorSentence({ name: "AuthRetryableFetchError", message: "", status: 0 })!,
               /could not be reached/);
});

test("an unknown code keeps the server's own words rather than inventing a reason", () => {
  const s = authErrorSentence({ code: "hook_timeout", status: 500, message: "Hook timed out" });
  assert.equal(s, "The email service refused it: Hook timed out");
});

test("an error with nothing in it is still an error, never success", () => {
  assert.equal(authErrorSentence({}), "The email service refused it and gave no reason.");
});

test("the Team screen's sentence says the row exists and the email did not go", () => {
  const s = inviteEmailNotSentMessage("Priya Sharma", "priya@firm.test",
                                      AUTH_ERROR_SENTENCES.over_email_send_rate_limit);
  assert.match(s, /^The invite for Priya Sharma was created, but the email to priya@firm\.test could not be sent\./);
  assert.match(s, /Wait an hour/);
  assert.doesNotMatch(s, /\bsent!/);
});
