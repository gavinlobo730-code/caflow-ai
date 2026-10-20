/**
 * The accounting dashboard's "Unmatched Bank Txns" tile, in the four states it
 * can truthfully be in.
 *
 * The count comes from the server (`GET /api/banking/unmatched-count`, behind
 * banking:read). It used to be read from the browser straight off the table,
 * and since migration 524 the bank tables answer a person whose Banking access
 * a Partner has blocked (and a Reviewer, who is below the floor) with ZERO
 * ROWS, not with an error. A count taken over zero visible rows is 0, which on
 * this tile reads as "every bank line is matched": a claim about the books, made
 * to the one person who cannot see them. The server asks the person's access on
 * every request, so a refusal is a refusal and reaches the tile as a dash.
 *
 * The permission map the page already holds only decides whether to ASK: a
 * person it says cannot read banking is told so without a request, and the tile
 * shows "—" with the note "Not part of your access". The map is resolved at
 * sign-in and on each token refresh, so a person blocked since then still asks,
 * and the server's refusal (or any other failure) shows "—" with the note "Could
 * not be read", not a 0.
 */
export type UnmatchedBankReading =
  | { kind: "waiting" }
  | { kind: "not_allowed" }
  | { kind: "failed" }
  | { kind: "count"; count: number };

export interface UnmatchedBankTile {
  /** What the tile prints: a figure, or a dash when there is none to stand behind. */
  value: string;
  /** A short line under the figure, or null when there is nothing to add. */
  note: string | null;
  /** Amber only for a real, positive count. */
  attention: boolean;
  /** Whether the tile leads to the Bank screen: it does not for someone who cannot open it. */
  opensBank: boolean;
}

export const NOT_ALLOWED_NOTE = "Not part of your access";
export const FAILED_NOTE = "Could not be read";

export function unmatchedBankTile(reading: UnmatchedBankReading): UnmatchedBankTile {
  switch (reading.kind) {
    case "count":
      return {
        value: String(reading.count),
        note: null,
        attention: reading.count > 0,
        opensBank: true,
      };
    case "not_allowed":
      return { value: "—", note: NOT_ALLOWED_NOTE, attention: false, opensBank: false };
    case "failed":
      return { value: "—", note: FAILED_NOTE, attention: false, opensBank: true };
    case "waiting":
    default:
      return { value: "—", note: null, attention: false, opensBank: true };
  }
}

/**
 * The reading the server's answer gives. Anything that is not a whole,
 * non-negative `unmatched` figure in a successful envelope is unknown, never
 * zero: a missing key, a string, a negative number and `success: false` are all
 * the same dash. (A refusal does not arrive here: the API client throws on it,
 * and the caller turns a throw into `failed`.)
 */
export function readingFromAnswer(answer: unknown): UnmatchedBankReading {
  const a = answer as { success?: unknown; data?: { unmatched?: unknown } | null } | null | undefined;
  const n = a?.data?.unmatched;
  if (a?.success !== true || typeof n !== "number" || !Number.isInteger(n) || n < 0) {
    return { kind: "failed" };
  }
  return { kind: "count", count: n };
}

/**
 * Whether the count should be asked at all: only once the permission map has
 * resolved and says the person holds banking:read. While it is unresolved the
 * answer is "wait", never "ask and trust a zero".
 */
export function bankCountDecision(
  resolved: boolean,
  mayReadBanking: boolean,
): "wait" | "ask" | "not_allowed" {
  if (!resolved) return "wait";
  return mayReadBanking ? "ask" : "not_allowed";
}
