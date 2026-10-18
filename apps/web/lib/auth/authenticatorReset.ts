/**
 * The request a person (or a Partner on their behalf) sends to have a lost authenticator reset (POST-A-006).
 *
 * This file builds the BODY and nothing else. Who may ask, what is stored, who may decide and what approving does are all
 * the server's (`services/mfa_reset_service`): the browser names a person and gives a reason, and the server writes the
 * name, the e-mail and the summary a Partner reads from the member's own row.
 */

/** The `request_type` the approvals engine knows this by. */
export const AUTHENTICATOR_RESET = "mfa_reset";

/** Whose authenticator: the signed-in person's own (the only thing a locked-out person can ask), or a member's, by their
 *  `users.id`. */
export type ResetTarget = { kind: "self" } | { kind: "member"; userId: string };

export function resetRequestPayload(target: ResetTarget, reason: string): Record<string, unknown> {
  const body: Record<string, unknown> = { reason: reason.trim() };
  if (target.kind === "self") body.self = true;
  else body.user_id = target.userId;
  return body;
}

/**
 * One line telling the Partner how the person who asked proved who they were, from the `asker_aal` the server stored on
 * the request. A request made with a password alone is the weakest thing the approvals screen is ever asked to act on, so
 * the line says it plainly; a request from before the field existed (or one where the sign-in service did not say) is
 * "not recorded", which is NOT the same as either answer.
 */
export function askedWithText(askerAal: unknown): string {
  if (askerAal === "aal2") return "Asked after signing in with a second factor.";
  if (askerAal === "aal1") return "Asked with a password only.";
  return "How the asker signed in was not recorded.";
}
