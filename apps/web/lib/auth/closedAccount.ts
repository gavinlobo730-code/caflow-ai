// What the browser does when the server says the signed-in person's account has been closed (POST-A-482).
//
// A platform administrator suspends or deletes a firm, or a Partner removes a person; the API then refuses that
// person's requests: 403 "Firm suspended", 403 "Firm unavailable", 403 "Account disabled. …", or 401 "Session
// revoked. …" for a token issued before they were signed out (core/auth). Until now the browser had no handler for
// these answers, so the person stayed on a screen that could load nothing and no word said why. The answer is to sign
// them out at once and say so in words, with nobody to blame and a way to sign in again.
//
// The decision is here, pure and tested; the sign-out and the move to the page are in lib/api (`request`).
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

export type ClosedAccountReason = "firm-suspended" | "firm-unavailable" | "person-disabled" | "signed-out";

/** The page also says why a person was signed out by the browser itself (POST-A-483): too long without a touch. */
export type SignedOutReason = ClosedAccountReason | "idle";

/** The reason a refusal means the account is closed, or null for any other refusal. Matched on what the server
 *  writes (`core/auth.py`), by status AND words, so an unrelated 403 or 401 never signs anybody out. */
export function closedAccountReason(status: number, message: string | null | undefined): ClosedAccountReason | null {
  const m = (message ?? "").trim();
  if (status === 403) {
    if (/^Firm suspended\b/.test(m)) return "firm-suspended";
    if (/^Firm unavailable\b/.test(m)) return "firm-unavailable";
    if (/^Account disabled\b/.test(m)) return "person-disabled";
  }
  if (status === 401 && /^Session revoked\b/.test(m)) return "signed-out";
  return null;
}

export interface ClosedAccountWords {
  heading: string;
  body: string;
}

/** What the page says for each reason. Nobody is named and no address is given: the product shows no contact until a
 *  business mailbox exists, and a person is pointed at whoever manages their firm's account. */
export function closedAccountWords(reason: string | null | undefined): ClosedAccountWords {
  switch (reason) {
    case "firm-suspended":
      return {
        heading: "Your firm's PracticeSync account has been suspended",
        body: "You have been signed out. Nothing has been lost. Please contact whoever manages your firm's PracticeSync account.",
      };
    case "firm-unavailable":
      return {
        heading: "Your firm's PracticeSync account is closed",
        body: "You have been signed out. Please contact whoever manages your firm's PracticeSync account.",
      };
    case "person-disabled":
      return {
        heading: "Your access has been removed",
        body: "You have been signed out. Please contact your firm's administrator.",
      };
    case "signed-out":
      return {
        heading: "You have been signed out",
        body: "An administrator ended your session. Sign in again to continue.",
      };
    case "idle":
      return {
        heading: "You were signed out for your security",
        body: "Nothing was touched for 30 minutes, so you were signed out to keep your practice's records safe. Sign in again to continue.",
      };
    default:
      return {
        heading: "You have been signed out",
        body: "Sign in again to continue.",
      };
  }
}

/** The page the browser is sent to. */
export function closedAccountPath(reason: SignedOutReason): string {
  return `/auth/account-closed/?why=${encodeURIComponent(reason)}`;
}

/** Whether `pathname` is a page that must NOT be sent to the closed-account page again (the page itself, the sign-in). */
export function isAlreadyOutside(pathname: string): boolean {
  return /^\/(auth\/account-closed|login)(\/|$)/.test(pathname);
}
