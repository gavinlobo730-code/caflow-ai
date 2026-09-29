/**
 * Is the signed-in identity a PORTAL CLIENT, as opposed to firm staff?
 *
 * A portal client's identity lives in `client_portal_users`, not
 * `public.users` — so AuthContext's own `hasFirm` check (a `users` row keyed
 * on auth_user_id) resolves to false for a portal client exactly as it does
 * for a brand-new firm signup whose bootstrap hasn't run yet, and AuthGuard
 * used to send both to the same /onboarding "Create your firm" wizard. This
 * tells the two apart so a portal client hitting a staff-only URL lands on
 * /portal/login instead.
 *
 * Asked of the database rather than the API, the same shape
 * lib/portal/employeeAccess.ts uses for the employee portal and for the same
 * reason: `client_portal_users_self` (migration 109) lets a portal contact
 * read their OWN row directly, so one RLS-scoped query answers this without
 * a round trip through apps/api.
 *
 * Never throws: this is a routing decision, not a data read, and a failed
 * probe should mean "cannot tell, fall back to onboarding" rather than an
 * error screen replacing a wizard that would otherwise have rendered fine.
 */
import { getSupabaseClient } from "@/lib/supabase/client";

export async function isPortalClientAccount(): Promise<boolean> {
  try {
    const sb = getSupabaseClient();
    const {
      data: { session },
    } = await sb.auth.getSession();
    if (!session) return false;
    const { data } = await sb
      .from("client_portal_users")
      .select("id")
      .eq("auth_user_id", session.user.id)
      .maybeSingle();
    return Boolean(data);
  } catch {
    return false;
  }
}
