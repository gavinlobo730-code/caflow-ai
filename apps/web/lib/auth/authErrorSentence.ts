// Supabase auth errors as plain sentences — the subset the Team screen's
// invite email needs. Named and shaped (a code-keyed table plus one reader)
// so a wider sign-up mapping can absorb it rather than sit beside it.
//
// No imports: strips to plain JS for `node --experimental-strip-types --test`.

export const AUTH_ERROR_SENTENCES: Readonly<Record<string, string>> = {
  over_email_send_rate_limit:
    "Too many emails have been sent from this app in the last hour. Wait an hour and try again.",
  over_request_rate_limit:
    "Too many requests were made in a short time. Wait a few minutes and try again.",
  email_address_invalid:
    "The email service does not accept that address. Check it for a typing mistake.",
  email_address_not_authorized:
    "The email service is only allowed to send to pre-approved addresses. A custom mail server (SMTP) has to be set up before invites can reach anybody else.",
  email_provider_disabled: "Email sign-in is switched off for this app.",
  otp_disabled: "Email sign-in links are switched off for this app.",
  signup_disabled: "New accounts cannot be created — sign-ups are switched off for this app.",
  unexpected_failure: "The mail server refused to send it.",
};

const RATE_LIMITED_STATUS = 429;

/**
 * Why an auth email was not sent, as one sentence — or null when it was.
 *
 * Takes `unknown` because it reads both what `signInWithOtp` RETURNS as
 * `error` (an AuthError, never thrown) and what a failed fetch THROWS.
 */
export function authErrorSentence(error: unknown): string | null {
  if (error === null || error === undefined) return null;
  const e = (typeof error === "object" ? error : {}) as {
    code?: unknown; status?: unknown; message?: unknown; name?: unknown;
  };
  const code = typeof e.code === "string" ? e.code : "";
  if (code && AUTH_ERROR_SENTENCES[code]) return AUTH_ERROR_SENTENCES[code];
  if (e.status === RATE_LIMITED_STATUS) return AUTH_ERROR_SENTENCES.over_request_rate_limit;
  const message =
    typeof e.message === "string" ? e.message.trim()
    : typeof error === "string" ? error.trim()
    : "";
  if (e.name === "AuthRetryableFetchError" || e.name === "TypeError" || /failed to fetch|network/i.test(message)) {
    return "The email service could not be reached. Check the connection and try again.";
  }
  return message
    ? `The email service refused it: ${message}`
    : "The email service refused it and gave no reason.";
}

/** The whole sentence the Team screen shows when the row exists and the email did not go. */
export function inviteEmailNotSentMessage(name: string, email: string, reason: string): string {
  return `The invite for ${name} was created, but the email to ${email} could not be sent. ${reason} Until an email reaches them they have no link to join with.`;
}
