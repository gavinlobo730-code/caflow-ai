// When the assurance already known may stand while a fresh read is made (POST-A-493).
//
// THE RULE IT GIVES BACK. AuthContext used to set the sign-in assurance to "not yet read" (null) on EVERY announcement of the
// sign-in service, and AuthGuard draws nothing for null (an unresolved assurance is not permission: lib/auth/guardDecision). So a
// page was unmounted and mounted again by an announcement that changed nothing about who is signed in: every time a tab regained
// focus (the library announces SIGNED_IN again for the session it loaded from storage), every hour (TOKEN_REFRESHED), and after a
// password was saved (USER_UPDATED). What was typed was lost, and a message set by a request already in flight was set on a page
// that had gone. Reproduced in a real browser on 19-11-2026 with the sign-in service's account lookup held for a second, which is
// what the assurance check waits for in production.
//
// WHAT MAY STAND, AND WHAT MAY NOT. The assurance is a property of a SESSION. It may stand, while the read is made again, only
// when the announcement cannot have changed which session this is:
//   * TOKEN_REFRESHED and USER_UPDATED are emitted for the session the browser already holds (a refresh of its token; a change to
//     its user), so for the same person they keep it;
//   * SIGNED_IN keeps it only when the token is the very same string: that is the library announcing the session it loaded from
//     storage again, and an identical token is an identical session without decoding anything;
//   * MFA_CHALLENGE_VERIFIED keeps it only where the session is ALREADY ADMITTED (`pending === false`) (POST-A-515 (c)). A code
//     verified raises the level of the session it was verified on and never lowers it, so a session that owed nothing owes nothing
//     after it, and the page it was already on (Settings > Security enrolling a factor and verifying its first code) is not unmounted
//     and rebuilt under the person while the level is read again, which lost what was typed and any message a request in flight was
//     about to set. (The platform page's step-up emits the same event, and that page had its own gate that re-checked whenever the
//     session object changed and drew a spinner in place of its body; its open gate now stays open while it is read again, POST-A-528,
//     app/platform/page.tsx. The password proof on Settings > Security no longer emits the event at all: it runs on a throwaway client
//     since POST-A-512.) Where a challenge IS owed (`pending === true`) the verified code is what ends it, so that
//     value is NOT kept: it is read afresh and the guard draws nothing until the fresh read says what the session now owes, exactly as
//     before. A session whose assurance was never read (`null`) keeps nothing, as for every other event.
//   * everything else does not: a different person, a different token on a SIGNED_IN (a new sign-in, which may be at a lower level
//     and owes its own challenge), SIGNED_OUT, PASSWORD_RECOVERY, MFA_CHALLENGE_VERIFIED on a session that owed a challenge,
//     INITIAL_SESSION, an event this code does not know, and anything while nothing is yet known.
// Fail closed is kept in both directions: what is NOT recognised as unchanged is set to unresolved, exactly as before, and a kept
// value is replaced when the fresh read answers (the most recently started read always settles; an older one that answers late is
// dropped, lib/auth/latestWins), so a level that DID change (a factor enrolled, a challenge now owed) takes the page away again on
// the next render.
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

export type KnownAssurance = {
  /** The person the value belongs to, or null when there is none. */
  userId: string | null;
  /** The access token of the session it was read for. */
  accessToken: string | null;
  /** `true` a challenge is owed, `false` none is, `null` not read yet. */
  pending: boolean | null;
};

/** The announcements that are about the session the browser already holds, for the same person. */
const ABOUT_THE_SAME_SESSION = new Set(["TOKEN_REFRESHED", "USER_UPDATED"]);

export function mayKeepAssurance(args: {
  event: string;
  known: KnownAssurance;
  nextUserId: string | null;
  nextAccessToken: string | null;
}): boolean {
  const { event, known, nextUserId, nextAccessToken } = args;
  if (known.pending === null) return false;                       // nothing read yet: nothing to keep
  if (!known.userId || !nextUserId || known.userId !== nextUserId) return false;
  if (!nextAccessToken) return false;                             // no session in the announcement
  if (ABOUT_THE_SAME_SESSION.has(event)) return true;
  if (event === "SIGNED_IN") return !!known.accessToken && known.accessToken === nextAccessToken;
  // The verified code's session has a NEW token (the level is in it), so the token is not compared; the person is (above), and the
  // value kept is only ever the one that already let this person in.
  if (event === "MFA_CHALLENGE_VERIFIED") return known.pending === false;
  return false;
}
