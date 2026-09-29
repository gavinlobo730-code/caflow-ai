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

// ── /login/forgot-password (portal) ─────────────────────────────────────────
//
// `mfaPending === false && onLogin` bounces a fully-authenticated visitor away
// from anywhere under /login, including /login/forgot-password?portal=1 — the
// SAME shared reset-request page the client portal's own "Forgot password?"
// link uses (apps/web/app/portal/login/page.tsx). That page exists to request
// a reset link for a DIFFERENT identity than whatever session happens to be
// live in this browser, so bouncing it is wrong twice over: a CA tester
// signed in as firm staff (testing the portal in the same browser/tab) never
// sees the reset form at all, and a PORTAL CLIENT who is already signed in
// and clicks it anyway lands on "/" — which AuthGuard then bounces AGAIN, to
// /onboarding, because a portal contact has no `users` row. Either way the
// reset request is silently swallowed before it is ever sent.

export interface LoginBounceState {
  hasSession: boolean;
  mfaPending: MfaPending;
  onLogin: boolean;
  isPortalRecovery: boolean;
}

/** Whether AuthGuard should replace the URL with "/" from the login page. */
export function shouldBounceFromLogin(state: LoginBounceState): boolean {
  const { hasSession, mfaPending, onLogin, isPortalRecovery } = state;
  return hasSession && onLogin && mfaPending === false && !isPortalRecovery;
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

// ── /signup ──────────────────────────────────────────────────────────────────
//
// AuthGuard already bounces a fully authenticated /login visitor to "/" (the
// `mfaPending === false && onLogin` branch in the effect). /signup had no
// mirror: it is a PUBLIC_PREFIXES entry with no session check of its own, so
// a signed-in Partner with an existing firm got the live "Create your firm"
// form and could fire signInWithOtp while already onboarded.
//
// Same rule as the login bounce, with one extra term: a firm-less session —
// mid-signup, before the firm bootstrap has run — is left alone, since
// /signup is where that person finishes.

export interface SignupBounceState {
  hasSession: boolean;
  mfaPending: MfaPending;
  hasFirm: boolean | null;
  onSignup: boolean;
}

/** Whether AuthGuard should replace the URL with "/" from /signup. */
export function shouldBounceFromSignup(state: SignupBounceState): boolean {
  const { hasSession, mfaPending, hasFirm, onSignup } = state;
  return hasSession && onSignup && mfaPending === false && hasFirm === true;
}

// ── /onboarding ──────────────────────────────────────────────────────────────
//
// /onboarding is PUBLIC_EXACT (it has to run before a firm exists — see
// public-paths.ts), so `mayRenderProtected` above never gets a chance to
// refuse it: `!hasSession` there returns `isPublic`, which is `true` here by
// design. That is right for the case this page exists for (a fresh magic-link
// session) and wrong for every other one — a link already used, one opened in
// a browser that never completed the exchange, a bookmark from before sign-out
// — because the wizard itself never checked session or loading before
// rendering Step 1. It called supabase.auth.updateUser() with no session and
// surfaced the SDK's raw "Auth session missing!", and its greeting
// interpolated a blank `user?.email` (sweep-auth-and-public-04).
//
// `loading` keeps this from flashing the expired-link screen while the
// session is still being restored — though in practice AuthGuard's own
// loading gate has already resolved by the time this page mounts, since it
// renders nothing else while `loading` is true.
export interface OnboardingGuardState {
  loading: boolean;
  hasSession: boolean;
}

/** Whether the onboarding wizard (Step 1 onward) may render. */
export function mayRenderOnboardingWizard(state: OnboardingGuardState): boolean {
  return state.loading || state.hasSession;
}

// ── No `users` row: /onboarding OR /portal/login ────────────────────────────
//
// AuthGuard's own effect sends a signed-in session with `hasFirm === false`
// to /onboarding — right for the case that state exists for (a brand-new
// firm signup whose bootstrap hasn't run yet) and wrong for a PORTAL CLIENT
// hitting a staff-only URL directly: a portal contact's identity lives in
// `client_portal_users`, not `public.users`, so it resolves to hasFirm=false
// too, and lands the same business owner on "Welcome! Let's set up your
// firm... Create Password / Firm Profile" — a wizard for somebody who already
// has a password and does not run a firm. No data leaks (the redirect fires
// before anything staff-only is fetched); it is simply the wrong page.
//
// Whether the signed-in identity IS a portal client is an async fact (a
// database read keyed on auth_user_id — see lib/portal/clientAccess.ts) and
// cannot live in this dependency-free file; this is the one-line DECISION
// once that fact is known, kept here and tested the same way as the rest of
// this module.
export function noFirmRedirectTarget(isPortalClient: boolean): "/portal/login" | "/onboarding" {
  return isPortalClient ? "/portal/login" : "/onboarding";
}
