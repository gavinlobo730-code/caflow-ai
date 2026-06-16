"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  ReactNode,
} from "react";
import { Session, User } from "@supabase/supabase-js";
import { supabase, getSupabaseClient } from "@/lib/supabase/client";
import { normalizeRole, type UserRole } from "@/lib/auth/permissions";

/**
 * Resolve the caller's role AND firm membership from the AUTHORITATIVE source —
 * the users table — rather than JWT user_metadata (which can be stale/forged).
 * `hasFirm` is true only when a users row with a non-null firm_id exists; a
 * freshly-signed-up account with no firm yet resolves to hasFirm=false so the
 * guard can route it to onboarding instead of dropping it on an empty dashboard.
 */
async function resolveUserContext(user: User | null): Promise<{ role: UserRole | null; hasFirm: boolean }> {
  if (!user) return { role: null, hasFirm: false };
  try {
    const { data } = await getSupabaseClient()
      .from("users")
      .select("role, firm_id")
      .eq("auth_user_id", user.id)
      .maybeSingle();
    const raw = (data?.role as string | undefined) ?? (user.user_metadata?.role as string | undefined);
    return { role: normalizeRole(raw), hasFirm: !!data?.firm_id };
  } catch {
    return { role: normalizeRole(user.user_metadata?.role as string | undefined), hasFirm: false };
  }
}

interface AuthContextValue {
  session: Session | null;
  user: User | null;
  userRole: UserRole | null;
  loading: boolean;
  /**
   * MFA challenge state: true = the session is aal1 but the account has a verified
   * factor (must complete the TOTP challenge to reach aal2); false = no challenge
   * needed; null = not yet resolved for the current session.
   */
  mfaPending: boolean | null;
  /** Whether the signed-in user has a users row linked to a firm. null = resolving. */
  hasFirm: boolean | null;
  /** Re-resolve role + firm membership (call after creating a firm in onboarding). */
  refreshUserContext: () => Promise<boolean>;
  signIn: (email: string, password: string) => Promise<{ error: string | null }>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** Resolve whether the current session still owes a TOTP challenge (aal1 → aal2). */
async function resolveMfaPending(session: Session | null): Promise<boolean> {
  if (!session) return false;
  try {
    const { data } = await getSupabaseClient().auth.mfa.getAuthenticatorAssuranceLevel();
    return !!data && data.currentLevel === "aal1" && data.nextLevel === "aal2";
  } catch {
    return false;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [userRole, setUserRole] = useState<UserRole | null>(null);
  const [loading, setLoading] = useState(true);
  const [mfaPending, setMfaPending] = useState<boolean | null>(null);
  const [hasFirm, setHasFirm] = useState<boolean | null>(null);

  function applyContext(u: User | null) {
    setHasFirm(null);
    resolveUserContext(u).then(({ role, hasFirm }) => {
      setUserRole(role);
      setHasFirm(hasFirm);
    }).catch(() => { setUserRole(null); setHasFirm(false); });
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
      resolveMfaPending(session).then(setMfaPending).catch(() => setMfaPending(false));
    }).catch(() => {
      clearTimeout(timeout);
      setLoading(false);
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
        resolveMfaPending(session).then(setMfaPending).catch(() => setMfaPending(false));
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
    const { role, hasFirm } = await resolveUserContext(session?.user ?? null);
    setUserRole(role);
    setHasFirm(hasFirm);
    return hasFirm;
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (!error) {
      // M6: record login for admin login-history (best-effort; never blocks sign-in).
      const { api } = await import("@/lib/api");
      api.identity.recordLoginEvent("login").catch(() => {});
    }
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

  return (
    <AuthContext.Provider value={{ session, user, userRole, loading, mfaPending, hasFirm, refreshUserContext, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
