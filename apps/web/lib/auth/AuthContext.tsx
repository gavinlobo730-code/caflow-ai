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
 * Resolve the caller's role from the AUTHORITATIVE source — the users table —
 * rather than JWT user_metadata (which can be stale/forged and previously
 * defaulted to Partner). Falls back to user_metadata, then to least privilege.
 */
async function resolveUserRole(user: User | null): Promise<UserRole | null> {
  if (!user) return null;
  try {
    const { data } = await getSupabaseClient()
      .from("users")
      .select("role")
      .eq("auth_user_id", user.id)
      .maybeSingle();
    const raw = (data?.role as string | undefined) ?? (user.user_metadata?.role as string | undefined);
    return normalizeRole(raw);
  } catch {
    return normalizeRole(user.user_metadata?.role as string | undefined);
  }
}

interface AuthContextValue {
  session: Session | null;
  user: User | null;
  userRole: UserRole | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<{ error: string | null }>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [userRole, setUserRole] = useState<UserRole | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Safety timeout — if Supabase doesn't respond in 5s, unblock the UI
    const timeout = setTimeout(() => setLoading(false), 5000);

    supabase.auth.getSession().then(async ({ data: { session } }) => {
      clearTimeout(timeout);
      setSession(session);
      setUser(session?.user ?? null);
      setUserRole(await resolveUserRole(session?.user ?? null));
      setLoading(false);
    }).catch(() => {
      clearTimeout(timeout);
      setLoading(false);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      async (_event, session) => {
        setSession(session);
        setUser(session?.user ?? null);
        setUserRole(await resolveUserRole(session?.user ?? null));
      }
    );

    return () => {
      clearTimeout(timeout);
      subscription.unsubscribe();
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    return { error: error?.message ?? null };
  }, []);

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
  }, []);

  return (
    <AuthContext.Provider value={{ session, user, userRole, loading, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
