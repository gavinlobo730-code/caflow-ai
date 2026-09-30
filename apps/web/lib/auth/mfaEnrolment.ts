// Whether this staff member has to set up an authenticator app before the
// administration screens will answer them.
//
// WHY IT EXISTS
//
//   `mfa_guard` 403s an aal1 token for every role in MFA_REQUIRED_ROLES, and
//   mfaAssurance.ts rightly reads "no verified factor" as nothing owed at
//   sign-in — there is nothing to challenge. So a brand-new practice owner was
//   never asked to enrol and met the refusal instead, on Team, Payroll,
//   Billing, firm Settings and the permissions map that decides which buttons
//   render. The enrol screen existed; nothing sent anybody to it.
//
// WHAT IT DOES NOT DECIDE
//
//   Who the policy covers. The roles are environment-driven on the server, so
//   the server answers `applies_to_caller` with mfa_guard's own comparison
//   (GET /api/security/mfa-policy) and this reads it. A role list here would be
//   a second copy that drifts the first time MFA_REQUIRED_ROLES is changed.
//
// Dependency-free so it strips to plain JS and unit-tests with
// `node --experimental-strip-types --test`, like guardDecision.ts beside it.

export interface MfaPolicy {
  /** REQUIRE_MFA is on. */
  required: boolean;
  /** MFA_REQUIRED_ROLES, for display only — never tested against here. */
  roles: string[];
  /** mfa_guard would refuse THIS caller at aal1. */
  appliesToCaller: boolean;
}

/** The served payload, or null when it is not one. */
export function parseMfaPolicy(raw: unknown): MfaPolicy | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const o = raw as Record<string, unknown>;
  if (typeof o.required !== "boolean" || typeof o.applies_to_caller !== "boolean") return null;
  const roles = Array.isArray(o.roles) ? o.roles.filter((r): r is string => typeof r === "string") : [];
  return { required: o.required, roles, appliesToCaller: o.applies_to_caller };
}

export interface EnrolmentState {
  /** null = not known (not fetched yet, or the fetch failed). */
  policy: MfaPolicy | null;
  /** null = not known. Only an explicit `false` counts as "has none". */
  hasVerifiedFactor: boolean | null;
  isPortalPrincipal: boolean;
}

/**
 * True only when every fact is KNOWN and says so. An unknown policy or factor
 * list answers false: this is a nudge, not a gate — mfa_guard is the gate, and
 * a missed nudge still leaves the refusal naming Settings → Security, while a
 * wrong one tells somebody already enrolled that their account is unsecured.
 */
export function enrolmentRequired(state: EnrolmentState): boolean {
  const { policy, hasVerifiedFactor, isPortalPrincipal } = state;
  if (isPortalPrincipal) return false;
  if (!policy || !policy.required || !policy.appliesToCaller) return false;
  return hasVerifiedFactor === false;
}

/** Where the enrolment screen lives, with the welcome shown above the card. */
export const MFA_SETUP_HREF = "/settings/security?setup=1";

/** Where onboarding's last step sends a new owner. */
export function onboardingCompletionTarget(mustEnrol: boolean): string {
  return mustEnrol ? MFA_SETUP_HREF : "/?welcome=1";
}

/** What leads the enrol screen when it was opened with `?setup=1`: the
 *  welcome while enrolment is still owed, and a way on once it is not — the
 *  page stays mounted after a factor verifies, and nothing else on it leaves. */
export type SetupPageLead = "welcome" | "continue" | null;

export function setupPageLead(setup: boolean, mustEnrol: boolean): SetupPageLead {
  if (!setup) return null;
  return mustEnrol ? "welcome" : "continue";
}

/** Where "Continue to your workspace" goes: where onboarding would have gone. */
export const SETUP_CONTINUE_HREF = onboardingCompletionTarget(false);

/** Whether the "Secure your account" banner belongs on this path. The enrol
 *  screen itself is excluded — a banner pointing at the page it sits on. */
export function showsSecureAccountBanner(mustEnrol: boolean, pathname: string): boolean {
  if (!mustEnrol) return false;
  const p = pathname.length > 1 && pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
  return p !== "/settings/security";
}
