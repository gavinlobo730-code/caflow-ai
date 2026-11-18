// The platform admin's destructive actions (suspend, soft delete, permanent delete) need an authenticator code entered
// in the last five minutes (POST-A-484). The API refuses a stale one with this sentence and the page, recognising it,
// asks for a code and tries again. The sentence is `core/auth_time.FRESH_CODE_SENTENCE`;
// `apps/api/tests/test_the_fresh_code_sentence_is_one_sentence_in_two_languages.py` pins the pair.
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

export const FRESH_CODE_SENTENCE =
  "Enter a fresh authenticator code to continue: this action needs a code entered within the last 5 minutes.";

/** Whether a refusal's text is the API asking for a fresh authenticator code. */
export function isFreshCodeRefusal(message: string | null | undefined): boolean {
  return typeof message === "string" && message.includes(FRESH_CODE_SENTENCE);
}

/** A typed code, tidied: spaces and dashes a person adds are not part of it. `null` unless it is six digits. */
export function sixDigitCode(typed: string): string | null {
  const code = typed.replace(/[\s-]/g, "");
  return /^\d{6}$/.test(code) ? code : null;
}
