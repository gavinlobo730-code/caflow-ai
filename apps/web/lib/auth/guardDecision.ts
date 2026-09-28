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

// ── RoleGuard ────────────────────────────────────────────────────────────────
//
// The OTHER direction of the same rule. "Unresolved is not permission" keeps
// the app from rendering too early — but a role that is still resolving is not
// a REFUSAL either. RoleGuard used to redirect on `!loading && !permitted`, and
// `loading` clears when the SESSION is known, a round trip before the ROLE is:
// in between, `userRole` is null, `hasRole` reads that as least privilege, and
// a Partner opening /settings directly was sent to "/" every time. Waiting
// renders nothing; only a decided "no" redirects.

export type RoleGuardDecision = "wait" | "allow" | "deny";

export interface RoleGuardState {
  /** The session is still being restored. */
  loading: boolean;
  /** This user's role is still being resolved. */
  roleLoading: boolean;
  /** hasRole(userRole, allowed) — meaningless until both of the above are false. */
  permitted: boolean;
}

export function roleGuardDecision(state: RoleGuardState): RoleGuardDecision {
  if (state.loading || state.roleLoading) return "wait";
  return state.permitted ? "allow" : "deny";
}
