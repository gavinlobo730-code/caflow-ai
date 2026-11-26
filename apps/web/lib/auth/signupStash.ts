// What the sign-up page hands to the onboarding page across the emailed link: the firm name and the person's name
// they typed, and (POST-A-479) the address the link was sent to, so a link that lands already used can offer
// "Email me a new link" without asking for it all again.
//
// The stash lives in the browser's local storage (the link may open in another tab) and is removed when the firm is
// created. It holds no secret: a firm name, a name and an email address the person typed a moment before.
//
// Dependency-free (the storage is a parameter) so it strips to plain JS for `node --experimental-strip-types`.

export const SIGNUP_STASH_KEY = "practicesync_signup";

export interface SignupStash {
  firmName?: string;
  fullName?: string;
  email?: string;
}

/** The slice of Storage the stash uses, so a test can supply its own. */
export interface StashStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function clean(v: unknown): string | undefined {
  return typeof v === "string" && v.trim() !== "" ? v.trim() : undefined;
}

/** The stash as stored, with anything that is not a non-empty string dropped. `{}` when there is none. */
export function readSignupStash(storage: StashStorage | null): SignupStash {
  if (!storage) return {};
  try {
    const raw = JSON.parse(storage.getItem(SIGNUP_STASH_KEY) || "{}");
    if (!raw || typeof raw !== "object") return {};
    const out: SignupStash = {};
    const firmName = clean((raw as Record<string, unknown>).firmName);
    const fullName = clean((raw as Record<string, unknown>).fullName);
    const email = clean((raw as Record<string, unknown>).email);
    if (firmName) out.firmName = firmName;
    if (fullName) out.fullName = fullName;
    if (email) out.email = email;
    return out;
  } catch {
    return {};
  }
}

export function writeSignupStash(storage: StashStorage | null, stash: SignupStash): void {
  if (!storage) return;
  try { storage.setItem(SIGNUP_STASH_KEY, JSON.stringify(stash)); } catch { /* storage is a convenience */ }
}

export function clearSignupStash(storage: StashStorage | null): void {
  if (!storage) return;
  try { storage.removeItem(SIGNUP_STASH_KEY); } catch { /* storage is a convenience */ }
}

/** Whether a new-firm sign-up was started in this browser (the page the link opens then belongs to it). */
export function newFirmSignupStarted(stash: SignupStash): boolean {
  return !!(stash.firmName || stash.fullName || stash.email);
}
