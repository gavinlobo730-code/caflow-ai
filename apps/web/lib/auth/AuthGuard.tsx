"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useAuth } from "./AuthContext";
import { LogoIcon } from "@/components/LogoIcon";

// /platform is self-gated (checks platform-admin status server-side), so it is
// excluded from the firm AuthGuard's session/firm/MFA routing.
const PUBLIC_PREFIXES = ["/login", "/signup", "/onboarding", "/join", "/auth", "/portal", "/platform"];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(prefix + "/"));
}

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
        <div className="text-center space-y-4">
          <LogoIcon size="xl" />
          <div className="flex items-center justify-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:0ms]" />
            <div className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:150ms]" />
            <div className="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:300ms]" />
          </div>
          <p className="text-indigo-300 text-sm font-medium">PracticeSync AI</p>
        </div>
      </div>
    );
  }

  const isPublic = isPublicPath(pathname);
  if (!session && !isPublic) return null;
  // MFA challenge owed: render only the login page (the challenge UI); block
  // everything else while we redirect there.
  if (session && mfaPending === true && !onLogin) return null;
  // Firm-less user: block protected pages while redirecting to onboarding.
  if (session && hasFirm === false && !isPublic) return null;

  return <>{children}</>;
}
