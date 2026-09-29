"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useAuth } from "./AuthContext";
import { LogoIcon } from "@/components/LogoIcon";
import { isPublicPath } from "./public-paths";
import { mayRenderProtected, shouldBounceFromSignup, shouldBounceFromLogin } from "./guardDecision";

// output: "export" serves every route with a trailing slash, so both forms
// have to match — same normalisation isPublicPath uses.
const PORTAL_RECOVERY_PATHS = ["/login/forgot-password", "/login/forgot-password/"];

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { session, loading, mfaPending, hasFirm } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const onLogin = pathname === "/login" || pathname.startsWith("/login/");
  const onSignup = pathname === "/signup" || pathname.startsWith("/signup/");
  // Read straight off window.location rather than useSearchParams(): this
  // component wraps the whole app from the root layout, and useSearchParams()
  // there would force every statically-exported route through a Suspense
  // boundary. A plain read inside the effect below needs neither — it only
  // ever runs client-side, after mount.
  const isPortalRecovery =
    PORTAL_RECOVERY_PATHS.includes(pathname) &&
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).get("portal") === "1";

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
    // isPortalRecovery is excluded — see guardDecision.ts's shouldBounceFromLogin.
    if (shouldBounceFromLogin({ hasSession: !!session, mfaPending, onLogin, isPortalRecovery })) {
      router.replace("/");
      return;
    }
    // Same rule, mirrored for /signup: a fully authenticated session with an
    // existing firm has nothing left to do on the "Create your firm" form.
    // A firm-less session (mid-signup, before the firm bootstrap has run) is
    // left alone — shouldBounceFromSignup answers false for it.
    if (shouldBounceFromSignup({ hasSession: !!session, mfaPending, hasFirm, onSignup })) {
      router.replace("/");
    }
  }, [session, loading, mfaPending, hasFirm, onLogin, onSignup, isPortalRecovery, pathname, router]);

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
