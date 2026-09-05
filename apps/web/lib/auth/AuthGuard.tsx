"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useAuth } from "./AuthContext";
import { LogoIcon } from "@/components/LogoIcon";
import { isPublicPath } from "./public-paths";
import { mayRenderProtected } from "./guardDecision";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { session, loading, mfaPending, hasFirm } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const onLogin = pathname === "/login" || pathname.startsWith("/login/");

  useEffect(() => {
    if (loading) return;
    const isPublic = isPublicPath(pathname);
    if (!session) {
      if (!isPublic) router.replace("/login");
      return;
    }
    // Session exists but still owes a TOTP challenge → keep the user on /login
    // (which renders the challenge) and bounce them there from anywhere else.
    // This is enforced globally so MFA cannot be bypassed by deep-linking.
    if (mfaPending === true) {
      if (!onLogin) router.replace("/login");
      return;
    }
    // Authenticated but with no firm/users record (e.g. a brand-new signup whose
    // firm bootstrap hasn't run) → route to onboarding instead of dropping them
    // on an empty dashboard. Only on explicit false; null = still resolving.
    if (hasFirm === false && !isPublic) {
      router.replace("/onboarding");
      return;
    }
    // Fully authenticated (no challenge owed) — don't sit on the login page.
    // While mfaPending is still null (resolving) we do NOT redirect, so an aal1
    // session mid-challenge is never mistaken for fully authenticated.
    if (mfaPending === false && onLogin) {
      router.replace("/");
    }
  }, [session, loading, mfaPending, hasFirm, onLogin, pathname, router]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gradient-to-br from-indigo-950 via-indigo-900 to-violet-900">
        <div className="flex flex-col items-center space-y-4">
          <LogoIcon size="xl" spin />
          <p className="text-indigo-300 text-sm font-medium">PracticeSync AI</p>
        </div>
      </div>
    );
  }

  // One predicate, in lib/auth/guardDecision.ts so it can be unit-tested —
  // AuthGuard imports React and next/navigation and nothing here can be.
  //
  // The rule that changed: UNRESOLVED (null) IS NOT PERMISSION. It used to fall
  // through to `children`, so anyone whose MFA assurance could not be
  // determined got the whole app — the third of the three fail-opens described
  // in lib/auth/mfaAssurance.ts. The resolver retries internally and then
  // answers `pending`, so this is a brief loading state rather than a place
  // anybody gets stuck.
  if (!mayRenderProtected({
    hasSession: !!session,
    mfaPending,
    hasFirm,
    isPublic: isPublicPath(pathname),
    onLogin,
  })) return null;

  return <>{children}</>;
}
