// What the page an emailed sign-up link opens (/onboarding) does with the person who arrives on it (POST-A-480).
//
// Seen live on 18-11-2026: the owner started a NEW-firm sign-up with an address that already belonged to a Manager of
// an existing practice. The emailed link signed that account in and the wizard's redirect for an already-onboarded
// person sent them straight into the existing practice's dashboard, with no word that it was an existing account and
// no way to say they had meant a new firm. Opening somebody's practice silently as if it were the new one is the
// wrong answer; so is offering the new-firm steps to a person who already has a practice (one sign-in belongs to one
// practice, `routers/identity.ALREADY_A_MEMBER`).
//
//   wizard            a person with no practice: the new-firm steps, as before
//   existing-practice a new-firm sign-up was started AND this sign-in already belongs to a practice: SAY SO, naming who
//                     they are signed in as, and let them continue to it or sign out and use another address
//   go-home           a member of a practice who simply visited /onboarding (no sign-up was started here): the old
//                     redirect to their dashboard, which is right for them
//
// `createdHere` is true once THIS wizard has made the firm (step 2), when the person legitimately has a practice and
// the wizard goes on to step 3: it never turns into the notice.
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

export type SignupLanding = "wizard" | "existing-practice" | "go-home";

export interface SignupLandingState {
  /** The session is known (not still loading). */
  hasSession: boolean;
  /** Whether this sign-in belongs to a practice: true, false, or null while it is still being worked out. */
  hasFirm: boolean | null;
  /** A new-firm sign-up was started in this browser (the sign-up stash is present). */
  signupStarted: boolean;
  /** This wizard created the firm in this visit. */
  createdHere: boolean;
}

export function signupLanding(s: SignupLandingState): SignupLanding {
  if (!s.hasSession || s.createdHere) return "wizard";
  if (s.hasFirm !== true) return "wizard";
  return s.signupStarted ? "existing-practice" : "go-home";
}

/** The one line that says who the person is signed in as. */
export function signedInAsSentence(name: string | null | undefined, role: string | null | undefined, firm: string | null | undefined): string {
  const who = (name ?? "").trim() || "this account";
  const r = (role ?? "").trim();
  const f = (firm ?? "").trim();
  if (r && f) return `You are signed in as ${who}, ${r} at ${f}.`;
  if (f) return `You are signed in as ${who} at ${f}.`;
  if (r) return `You are signed in as ${who}, ${r}.`;
  return `You are signed in as ${who}.`;
}
