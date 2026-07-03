"use client";

// Legacy client-portal landing page (pre-Phase-4.5.1). Its auto-bind-on-first-login
// logic (matching `?client=` against `clients.portal_user_id`) has been superseded
// by the audited, token-gated invite flow (F22 fix — see portal_access_service.py
// and /portal/dashboard). That auto-bind was also RLS-unreachable in practice: no
// `clients` RLS policy has ever granted a non-staff identity direct SELECT/UPDATE
// on the table, so this page could never actually complete a real client's login.
// Kept as a redirect (not deleted) so any already-sent invite email/bookmark
// pointing here still lands the client somewhere functional.
import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export default function LegacyPortalRedirect() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const invite = searchParams.get("invite");
    router.replace(invite ? `/portal/dashboard?invite=${encodeURIComponent(invite)}` : "/portal/dashboard");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
