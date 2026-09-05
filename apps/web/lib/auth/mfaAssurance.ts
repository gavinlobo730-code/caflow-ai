// Whether this session still owes an MFA challenge.
//
// WHAT WAS WRONG
//
//   Measured on production 2026-09-05. Both Partners hold a VERIFIED TOTP
//   factor, enrolled 2026-08-15. Every session created since — 88 of them,
//   through today — is `aal1`, and every one carries a single AMR claim:
//   `password`. Not one `totp` since the day of enrolment. Meanwhile the app is
//   in daily use on those sessions: 162 browser writes reached audit_log on
//   3 September alone, from a session that never completed a challenge.
//
//   So MFA is enrolled and is not being asked for.
//
//   The previous resolution was:
//
//     try {
//       const { data } = await auth.mfa.getAuthenticatorAssuranceLevel();
//       return !!data && data.currentLevel === "aal1" && data.nextLevel === "aal2";
//     } catch { return false; }
//
//   which FAILS OPEN twice over. `catch { return false }` turns "I could not
//   tell" into "nothing is owed", and a null `data` does the same. Its caller
//   repeated the mistake — `.catch(() => setMfaPending(false))` — and AuthGuard
//   rendered the app while the answer was still unresolved. Three layers, all
//   defaulting to "let them in".
//
//   It also asks the wrong oracle. `nextLevel` is computed from the USER OBJECT
//   the client happens to hold, so a session restored from storage whose cached
//   user carries no `factors` array reports nextLevel `aal1` — no challenge
//   owed — for an account that has a verified factor sitting in the database.
//   That is consistent with what production shows: the challenge worked on
//   enrolment day, when the user object was fresh, and has not been asked for
//   since.
//
// WHAT THIS DOES
//
//   Asks BOTH oracles and believes whichever one says a factor exists.
//   `listFactors()` is authoritative — it is the account's real factor list,
//   not a property of whatever user object is cached — so a verified factor
//   there means a challenge is owed even when the AAL call disagrees.
//
//   And it distinguishes THREE states rather than two. "Unresolved" is not
//   "satisfied": the caller must not render the app on it. That is the whole
//   defect, expressed as a type.
//
// THE TRADE-OFF, STATED
//
//   Persistent failure resolves to `pending`, not `satisfied` — the user is
//   held at the challenge screen instead of let through. That direction is
//   chosen deliberately: being wrongly held is recoverable by signing out and
//   in again, while being wrongly let through is a silent authentication
//   bypass, which is the thing being fixed. Transient errors are retried first
//   so a single blip does not bounce anybody.
//
// WHAT THIS CANNOT PROVE
//
//   That it makes production sessions aal2. The evidence above establishes the
//   OUTCOME (work happening at aal1 with factors enrolled) and this module
//   fixes a fail-open that would produce exactly that outcome — but confirming
//   cause needs one real login against the deployed app, which no test here can
//   do. See docs/compliance/06-data-protection-dpdp.md §5c.
//
// Dependency-free (type-only imports) so it strips to plain JS and unit-tests
// with `node --experimental-strip-types --test`, like reauth.ts beside it.

/** What the session owes. `unresolved` is deliberately not `satisfied`. */
export type Assurance = "pending" | "satisfied" | "unresolved";

export interface AssuranceLevels {
  currentLevel: string | null;
  nextLevel: string | null;
}

export interface FactorList {
  totp?: { status?: string }[] | null;
  all?: { status?: string; factor_type?: string }[] | null;
}

/** The minimal slice of supabase.auth.mfa this needs — keeps it mockable. */
export interface AssuranceCapableAuth {
  getAuthenticatorAssuranceLevel(): Promise<{ data: AssuranceLevels | null }>;
  listFactors(): Promise<{ data: FactorList | null }>;
}

function hasVerifiedFactor(list: FactorList | null | undefined): boolean {
  if (!list) return false;
  const totp = list.totp ?? [];
  if (totp.some((f) => f?.status === "verified")) return true;
  const all = list.all ?? [];
  return all.some((f) => f?.status === "verified");
}

/**
 * Resolve once, with no retry. `resolveAssurance` is the entry point; this is
 * separated so the retry policy is testable on its own.
 */
export async function resolveAssuranceOnce(
  auth: AssuranceCapableAuth,
): Promise<Assurance> {
  let levels: AssuranceLevels | null = null;
  let factors: FactorList | null = null;
  try {
    levels = (await auth.getAuthenticatorAssuranceLevel())?.data ?? null;
  } catch {
    levels = null;
  }

  // Already elevated — nothing is owed and nothing else needs asking.
  if (levels?.currentLevel === "aal2") return "satisfied";

  try {
    factors = (await auth.listFactors())?.data ?? null;
  } catch {
    factors = null;
  }

  // A NULL PAYLOAD IS NOT AN ANSWER. Treating `data: null` as "no factors" is
  // the same fail-open as swallowing the throw — the old code did both.
  const factorsAnswered = factors !== null;

  // Either oracle reporting a factor means a challenge is owed. listFactors is
  // asked first because it is the account's real factor list; `nextLevel` is
  // derived from whatever user object the client happens to hold.
  if (hasVerifiedFactor(factors)) return "pending";
  if (levels?.nextLevel === "aal2") return "pending";

  // "Satisfied" needs the AUTHORITATIVE list to have said there is no factor.
  // The AAL call alone is not enough: nextLevel === "aal1" is exactly what a
  // restored session reports for an account that does have one, which is the
  // bug this module exists to fix.
  if (factorsAnswered) return "satisfied";

  return "unresolved";
}


/**
 * Resolve with a bounded retry, then fail CLOSED.
 *
 * `attempts` counts total tries. `sleep` is injected so tests do not wait.
 */
export async function resolveAssurance(
  auth: AssuranceCapableAuth,
  { attempts = 3, sleep = (ms: number) => new Promise((r) => setTimeout(r, ms)) }: {
    attempts?: number;
    sleep?: (ms: number) => Promise<void>;
  } = {},
): Promise<Assurance> {
  let last: Assurance = "unresolved";
  for (let i = 0; i < attempts; i++) {
    last = await resolveAssuranceOnce(auth);
    if (last !== "unresolved") return last;
    if (i < attempts - 1) await sleep(150 * (i + 1));
  }
  // Still unresolved after retrying. Hold the user at the challenge rather than
  // letting them in — see "THE TRADE-OFF, STATED" above.
  return "pending";
}

/** `true` = challenge owed, `false` = nothing owed, `null` = still resolving. */
export function toMfaPending(assurance: Assurance): boolean | null {
  if (assurance === "pending") return true;
  if (assurance === "satisfied") return false;
  return null;
}
