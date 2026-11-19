// Prove a person's CURRENT password without touching the browser's session (POST-A-512).
//
// A live session is not proof of identity: someone at an unlocked, signed-in browser could otherwise set a new password and lock
// the real owner out, so Settings > Security asks for the current password and checks it itself, whatever the project's own
// "Require current password when updating" switch is set to. The check used to be `signInWithPassword` on the browser's client,
// which replaces the browser's session (a new token, a first-level assurance for a person with an authenticator, a rebuilt page).
// It is made on a throwaway client that keeps nothing (lib/supabase/client.makeEphemeralAuthClient) and signed out again at once.
//
// Dependency-light so it strips to plain JS for `node --experimental-strip-types`: the client is passed in.
import { authErrorMessage } from "./authErrorMessage.ts";

/** What a person is told when the password they typed is not the account's. */
export const CURRENT_PASSWORD_WRONG = "Current password is incorrect.";

export type PasswordProof = { ok: true } | { ok: false; message: string };

/** The slice of a Supabase client this needs: one sign-in and one local sign-out. */
export interface ProofClient {
  auth: {
    signInWithPassword(credentials: { email: string; password: string }): Promise<{ error: unknown }>;
    signOut(options?: { scope?: "local" | "global" | "others" }): Promise<unknown>;
  };
}

const COULD_NOT_CHECK = "Could not check your current password. Please try again.";

export async function verifyCurrentPassword(email: string, password: string, makeClient: () => ProofClient): Promise<PasswordProof> {
  const client = makeClient();
  try {
    const { error } = await client.auth.signInWithPassword({ email, password });
    if (error) {
      const code = error !== null && typeof error === "object" ? (error as { code?: unknown }).code : undefined;
      // Wrong password: the card's own words, not the sign-in screen's "email or password".
      if (code === "invalid_credentials") return { ok: false, message: CURRENT_PASSWORD_WRONG };
      // Anything else (a throttle, a service that cannot be reached) is NOT "incorrect": say what it was.
      return { ok: false, message: authErrorMessage(error, COULD_NOT_CHECK) };
    }
    return { ok: true };
  } catch (e) {
    return { ok: false, message: authErrorMessage(e, COULD_NOT_CHECK) };
  } finally {
    // The throwaway session is revoked at once. Failing to revoke it must never change the answer the proof gave.
    try {
      await client.auth.signOut({ scope: "local" });
    } catch {
      /* nothing the person can act on */
    }
  }
}
