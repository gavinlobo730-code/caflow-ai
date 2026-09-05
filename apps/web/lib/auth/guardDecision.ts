// What AuthGuard may render, as a pure function.
//
// WHY IT IS NOT INLINE
//
//   The rule it encodes is one line — "unresolved is not permission" — and that
//   line is the third of the three fail-opens described in mfaAssurance.ts.
//   AuthGuard.tsx imports React and next/navigation, so nothing there can be
//   unit-tested with `node --experimental-strip-types --test`; the predicate
//   inlined in it was therefore the one part of this control with no test at
//   all. Reverting it failed nothing.
//
//   So the decision lives here, dependency-free, and AuthGuard calls it.

/** `true` = challenge owed, `false` = nothing owed, `null` = still resolving. */
export type MfaPending = boolean | null;

export interface GuardState {
  hasSession: boolean;
  mfaPending: MfaPending;
  hasFirm: boolean | null;
  isPublic: boolean;
  onLogin: boolean;
}

/**
 * Whether the protected app may be rendered.
 *
 * The MFA rule is the point: BOTH `true` (a challenge is owed) and `null` (we
 * could not tell) withhold the app. Only an explicit `false` — resolved, and
 * nothing owed — lets it through.
 */
export function mayRenderProtected(state: GuardState): boolean {
  const { hasSession, mfaPending, hasFirm, isPublic, onLogin } = state;

  if (!hasSession) return isPublic;

  // A challenge is owed, or we could not determine whether one is. Neither is
  // permission. The login page is exempt because it renders the challenge.
  if (!onLogin && mfaPending !== false) return false;

  // Signed in with no firm record — onboarding, not the app.
  if (hasFirm === false && !isPublic) return false;

  return true;
}
