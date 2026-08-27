/**
 * The narration text a set of bank lines have in common — the pattern a
 * matching rule should carry.
 *
 * WHY A SUBSTRING AND NOT SOMETHING CLEVERER
 *     A rule fires when the narration CONTAINS its pattern, case-insensitively:
 *     domain/banking/rules.rule_matches does `pattern not in narration.lower()`
 *     and nothing else. There is no regex, no tokenising, no fuzzy match on the
 *     server. So the only pattern worth proposing is a literal run of text that
 *     appears in every line the CA just coded — and, with luck, in next month's
 *     too. Anything smarter here would be a second matcher that disagrees with
 *     the one that actually runs.
 *
 * WHY IT IS ONLY EVER A PROPOSAL
 *     A statement is full of coincidental overlap: two unrelated lines both
 *     contain "2026", " TO ", or a bank's own prefix. This returns the longest
 *     run and lets the CA see and edit it before anything is saved. It is not
 *     allowed to create a rule on its own, and the caller must not either.
 */

/** A pattern must BEGIN and END with a letter; everything outside the first and
 *  last letter is trimmed away.
 *
 *  Punctuation and spaces at an edge narrow nothing and read like a typo. The
 *  digits matter more: the longest shared run between "NEFT SALARY PAYOUT 01"
 *  and "…02" is "NEFT SALARY PAYOUT 0", and that trailing 0 is an artefact of
 *  those two particular lines — it would fail to match "…PAYOUT 10" next month.
 *  A sequence number, cheque number or date at the edge of a pattern is always
 *  narrower than the CA means. Digits INSIDE a pattern are untouched, so
 *  "GST @9% ON BANK CHARGES" survives whole.
 *
 *  Spelled as "digits, spaces and ASCII punctuation" rather than the Unicode
 *  property escape \p{L} it would like to be: that escape needs the `u` flag,
 *  which needs an ES2018 target, and this project sets none — raising the whole
 *  repo's target to tidy one regex is not a trade worth making. Written this
 *  way a non-ASCII letter in a narration is kept rather than trimmed as noise,
 *  which is the behaviour \p{L} would have given anyway. */
const EDGE_NOISE_CLASS = "\\s0-9!-\\/:-@\\[-`{-~";
const EDGE_NOISE = new RegExp(`^[${EDGE_NOISE_CLASS}]+|[${EDGE_NOISE_CLASS}]+$`, "g");

/** The shortest pattern worth offering. Two or three characters ("TO", "26")
 *  appear in most narrations on a statement, so a rule built on one would fire
 *  on nearly every line — worse than no rule, because it also blocks the later
 *  rules that would have matched (rules.match_rule takes the FIRST that fires). */
export const MIN_PATTERN_LENGTH = 4;

/**
 * The longest run of text every one of `descriptions` contains, compared
 * case-insensitively but returned in the casing of the first line so the CA
 * recognises it.
 *
 * Returns "" when there is nothing worth proposing: fewer than two lines, any
 * line empty, no common run, or a run too short or with no letter in it.
 */
export function commonNarrationPattern(descriptions: string[]): string {
  // Fewer than two lines have nothing "in common" — the whole of a single
  // narration would come back, dates and reference numbers included, and a
  // rule built on it could never fire a second time.
  if (descriptions.length < 2) return "";
  const lines = descriptions.map((d) => (d ?? "").trim());
  if (lines.some((l) => l.length === 0)) return "";

  const lower = lines.map((l) => l.toLowerCase());
  // Search within the SHORTEST line: any run common to all of them is a
  // substring of that one, so nothing is missed and the scan stays small.
  let shortestAt = 0;
  for (let i = 1; i < lower.length; i++) {
    if (lower[i].length < lower[shortestAt].length) shortestAt = i;
  }
  const needleSrc = lower[shortestAt];
  const others = lower.filter((_, i) => i !== shortestAt);

  let bestStart = -1;
  let bestLen = 0;
  for (let start = 0; start < needleSrc.length; start++) {
    // Nothing starting here can beat what we already have.
    if (needleSrc.length - start <= bestLen) break;
    let len = bestLen;
    // Grow only past the current best: a shorter run is of no interest, and
    // every prefix of a common run is itself common, so this never skips one.
    while (start + len < needleSrc.length) {
      const candidate = needleSrc.slice(start, start + len + 1);
      if (!others.every((o) => o.includes(candidate))) break;
      len += 1;
    }
    if (len > bestLen) {
      bestLen = len;
      bestStart = start;
    }
  }
  if (bestStart < 0 || bestLen === 0) return "";

  // Return it in the shortest line's own casing — the CA is about to read it,
  // and an all-lowercase pattern next to an all-caps statement looks wrong even
  // though the matcher does not care.
  const raw = lines[shortestAt].slice(bestStart, bestStart + bestLen);
  const trimmed = raw.replace(EDGE_NOISE, "");
  // Short-circuits the all-digits case too: "2026-04" is common to every line
  // of an April statement and identifies nothing about what the money was for,
  // and the edge trim above leaves nothing of it at all.
  if (trimmed.length < MIN_PATTERN_LENGTH) return "";
  return trimmed;
}
