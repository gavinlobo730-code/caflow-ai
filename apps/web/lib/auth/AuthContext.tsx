"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useRef,
  ReactNode,
} from "react";
import { Session, User } from "@supabase/supabase-js";
import { supabase, getSupabaseClient } from "@/lib/supabase/client";
import { authErrorMessage } from "@/lib/auth/authErrorMessage";
import {
  can as canDo,
  normalizeRole,
  parsePermissionMap,
  type PermissionMap,
  type UserRole,
} from "@/lib/auth/permissions";

/**
 * Resolve the caller's role AND firm membership from the AUTHORITATIVE source —
 * the users table — rather than JWT user_metadata (which can be stale/forged).
 * `hasFirm` is true only when a users row with a non-null firm_id exists; a
 * freshly-signed-up account with no firm yet resolves to hasFirm=false so the
 * guard can route it to onboarding instead of dropping it on an empty dashboard.
 */
interface ResolvedContext {
  role: UserRole | null;
  /** null = could not be determined (the read FAILED), which is not "no firm". */
  hasFirm: boolean | null;
  fullName: string | null;
  /** The users-table read failed, so none of the above is authoritative. */
  failed: boolean;
}

async function resolveUserContext(user: User | null): Promise<ResolvedContext> {
  if (!user) return { role: null, hasFirm: false, fullName: null, failed: false };
  try {
    const { data, error } = await getSupabaseClient()
      .from("users")
      .select("role, firm_id, full_name")
      .eq("auth_user_id", user.id)
      .maybeSingle();
    // A FAILED read is not an absent row. supabase-js returns the error rather
    // than throwing, and this used to read `data` straight through it — so a
    // transient failure (a re-resolution racing a token refresh, a cold API
    // proxy) answered hasFirm=false, AuthGuard sent the user to /onboarding and
    // on to Home: the "Audit Log bounces to Home after ~10 seconds" finding.
    if (error) throw error;
    const raw = (data?.role as string | undefined) ?? (user.user_metadata?.role as string | undefined);
    return { role: normalizeRole(raw), hasFirm: !!data?.firm_id, fullName: (data?.full_name as string | null) ?? null, failed: false };
  } catch {
    return { role: normalizeRole(user.user_metadata?.role as string | undefined), hasFirm: null, fullName: null, failed: true };
  }
}

/**
 * Is the current tab a PORTAL principal's, not firm staff's?
 *
 * `AuthContext` wraps the whole app, `/portal/*` included, and a portal
 * session — a client (core/portal_auth.get_current_portal_client) or an
 * employee (get_current_portal_employee) — has no `users` row and no RBAC
 * role. `"PortalClient"`/`"PortalEmployee"` are not entries in `PERMISSIONS`
 * (CLAUDE.md), so `GET /api/identity/permissions` correctly 403s for either
 * one — correctly, but on every single portal page, since `applyContext`
 * calls it for any signed-in identity with no way to tell the two kinds
 * apart. This is the equivalent of that backend distinction on THIS side:
 * there is no portal-scoped API call to make instead, so the route itself —
 * the one structural fact the browser already has — is what stands in for
 * it, the same way `guardDecision.ts`'s `isPortalRecovery` already reads the
 * URL rather than asking the server which kind of session this is.
 *
 * `"/portal"` is deliberately not imported from `PUBLIC_PREFIXES`
 * (public-paths.ts): that list also covers `/login`, `/signup`, `/join`,
 * `/auth`, `/platform` and `/sign`, none of which is this question, and an
 * authenticated `/platform` session is a different principal this function
 * is not the place to decide about.
 */
function isPortalPrincipalPath(): boolean {
  if (typeof window === "undefined") return false;
  const p = window.location.pathname;
  return p === "/portal" || p.startsWith("/portal/");
}

/**
 * Fetch the caller's resource→actions map from the backend.
 *
 * Returns null on ANY failure — an unreachable/cold-starting API, an older
 * backend without the endpoint, a body that is not the expected shape. Null
 * means `can()` says no everywhere, so a failure hides action controls rather
 * than showing ones the server will refuse. Imported lazily to match the rest
 * of this file, which keeps the API client out of the auth bundle.
 */
async function resolvePermissions(): Promise<PermissionMap | null> {
  try {
    const { api } = await import("@/lib/api");
    const res = await api.identity.myPermissions();
    if (!res?.success) return null;
    return parsePermissionMap(res.data?.permissions);
  } catch {
    return null;
  }
}

/** GET /api/security/mfa-policy, or null on any failure. Null means no nudge:
 *  the nudge is advice and mfa_guard is the gate, so an unknown policy must not
 *  tell an enrolled Partner their account is unsecured. */
async function resolveMfaPolicy(): Promise<MfaPolicy | null> {
  try {
    const { api } = await import("@/lib/api");
    const res = await api.security.mfaPolicy();
    if (!res?.success) return null;
    return parseMfaPolicy(res.data);
  } catch {
    return null;
  }
}

async function resolveFactorState(session: Session | null): Promise<boolean | null> {
  if (!session) return null;
  const mfa = getSupabaseClient().auth.mfa;
  return resolveVerifiedFactor({ listFactors: () => mfa.listFactors() });
}

interface AuthContextValue {
  session: Session | null;
  user: User | null;
  userRole: UserRole | null;
  loading: boolean;
  /**
   * True while the role for the CURRENT user is still being resolved.
   * `loading` clears as soon as the SESSION is known and the role arrives a
   * round trip later; in between `userRole` is null, which the permission
   * helpers read as least privilege. A guard that redirects on "not permitted"
   * must wait for this too, or it bounces a Partner off a Partner-only page on
   * every hard navigation (the /settings/* pages did exactly that).
   */
  roleLoading: boolean;
  /**
   * MFA challenge state: true = the session is aal1 but the account has a verified
   * factor (must complete the TOTP challenge to reach aal2); false = no challenge
   * needed; null = not yet resolved for the current session.
   */
  mfaPending: boolean | null;
  /** Whether the signed-in user has a users row linked to a firm. null = resolving. */
  hasFirm: boolean | null;
  /** The user's full name from the users table. null = not yet resolved or not set. */
  fullName: string | null;
  /**
   * The caller's resource→actions map, served by GET /api/identity/permissions
   * straight from the backend's PERMISSIONS matrix. null = not yet resolved, or
   * the request failed — `can()` treats both as "no", which is the fail-closed
   * reading and matches how userRole=null is handled above.
   */
  permissions: PermissionMap | null;
  /** `can("accounting", "write")` — action-level gating for the current user. */
  can: (resource: string, action: string) => boolean;
  /** Re-resolve role + firm membership (call after creating a firm in onboarding). */
  refreshUserContext: () => Promise<boolean>;
  /**
   * The caller must set up an authenticator app before mfa_guard will answer
   * them (lib/auth/mfaEnrolment.ts). False while anything is unknown.
   */
  mustEnrolMfa: boolean;
  /** Fetch the policy and the factor list afresh and answer the same question,
   *  for a caller that must decide NOW (onboarding's last step). */
  resolveEnrolmentRequired: () => Promise<boolean>;
  signIn: (email: string, password: string) => Promise<{ error: string | null }>;
  signOut: () => Promise<void>;
}

import { resolveAssurance, resolveVerifiedFactor, toMfaPending } from "./mfaAssurance";
import { enrolmentRequired, parseMfaPolicy, type MfaPolicy } from "./mfaEnrolment";
import { latestWins } from "./latestWins";

const AuthContext = createContext<AuthContextValue | null>(null);

// Whether this session still owes an MFA challenge.
//
// The logic lives in lib/auth/mfaAssurance.ts, dependency-free and unit-tested,
// because the version inlined here FAILED OPEN three ways: it swallowed errors
// as "nothing owed", read a null payload the same way, and asked only
// getAuthenticatorAssuranceLevel() — whose nextLevel comes from the cached user
// object, so a restored session reports "nothing owed" for an account that has a
// verified factor. (This used to cite production evidence — "both Partners
// enrolled on 2026-08-15, every session since aal1" — and both halves were
// wrong: auth.mfa_factors shows the two verified Partner factors created on
// 2026-06-15 and 2026-09-29, and the aal1 sessions were the CI smoke script's
// password grants. mfaAssurance.ts records the re-measurement. The fail-opens
// were real defects in this code whatever production showed.)
//
// `null` now means UNRESOLVED and AuthGuard refuses to render on it. It is no
// longer a synonym for false.
async function resolveMfaPending(session: Session | null): Promise<boolean | null> {
  if (!session) return false;
  const mfa = getSupabaseClient().auth.mfa;
  return toMfaPending(await resolveAssurance({
    getAuthenticatorAssuranceLevel: () => mfa.getAuthenticatorAssuranceLevel(),
    listFactors: () => mfa.listFactors(),
  }));
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [userRole, setUserRole] = useState<UserRole | null>(null);
  const [loading, setLoading] = useState(true);
  const [roleLoading, setRoleLoading] = useState(true);
  // applyContext runs from getSession AND onAuthStateChange, so two role
  // lookups can be in flight; only the LATEST may settle the state, or an
  // older answer (e.g. the signed-out null) can land after the newer one.
  const contextRequest = useRef(0);
  // The user the current role belongs to. applyContext also runs on every
  // TOKEN_REFRESHED (hourly), and flipping roleLoading back to true there would
  // make every RoleGuard render null for a round trip — unmounting the page and
  // losing whatever the CA had typed. Only a DIFFERENT user makes the role unknown.
  const roleOwner = useRef<string | null | undefined>(undefined);
  // The user whose role/hasFirm are currently in state from a SUCCESSFUL read.
  const resolvedFor = useRef<string | null | undefined>(undefined);
  // apex-overview-practice-07(c): the owner a context resolution is CURRENTLY
  // in flight for, or undefined/null between resolutions. getSession().then(...)
  // and onAuthStateChange's own INITIAL_SESSION event both call applyContext
  // for the same user on every page load — 2x the users-table query and 2x
  // resolvePermissions() before either had a chance to answer. A call for a
  // user already being resolved is a duplicate of work already in flight, not
  // a new fact to learn, so it is skipped; a call once that work has settled
  // (the hourly TOKEN_REFRESHED case) still runs, because the token itself
  // changed and this is a genuine refresh rather than a duplicate.
  const contextInFlightFor = useRef<string | null | undefined>(undefined);
  const [mfaPending, setMfaPending] = useState<boolean | null>(null);
  const [hasFirm, setHasFirm] = useState<boolean | null>(null);
  const [fullName, setFullName] = useState<string | null>(null);
  const [permissions, setPermissions] = useState<PermissionMap | null>(null);
  const [mfaPolicy, setMfaPolicy] = useState<MfaPolicy | null>(null);
  const [hasVerifiedFactor, setHasVerifiedFactor] = useState<boolean | null>(null);
  // Set from the URL inside applyContext (an effect), never read during render.
  const [portalPrincipal, setPortalPrincipal] = useState(false);
  // Only the most recently STARTED request settles each of these — see
  // latestWins.ts for the aal1 403 that landed after the aal2 success.
  const permissionsGate = useRef(latestWins());
  const policyGate = useRef(latestWins());
  const factorGate = useRef(latestWins());

  function refreshFactorState(s: Session | null) {
    const apply = factorGate.current.begin<boolean | null>(setHasVerifiedFactor);
    resolveFactorState(s).then(apply).catch(() => apply(null));
  }

  function applyContext(u: User | null) {
    const owner = u?.id ?? null;
    // A resolution for this exact identity is already running (getSession()
    // and onAuthStateChange's INITIAL_SESSION firing back to back on mount is
    // the common case) — nothing new to learn by starting a second one, and
    // its result would just be discarded by the `request` guard below anyway.
    if (owner === contextInFlightFor.current) return;
    contextInFlightFor.current = owner;
    setHasFirm(null);
    const newUser = owner !== roleOwner.current;
    if (newUser) {
      roleOwner.current = owner;
      setRoleLoading(true);
    }
    const request = ++contextRequest.current;
    (async () => {
      try {
        let ctx = await resolveUserContext(u);
        if (ctx.failed) {
          // One retry: most failures here are a request racing a token refresh.
          await new Promise((r) => setTimeout(r, 1500));
          if (request !== contextRequest.current) return;
          ctx = await resolveUserContext(u);
        }
        if (request !== contextRequest.current) return;
        if (ctx.failed && resolvedFor.current === owner) {
          // Still failing, for the SAME user we already resolved: keep the last
          // good answer rather than demoting them mid-session.
          setRoleLoading(false);
          return;
        }
        setUserRole(ctx.role);
        setHasFirm(ctx.hasFirm);
        setFullName(ctx.fullName);
        if (!ctx.failed) resolvedFor.current = owner;
        setRoleLoading(false);
      } finally {
        // Only clear it if nothing NEWER for this same owner has already
        // taken over the slot (can't happen given the guard above, but a
        // stray `undefined` is what unblocks a genuinely later resolution,
        // e.g. the hourly TOKEN_REFRESHED, rather than leaving it wedged).
        if (contextInFlightFor.current === owner) contextInFlightFor.current = undefined;
      }
    })().catch(() => {
      if (request !== contextRequest.current) return;
      setRoleLoading(false);
    });
    // Action-level permissions, resolved independently of the role query above.
    // Kept separate on purpose: the role comes from Supabase directly (used for
    // nav/page gating and available even if the API is asleep), while this comes
    // from the API and is the authority on what the API will actually accept.
    // Deliberately NOT awaited — nothing here gates first paint; until it lands,
    // can() answers false and action controls stay hidden.
    // Reset only for a DIFFERENT user: clearing it on every hourly
    // TOKEN_REFRESHED hid every action control until the API answered again.
    if (newUser) {
      // Supersede anything still in flight for the previous identity (a
      // sign-out starts no request of its own to do it).
      permissionsGate.current.begin(() => {});
      policyGate.current.begin(() => {});
      setPermissions(null);
      setMfaPolicy(null);
    }
    // A portal principal (client or employee) has no RBAC role at all, so this
    // 403s correctly but noisily on every one of their pages — see
    // isPortalPrincipalPath's own comment. `can()` already answers false with
    // permissions left null, which is exactly what a portal page needs: it
    // never renders a staff action control in the first place.
    const portal = isPortalPrincipalPath();
    setPortalPrincipal(portal);
    if (u && !portal) {
      const applyPermissions = permissionsGate.current.begin<PermissionMap | null>(setPermissions);
      resolvePermissions().then(applyPermissions).catch(() => { if (newUser) applyPermissions(null); });
      const applyPolicy = policyGate.current.begin<MfaPolicy | null>(setMfaPolicy);
      resolveMfaPolicy().then(applyPolicy).catch(() => applyPolicy(null));
    }
  }

  useEffect(() => {
    // Perf: fire a no-op warm-up ping at the backend as early as possible so a
    // sleeping Render instance starts cold-starting while the user authenticates,
    // rather than on the first data request. Fire-and-forget; ignore all errors.
    const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "";
    if (apiBase) {
      fetch(`${apiBase}/health`, { method: "GET", mode: "cors" }).catch(() => {});
    }

    // Safety timeout — if Supabase doesn't respond in 5s, unblock the UI
    const timeout = setTimeout(() => setLoading(false), 5000);

    // Perf (Cause B fix): unblock the app as soon as the session is known. Role
    // resolution (an extra users-table query) runs asynchronously and no longer
    // gates AuthGuard / first paint. Until it resolves, userRole is null, which
    // the permission helpers treat as least-privilege (fail-closed), so nothing
    // is over-exposed during the brief window.
    supabase.auth.getSession().then(({ data: { session } }) => {
      clearTimeout(timeout);
      setSession(session);
      setUser(session?.user ?? null);
      setLoading(false);
      applyContext(session?.user ?? null);
      // Resolve MFA assurance for the restored session (null = computing).
      setMfaPending(null);
      resolveMfaPending(session).then(setMfaPending).catch(() => setMfaPending(true));
      if (!isPortalPrincipalPath()) refreshFactorState(session);
    }).catch(() => {
      clearTimeout(timeout);
      setLoading(false);
      setRoleLoading(false);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      async (_event, session) => {
        setSession(session);
        setUser(session?.user ?? null);
        // Non-blocking role + firm resolution.
        applyContext(session?.user ?? null);
        // Recompute MFA assurance on every auth transition (login, refresh, verify).
        // Set null first so the guard never treats an unresolved aal1 session as
        // "fully authenticated" and skips the challenge.
        setMfaPending(null);
        resolveMfaPending(session).then(setMfaPending).catch(() => setMfaPending(true));
        // A factor verified on the security page arrives here as
        // MFA_CHALLENGE_VERIFIED, which is what takes the banner down.
        if (!isPortalPrincipalPath()) refreshFactorState(session);
      }
    );

    return () => {
      clearTimeout(timeout);
      subscription.unsubscribe();
    };
  }, []);

  // Awaitable re-resolution — onboarding calls this right after creating a firm
  // so the guard sees hasFirm=true before navigating to the dashboard.
  const refreshUserContext = useCallback(async (): Promise<boolean> => {
    const { data: { session } } = await supabase.auth.getSession();
    const { role, hasFirm, fullName, failed } = await resolveUserContext(session?.user ?? null);
    if (!failed) {
      setUserRole(role);
      setHasFirm(hasFirm);
      setFullName(fullName);
    }
    // Onboarding calls this right after the users row gains a firm_id and a
    // role; without re-resolving here the map stays null for the rest of the
    // session and every action control would remain hidden for a new Partner.
    // It is also what the security page calls after a factor is verified: the
    // session is aal2 from then on and the map the aal1 token was refused
    // becomes answerable without signing out.
    const applyPermissions = permissionsGate.current.begin<PermissionMap | null>(setPermissions);
    resolvePermissions().then(applyPermissions).catch(() => applyPermissions(null));
    return hasFirm === true;
  }, []);

  const resolveEnrolmentRequired = useCallback(async (): Promise<boolean> => {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session) return false;
    const applyPolicy = policyGate.current.begin<MfaPolicy | null>(setMfaPolicy);
    const applyFactor = factorGate.current.begin<boolean | null>(setHasVerifiedFactor);
    const [policy, factor] = await Promise.all([
      resolveMfaPolicy().catch(() => null),
      resolveFactorState(session).catch(() => null),
    ]);
    applyPolicy(policy);
    applyFactor(factor);
    return enrolmentRequired({ policy, hasVerifiedFactor: factor, isPortalPrincipal: false });
  }, []);

  const mustEnrolMfa = enrolmentRequired({
    policy: mfaPolicy,
    hasVerifiedFactor,
    isPortalPrincipal: portalPrincipal,
  });

  // A sign-in is RECORDED once the session is fully signed in, not at the
  // password step. POST /api/identity/login-event sits behind mfa_guard, which
  // refuses an aal1 token for the roles MFA is required of — so recording it
  // straight after signInWithPassword, before the TOTP challenge, was refused
  // every time, and from the day MFA was switched on the login history held
  // logouts only (team-hub-02). The logout still records, because by then
  // the session is aal2.
  const loginToRecord = useRef(false);
  useEffect(() => {
    if (!loginToRecord.current || !session || mfaPending !== false) return;
    loginToRecord.current = false;
    import("@/lib/api")
      .then(({ api }) => api.identity.recordLoginEvent("login"))
      .catch(() => {});
  }, [session, mfaPending]);

  const signIn = useCallback(async (email: string, password: string) => {
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    // M6: login history (best-effort; never blocks sign-in) — recorded by the
    // effect above once any MFA challenge has been passed.
    if (!error) loginToRecord.current = true;
    return { error: error ? authErrorMessage(error) : null };
  }, []);

  const signOut = useCallback(async () => {
    // Record logout while the token is still valid, then sign out.
    try {
      const { api } = await import("@/lib/api");
      await api.identity.recordLoginEvent("logout").catch(() => {});
    } catch { /* best-effort */ }
    await supabase.auth.signOut();
  }, []);

  const can = useCallback(
    (resource: string, action: string) => canDo(permissions, resource, action),
    [permissions]
  );

  return (
    <AuthContext.Provider value={{ session, user, userRole, loading, roleLoading, mfaPending, hasFirm, fullName, permissions, can, refreshUserContext, mustEnrolMfa, resolveEnrolmentRequired, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/**
 * Action-level gating for the current user.
 *
 *   const { can } = usePermissions();
 *   {can("accounting", "write") && <Button>Post entry</Button>}
 *
 * `resolved` distinguishes "definitely not allowed" from "we don't know yet",
 * for the few places that want a spinner rather than an absent control. Most
 * call sites should ignore it: `can()` already answers false while unresolved,
 * which is the fail-closed default.
 */
export function usePermissions(): {
  can: (resource: string, action: string) => boolean;
  permissions: PermissionMap | null;
  resolved: boolean;
} {
  const { can, permissions } = useAuth();
  return { can, permissions, resolved: permissions !== null };
}
