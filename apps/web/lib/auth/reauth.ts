// Reauthentication / password-finalization helpers for the onboarding flow.
//
// Background — the OTP onboarding bug:
//   When "Secure password change" is enabled in Supabase Auth, updating the
//   password on a magic-link session that isn't "recently signed in" requires a
//   reauthentication nonce. supabase.auth.reauthenticate() emails that nonce.
//
//   The nonce is NOT an email OTP. The Supabase SDK is explicit:
//     "After receiving the OTP, include it as the `nonce` in your updateUser()
//      call to finalize the password change."
//   EmailOtpType has no 'reauthentication' member
//   ('signup'|'invite'|'magiclink'|'recovery'|'email_change'|'email'), so
//   verifyOtp({ type: "email" }) can NEVER validate a reauthentication nonce —
//   it rejects every correct code as "invalid". The bug was using verifyOtp.
//
//   Correct flow:  reauthenticate()  →  updateUser({ password, nonce })
//
// This module is intentionally dependency-free (type-only import) so it strips to
// plain JS and can be unit-tested with `node --experimental-strip-types --test`.
import type { AuthError, UserResponse } from "@supabase/supabase-js";

/** The minimal slice of supabase.auth this helper needs — keeps it mockable. */
export interface ReauthCapableAuth {
  updateUser(attributes: { password?: string; nonce?: string }): Promise<UserResponse>;
}

/** True when an updateUser() error indicates a bad/expired reauthentication nonce. */
export function isInvalidNonceError(err: Pick<AuthError, "message"> | null | undefined): boolean {
  if (!err?.message) return false;
  return /expired|invalid|nonce|otp/i.test(err.message);
}

/**
 * True when an auth error means there is no session to act on at all — the
 * visitor is not signed in (an already-used or expired magic link, a
 * signed-out tab left open on /onboarding). Supabase's own SDK error is the
 * literal "Auth session missing!" (AuthSessionMissingError), which
 * updateUser() surfaced verbatim to the CA before this existed
 * (sweep-auth-and-public-04).
 */
export function isSessionMissingError(err: Pick<AuthError, "message"> | null | undefined): boolean {
  if (!err?.message) return false;
  return /auth session missing/i.test(err.message);
}

/** The one message shown wherever a step 1 auth call finds no session. */
export const SESSION_EXPIRED_MESSAGE =
  "This sign-up link has expired or you are not signed in. Please request a new sign-up link or sign in.";

/** The same, on the reset-password page, where the visitor has no working password. */
export const RESET_LINK_ENDED_MESSAGE =
  "This password-reset link has expired or has already been used. Please request a new reset link.";

/**
 * Finalize a password change using the reauthentication nonce emailed by
 * supabase.auth.reauthenticate(). The nonce is sent VERBATIM (only trimmed) —
 * never truncated, sliced, or parsed — so the exact code the user typed is the
 * exact value Supabase receives.
 */
export async function setPasswordWithReauthNonce(
  auth: ReauthCapableAuth,
  password: string,
  nonce: string,
): Promise<UserResponse> {
  return auth.updateUser({ password, nonce: nonce.trim() });
}
