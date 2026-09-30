// What a Supabase Auth error says to a CA. Supabase answers with strings written
// for developers ("email rate limit exceeded", 'Email address "x" is invalid',
// "Auth session missing!"), and the sign-up and sign-in screens rendered them
// verbatim. This maps the error's CODE — the stable part of the contract, see
// @supabase/auth-js lib/error-codes.d.ts — to a sentence the reader can act on.
// An unknown code keeps the original message: hiding a real reason behind a
// generic one is worse than showing it raw.
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

type ErrorLike = { code?: unknown; name?: unknown; status?: unknown; message?: unknown };

const TRY_AGAIN_SHORTLY = "Please wait a few minutes and try again.";

export const AUTH_ERROR_SENTENCES: Readonly<Record<string, string>> = {
  over_email_send_rate_limit:
    `Too many sign-in emails have been sent to this address recently. ${TRY_AGAIN_SHORTLY}`,
  over_request_rate_limit: `Too many attempts in a short time. ${TRY_AGAIN_SHORTLY}`,
  over_sms_send_rate_limit: `Too many text messages have been sent recently. ${TRY_AGAIN_SHORTLY}`,
  email_address_invalid:
    "That email address was not accepted. Please check it for typing mistakes, or use a different address.",
  email_address_not_authorized:
    "Sign-in emails cannot be sent to that address yet. Please use a different address or contact support.",
  otp_expired: "This link or code has expired. Please request a new one.",
  reauthentication_not_valid: "That code is incorrect or has expired. Request a new code and try again.",
  reauth_nonce_missing: "Enter the verification code we emailed you to confirm the change.",
  reauthentication_needed:
    "For your security we need to confirm it is you. Request a verification code and try again.",
  same_password: "Your new password must be different from your current one.",
  weak_password: "That password is too easy to guess. Use a longer password with a mix of words, numbers or symbols.",
  invalid_credentials: "The email or password is incorrect.",
  email_not_confirmed: "Please confirm your email address first, using the link we emailed you.",
  user_banned: "This account has been disabled. Please contact your firm's administrator.",
  signup_disabled: "New sign-ups are not open at the moment.",
  session_expired: "Your session has expired. Please sign in again.",
  session_not_found: "Your session has expired. Please sign in again.",
  refresh_token_not_found: "Your session has expired. Please sign in again.",
  refresh_token_already_used: "Your session has expired. Please sign in again.",
  request_timeout: "The sign-in service took too long to respond. Please try again.",
  hook_timeout: "The sign-in service took too long to respond. Please try again.",
  hook_timeout_after_retry: "The sign-in service took too long to respond. Please try again.",
};

const DEFAULT_FALLBACK = "Something went wrong. Please try again.";

function asErrorLike(err: unknown): ErrorLike | null {
  return err !== null && typeof err === "object" ? (err as ErrorLike) : null;
}

/** The plain sentence for an error this module recognises, or null. */
export function knownAuthErrorMessage(err: unknown): string | null {
  const e = asErrorLike(err);
  if (!e) return null;
  const code = typeof e.code === "string" ? e.code : "";
  if (code && Object.prototype.hasOwnProperty.call(AUTH_ERROR_SENTENCES, code)) {
    return AUTH_ERROR_SENTENCES[code];
  }
  // AuthSessionMissingError carries no code, only its class name.
  if (e.name === "AuthSessionMissingError") return AUTH_ERROR_SENTENCES.session_expired;
  // A 429 from an older server that sends no code is still a rate limit.
  if (!code && e.status === 429) return AUTH_ERROR_SENTENCES.over_request_rate_limit;
  return null;
}

/**
 * The sentence to show for an auth error: the plain one where the code is
 * known, otherwise the error's own message, otherwise `fallback`. A plain
 * `Error` the page threw itself passes through with its message intact.
 */
export function authErrorMessage(err: unknown, fallback: string = DEFAULT_FALLBACK): string {
  const known = knownAuthErrorMessage(err);
  if (known) return known;
  if (typeof err === "string") return err.trim() || fallback;
  const e = asErrorLike(err);
  const message = e && typeof e.message === "string" ? e.message.trim() : "";
  return message || fallback;
}
