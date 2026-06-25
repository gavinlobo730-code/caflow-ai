/**
 * Routes that are publicly accessible without authentication.
 * AuthGuard uses this to skip auth redirects; tests verify the list is correct.
 *
 * /platform is self-gated (platform-admin check server-side), so AuthGuard
 * skips its standard firm/MFA routing — but the AppShell still renders for it.
 * /sign is the public engagement-letter signing page (no CA login required).
 */
export const PUBLIC_PREFIXES = [
  "/login",
  "/signup",
  "/onboarding",
  "/join",
  "/auth",
  "/portal",
  "/platform",
  "/sign",
];

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(prefix + "/")
  );
}
