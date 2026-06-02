import { getSupabaseClient } from "@/lib/supabase/client";

/**
 * Returns the firm_id for the current authenticated user.
 * Throws a clear error if the user has no firm yet (prevents uuid "undefined" errors).
 */
export async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb
    .from("users")
    .select("firm_id")
    .eq("auth_user_id", session.user.id)
    .maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found — please complete onboarding first");
  return data.firm_id as string;
}
