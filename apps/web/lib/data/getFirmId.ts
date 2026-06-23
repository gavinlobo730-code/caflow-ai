import { getSupabaseClient } from "@/lib/supabase/client";

interface UserProfile {
  firmId: string;
  /** Primary key of the users table row for this user. */
  userId: string;
  /** Supabase auth UUID (session.user.id). */
  authUserId: string;
}

// Module-level 5-minute cache — firm membership is stable within a session.
// Eliminates the users-table round-trip on every page navigation.
let _cache: (UserProfile & { expiry: number }) | null = null;

export function invalidateFirmIdCache() {
  _cache = null;
}

/**
 * Returns firm_id, users-table UUID, and auth UUID for the current user.
 * Results are cached for 5 minutes; safe to call multiple times per page load.
 */
export async function getUserProfile(): Promise<UserProfile> {
  if (_cache && Date.now() < _cache.expiry) {
    return { firmId: _cache.firmId, userId: _cache.userId, authUserId: _cache.authUserId };
  }

  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");

  const { data } = await sb
    .from("users")
    .select("id, firm_id")
    .eq("auth_user_id", session.user.id)
    .maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found — please complete onboarding first");

  _cache = {
    firmId: data.firm_id as string,
    userId: data.id as string,
    authUserId: session.user.id,
    expiry: Date.now() + 5 * 60 * 1000,
  };
  return { firmId: _cache.firmId, userId: _cache.userId, authUserId: _cache.authUserId };
}

/**
 * Returns the firm_id for the current authenticated user.
 * Throws a clear error if the user has no firm yet (prevents uuid "undefined" errors).
 */
export async function getFirmId(): Promise<string> {
  return (await getUserProfile()).firmId;
}
