// Password-recovery URL marker — used by /auth/reset-password to tell a
// genuine recovery link apart from an ordinary already-signed-in visit.
//
// This module has no dependencies (a `Location`-shaped parameter, not a read
// of `window` itself) so it strips to plain JS and can be unit-tested with
// `node --experimental-strip-types --test`, the same shape as reauth.ts.

/**
 * True when a URL's hash or search carries a Supabase password-recovery
 * marker — the implicit flow's `#access_token=...&type=recovery` hash, or
 * the PKCE flow's `?code=...` query param.
 *
 * /auth/reset-password reads this from `window.location` synchronously, at
 * first render, before Supabase's own detectSessionInUrl handling can strip
 * these params from the address bar — see that page's doc comment for why
 * the timing matters, and why an ordinary existing session with neither
 * marker must not be read as a recovery signal.
 */
export function hasRecoveryMarkerInUrl(location: Pick<Location, "hash" | "search">): boolean {
  return /[#&]type=recovery(?:&|$)/.test(location.hash) || /[?&]code=/.test(location.search);
}
