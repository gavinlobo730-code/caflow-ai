"use client";

import { useEffect, Suspense } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { useAuth } from "./AuthContext";
import { LogoIcon } from "@/components/LogoIcon";
import { isPublicPath } from "./public-paths";
import { isPortalClientAccount } from "@/lib/portal/clientAccess";
import {
  mayRenderProtected, shouldBounceFromSignup, shouldBounceFromLogin,
  noFirmRedirectTarget, type MfaPending,
} from "./guardDecision";

// output: "export" serves every route with a trailing slash, so both forms
// have to match — same normalisation isPublicPath uses.
const PORTAL_RECOVERY_PATHS = ["/login/forgot-password", "/login/forgot-password/"];

/**
 * The /login → "/" bounce for a fully-authenticated session, except on the
 * portal's own forgot-password link (?portal=1) — see guardDecision.ts's
 * shouldBounceFromLogin. Split out of AuthGuard's own effect with its OWN
 * usePathname()/useSearchParams(), rather than reading window.location the
 * way this used to, because those are two different clocks.
 *
 * usePathname() and useSearchParams() are both read out of React context that
 * Next.js updates together, in the SAME render, on every navigation —
 * client-side or a hard load alike. `window.location.search` is a THIRD,
 * independent source: the browser's own address bar, which Next updates via
 * history.pushState() inside an effect, not inside the render that flips
 * usePathname(). On a hard reload the two happen to agree from the very first
 * render (the browser already carries the final URL before React ever runs),
 * so that path always worked, and it is what the original fix's own tests
 * exercised. On an in-app <Link> transition — the SAME "Forgot password?"
 * link the client portal's own login page uses — pathname flips first, and
 * window.location.search still names the PREVIOUS page's query string for a
 * moment, so an already-signed-in session reading it here saw
 * isPortalRecovery=false for this effect's first run and was bounced to "/"
 * (and on, from there, since a portal contact has no `users` row) before the
 * exemption ever had a chance to apply.
 *
 * Reading straight off window.location was the original fix's OWN choice,
 * and for a real reason (see the header this replaces): AuthGuard wraps the
 * whole app from the root layout, and useSearchParams() forces a
 * statically-exported route out of static rendering unless ITS OWN caller
 * sits inside a Suspense boundary — wrapping AuthGuard itself would put a
 * Suspense fallback in front of every page in the product. This component
 * renders nothing and does only this one check, so it is the thing wrapped
 * instead: one small, invisible boundary rather than the whole app, and only
 * mounted while actually on /login (see AuthGuard below).
 */
function PortalRecoveryLoginBounce({
  hasSession,
  mfaPending,
}: {
  hasSession: boolean;
  mfaPending: MfaPending;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const onLogin = pathname === "/login" || pathname.startsWith("/login/");
  const isPortalRecovery =
    PORTAL_RECOVERY_PATHS.includes(pathname) && searchParams.get("portal") === "1";

  useEffect(() => {
    if (shouldBounceFromLogin({ hasSession, mfaPending, onLogin, isPortalRecovery })) {
      router.replace("/");
    }
  }, [hasSession, mfaPending, onLogin, isPortalRecovery, router]);

  return null;
}

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { session, loading, mfaPending, hasFirm } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const onLogin = pathname === "/login" || pathname.startsWith("/login/");
  const onSignup = pathname === "/signup" || pathname.startsWith("/signup/");

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
    // Authenticated but with no firm/users record → route onward instead of
    // dropping them on an empty dashboard. Only on explicit false; null =
    // still resolving. Two identities resolve to hasFirm=false: a brand-new
    // signup whose firm bootstrap hasn't run (→ /onboarding, unchanged), and
    // a PORTAL CLIENT hitting a staff-only URL — their identity has no
    // `users` row at all, and /onboarding's "Create your firm" wizard makes
    // no sense to a business owner who already has a password and does not
    // run one. noFirmRedirectTarget is the decision; isPortalClientAccount()
    // is the one async fact it needs, asked here because a guard that must
    // consult the database first cannot be the dependency-free predicate.
    if (hasFirm === false && !isPublic) {
      let cancelled = false;
      isPortalClientAccount().then((isPortalClient) => {
        if (!cancelled) router.replace(noFirmRedirectTarget(isPortalClient));
      });
      return () => { cancelled = true; };
    }
    // The /login → "/" bounce for a fully authenticated session lives in
    // PortalRecoveryLoginBounce below, which reads usePathname()/
    // useSearchParams() itself rather than through this effect — see its own
    // comment for why.
    // Same rule, mirrored for /signup: a fully authenticated session with an
    // existing firm has nothing left to do on the "Create your firm" form.
    // A firm-less session (mid-signup, before the firm bootstrap has run) is
    // left alone — shouldBounceFromSignup answers false for it.
    if (shouldBounceFromSignup({ hasSession: !!session, mfaPending, hasFirm, onSignup })) {
      router.replace("/");
    }
  }, [session, loading, mfaPending, hasFirm, onLogin, onSignup, pathname, router]);

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

  return (
    <>
      {onLogin && (
        <Suspense fallback={null}>
          <PortalRecoveryLoginBounce hasSession={!!session} mfaPending={mfaPending} />
        </Suspense>
      )}
      {children}
    </>
  );
}
