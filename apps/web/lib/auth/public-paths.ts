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
  "/join",
  "/auth",
  "/portal",
  "/platform",
  "/sign",
];

/**
 * Public routes that are EXACT, not prefixes.
 *
 * `/onboarding` is the firm SIGNUP wizard and has to run before a firm exists,
 * so it is public — but it was a PREFIX, and `/onboarding/checklist` is a
 * STAFF screen (the client-onboarding workflow tracker, which calls
 * `api.onboarding.listActive`). So a signed-out visitor was handed that screen
 * instead of the login page, and AuthGuard skipped its redirect. The API call
 * behind it still needs a token, so nothing leaked — the page simply rendered
 * empty at a URL that should have bounced. `app/onboarding/` holds exactly one
 * page today; a later multi-step wizard adds its steps here by name.
 */
export const PUBLIC_EXACT = ["/onboarding"];

export function isPublicPath(pathname: string): boolean {
  // `output: export` serves every route with a trailing slash, so an exact
  // match has to ignore one — `/onboarding/` is `/onboarding`.
  const bare =
    pathname.length > 1 && pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
  if (PUBLIC_EXACT.includes(bare)) return true;
  return PUBLIC_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(prefix + "/")
  );
}
