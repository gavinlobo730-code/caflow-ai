// Asking the server for a sign-up link, in one place (POST-A-485). The sign-up form, the page a link that can no longer be used lands on, and
// the wizard's "Email me a new link" all ask the same way, so the wait, the sentences and the stash are one speaker.
//
// The names and the address are written to the browser's stash BEFORE the request: a person whose first request failed (a wait, a mail that
// did not go) still has them when they come back. The server's own sentence is what a refusal says; this adds none.
import { api } from "@/lib/api";
import { writeSignupStash } from "@/lib/auth/signupStash";

export interface SignupLinkAsk { email: string; firmName: string; fullName: string }
export interface SignupLinkSent { validUntil: string; waitSeconds: number }

/** The browser's storage, or null where there is none (a server render, a blocked browser). */
function storage(): Storage | null {
  try { return typeof window === "undefined" ? null : window.localStorage; } catch { return null; }
}

/** Ask for a link. Resolves with when it ends and how long to wait before asking again; throws an Error carrying the server's sentence. */
export async function requestSignupLink(ask: SignupLinkAsk): Promise<SignupLinkSent> {
  const email = ask.email.trim();
  const firmName = ask.firmName.trim();
  const fullName = ask.fullName.trim();
  writeSignupStash(storage(), { firmName, fullName, email });
  const res = await api.signup.requestLink({ email, firm_name: firmName, full_name: fullName });
  if (!res.success || !res.data?.sent) throw new Error(res.error ?? "The link could not be sent just now. Please try again.");
  return { validUntil: res.data.valid_until, waitSeconds: res.data.wait_seconds };
}
