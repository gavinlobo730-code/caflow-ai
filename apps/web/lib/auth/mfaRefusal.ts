// What a screen says when mfa_guard refused the request.
//
// The backend's sentence, "Multi-factor authentication required for this
// action.", reached the CA verbatim — on the firm-profile load, beside a blank
// form, and again on Save — and named neither what to do nor where. It is
// translated ONCE, where lib/api turns a refusal body into text, so every
// screen that shows `e.message` says the same useful thing; a component that
// can render a link asks `isMfaRefusal` and adds one.
//
// Keyed on the backend's EXACT detail, pinned from the Python side by
// apps/api/tests/test_the_mfa_policy_reaches_the_people_it_locks_out.py —
// matching "mfa" anywhere in a message (which /approvals used to do) would
// also catch the platform-admin refusal, a different guard with its own text.
//
// Dependency-free, for `node --experimental-strip-types --test`.

import { MFA_SETUP_HREF } from "./mfaEnrolment.ts";

export const MFA_REQUIRED_DETAIL = "Multi-factor authentication required for this action.";

/** The sentence in two halves, so a screen that can link the place does
 *  without restating the words. */
export const MFA_SETUP_LEAD = "Set up your authenticator app to use this";
export const MFA_SETUP_PLACE = "Settings → Security";
export const MFA_SETUP_MESSAGE = `${MFA_SETUP_LEAD} — ${MFA_SETUP_PLACE}`;

export { MFA_SETUP_HREF };

/** The text to show for a refusal: the setup sentence for an MFA refusal,
 *  anything else unchanged. */
export function explainMfaRefusal(message: string): string {
  return message.trim() === MFA_REQUIRED_DETAIL ? MFA_SETUP_MESSAGE : message;
}

/** Whether a message IS the MFA refusal, before or after translation. */
export function isMfaRefusal(message: unknown): boolean {
  if (typeof message !== "string") return false;
  const m = message.trim();
  return m === MFA_REQUIRED_DETAIL || m === MFA_SETUP_MESSAGE;
}
