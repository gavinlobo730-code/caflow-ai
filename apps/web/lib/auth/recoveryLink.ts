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

// ── WHICH PAGE LOAD WAS OPENED BY A RECOVERY LINK, KEPT UNTIL THE RESET PAGE ASKS (POST-A-510) ────────────────────────────────────────
//
// `hasRecoveryMarkerInUrl(window.location)` read "synchronously, at first render, before Supabase's own detectSessionInUrl handling can
// strip these params" is a read the page cannot make. The sign-in guard holds every page back until `getSession()` answers, and that
// answer waits for the library to start up, which reads the recovery link, stores its session, CLEARS the hash (`window.location.hash =
// ''`; the PKCE flow deletes `?code=`) and only then schedules the PASSWORD_RECOVERY event on a zero-delay timer (auth-js 2.118,
// GoTrueClient._initialize and _getSessionFromURL). So by the time the reset page renders, the address carries no marker, and whether
// the event arrives after the page has attached its listener is a race between a timer and a React commit: a valid link could land on
// "Link invalid or expired" with nothing wrong with it. The one attempt to drive the page showed exactly that, and was not explained.
//
// So the marker is read where it still exists, in `lib/supabase/client.ts` before the client is made, and remembered here for the reset
// page to ask. It is remembered ONLY for a load of the reset page itself (a `?code=` on any other page is not a recovery link), for a few
// minutes, and it is forgotten when the page is done with it, so an ordinary session visiting the page later is still not read as one
// that came by a link. Nothing here trusts a person: it records what the address said, once, before anything could rewrite it.

/** The reset page's own address, with or without the trailing slash a static export serves it under. */
const RESET_PAGE = /^\/auth\/reset-password\/?$/;

/** How long a page load stays "opened by a recovery link": the page mounts within seconds of the link opening, and a longer memory would
 *  let a tab left open for the day be read as a fresh link. */
export const RECOVERY_LINK_MEMORY_MS = 5 * 60 * 1000;

let remembered: { at: number } | null = null;
let looked = false;

/** Called ONCE per page load, before the sign-in library has read and cleaned the address. Only the first call counts: a later one
 *  would see an address the library has already rewritten and must not erase what the first saw. */
export function rememberRecoveryLink(location: Pick<Location, "hash" | "search" | "pathname">, now: number): void {
  if (looked) return;
  looked = true;
  if (RESET_PAGE.test(location.pathname) && hasRecoveryMarkerInUrl(location)) remembered = { at: now };
}

/** Whether THIS page load was opened by a recovery link, within the last few minutes. A read, not a consumption: React may run a
 *  state initialiser twice, and the page forgets it explicitly when it is done. */
export function recoveryLinkWasOpened(now: number): boolean {
  return remembered !== null && now - remembered.at >= 0 && now - remembered.at <= RECOVERY_LINK_MEMORY_MS;
}

/** The page is done with the link (the form was shown, the link was refused, or the password was saved): nothing is trusted after it. */
export function forgetRecoveryLink(): void {
  remembered = null;
}

/** Test only: start a page load afresh. */
export function resetRecoveryLinkMemoryForTests(): void {
  remembered = null;
  looked = false;
}
