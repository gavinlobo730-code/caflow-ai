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
  signIn: (email: string, password: string) => Promise<{ error: string | null }>;
  signOut: () => Promise<void>;
}

import { resolveAssurance, toMfaPending } from "./mfaAssurance";

const AuthContext = createContext<AuthContextValue | null>(null);

// Whether this session still owes an MFA challenge.
//
// The logic lives in lib/auth/mfaAssurance.ts, dependency-free and unit-tested,
// because the version inlined here FAILED OPEN three ways: it swallowed errors
// as "nothing owed", read a null payload the same way, and asked only
// getAuthenticatorAssuranceLevel() — whose nextLevel comes from the cached user
// object, so a restored session reports "nothing owed" for an account that has a
// verified factor. Production showed the result: both Partners enrolled on
// 2026-08-15, and every session since is aal1 with a `password` AMR claim only.
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
  const [mfaPending, setMfaPending] = useState<boolean | null>(null);
  const [hasFirm, setHasFirm] = useState<boolean | null>(null);
  const [fullName, setFullName] = useState<string | null>(null);
  const [permissions, setPermissions] = useState<PermissionMap | null>(null);

  function applyContext(u: User | null) {
    setHasFirm(null);
    const owner = u?.id ?? null;
    const newUser = owner !== roleOwner.current;
    if (newUser) {
      roleOwner.current = owner;
      setRoleLoading(true);
    }
    const request = ++contextRequest.current;
    (async () => {
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
    if (newUser) setPermissions(null);
    if (u) {
      resolvePermissions().then(setPermissions).catch(() => { if (newUser) setPermissions(null); });
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
    resolvePermissions().then(setPermissions).catch(() => setPermissions(null));
    return hasFirm === true;
  }, []);

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
    return { error: error?.message ?? null };
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
    <AuthContext.Provider value={{ session, user, userRole, loading, roleLoading, mfaPending, hasFirm, fullName, permissions, can, refreshUserContext, signIn, signOut }}>
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
