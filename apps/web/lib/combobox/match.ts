/**
 * Pure, dependency-free combobox matching + ranking. No React here, so it is
 * unit-tested with `node --test` (mirrors lib/table/process.ts). Deterministic
 * and stable: within an equal rank, input order is preserved, so callers can
 * pre-sort (recent-first / alphabetical) and trust it to survive filtering.
 *
 * Ranking (lower = better): a field that EXACTLY equals the query beats one that
 * merely starts with it, which beats a word-prefix, which beats a substring; a
 * multi-token query that matches every token across fields is the loosest match.
 */

export const RANK = {
  EXACT: 0,
  PREFIX: 1,
  WORD_PREFIX: 2,
  INCLUDES: 3,
  TOKENS: 4,
  NONE: -1,
} as const;

/** Trim + lowercase for case-insensitive comparison. */
export const normalize = (s: unknown): string => (s == null ? "" : String(s)).trim().toLowerCase();

// Split on whitespace and common separators so "998314" matches "IT / 998314".
const WORD_SPLIT = /[\s\-/,.:;()]+/;

/**
 * Rank one option's searchable fields against a query. Returns a RANK score, or
 * RANK.NONE (-1) when nothing matches. An empty query is a neutral match so the
 * full list shows.
 */
export function matchScore(fields: string[], query: string): number {
  const q = normalize(query);
  if (!q) return RANK.WORD_PREFIX; // neutral: no query → keep all, stable order
  const nf = fields.map(normalize).filter(Boolean);
  if (nf.length === 0) return RANK.NONE;

  let best = Infinity;
  for (const f of nf) {
    if (f === q) return RANK.EXACT; // unbeatable — stop early
    if (f.startsWith(q)) best = Math.min(best, RANK.PREFIX);
    else if (f.split(WORD_SPLIT).some((w) => w && w.startsWith(q)))
      best = Math.min(best, RANK.WORD_PREFIX);
    else if (f.includes(q)) best = Math.min(best, RANK.INCLUDES);
  }
  if (best !== Infinity) return best;

  // Multi-token AND: every whitespace-separated token found somewhere across fields.
  const tokens = q.split(/\s+/).filter(Boolean);
  if (tokens.length > 1) {
    const hay = nf.join(" ");
    if (tokens.every((t) => hay.includes(t))) return RANK.TOKENS;
  }
  return RANK.NONE;
}

/**
 * Filter + rank options for a query. Empty query returns the input unchanged
 * (so a caller's recent-first / alphabetical order is preserved). Stable within
 * equal ranks.
 */
export function filterAndRank<T>(
  options: T[],
  query: string,
  getFields: (o: T) => string[],
): T[] {
  if (!normalize(query)) return options;
  const scored: { item: T; score: number; i: number }[] = [];
  options.forEach((item, i) => {
    const score = matchScore(getFields(item), query);
    if (score !== RANK.NONE) scored.push({ item, score, i });
  });
  scored.sort((a, b) => a.score - b.score || a.i - b.i);
  return scored.map((s) => s.item);
}

/** Does any option's field EXACTLY equal the query? Drives the "+ Create" row. */
export function hasExactMatch<T>(
  options: T[],
  query: string,
  getFields: (o: T) => string[],
): boolean {
  const q = normalize(query);
  if (!q) return false;
  return options.some((o) => getFields(o).some((f) => normalize(f) === q));
}
