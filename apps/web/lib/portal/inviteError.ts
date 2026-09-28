/**
 * Turns a failed browser-side sign-in-email send into a sentence that says
 * what actually happened.
 *
 * `handleSendInvite` (apps/web/app/clients/[id]/portal/page.tsx) creates the
 * portal contact server-side FIRST — it is already committed and "invited"
 * — and only then asks Supabase Auth to send the sign-in email from the
 * browser. When that second step fails (most often Supabase Auth's own
 * send-rate limit, hit by sending a second or third invite shortly after the
 * first), the raw message — "email rate limit exceeded" — read as though the
 * whole invite had failed, when the contact record was in fact already
 * created. This says so plainly instead of surfacing Supabase's wording
 * unexplained.
 */
export function portalInviteEmailFailureMessage(rawMessage: string): string {
  return (
    `The invite was created, but the sign-in email could not be sent just now (${rawMessage}). ` +
    `Wait a few minutes, then use "Invite Another Contact" with the same email to try again.`
  );
}
