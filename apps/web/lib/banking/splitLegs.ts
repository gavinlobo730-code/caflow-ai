/**
 * Pure arithmetic for splitting ONE bank line across several GL accounts
 * (Tier 1.2). No framework or browser imports, so it is unit-testable under
 * `node --test` — see splitLegs.test.ts.
 *
 * THE INVARIANT THIS SERVES
 *   The legs must sum EXACTLY to what the bank moved. Not "close enough", not
 *   "with a rounding line": a bank debited a specific number of paise, and a
 *   journal that does not account for every one of them either does not balance
 *   or hides the difference in whichever account was last in the list.
 *   domain/banking/splits refuses anything else and the replace RPC refuses it
 *   again inside the transaction; this is the same rule computed in the browser
 *   so the reader watches the gap close instead of meeting it on Save.
 *
 * INTEGER PAISE
 *   The reader types rupees. Every total here is computed in paise, and the
 *   conversion rounds once, at the point of conversion — `sum(amounts) * 100`
 *   would let three legs of 1/3 of a rupee drift off the total.
 *
 * WHY THE REASONS ARE CODES, NOT SENTENCES
 *   So this module needs no formatter, and so the sentence and the disabled
 *   button can be driven from ONE decision. The component renders the words.
 */

export interface SplitLeg {
  /** Stable only within the editor; the server keys splits by sequence. */
  key: string;
  account_id: string;
  /** Rupees as typed. "" means not filled in yet — which is not zero. */
  amount: string;
  narration: string;
}

/** Rupees as typed → integer paise. Commas and surrounding space are tolerated
 *  because Indian amounts get pasted in as "1,00,000.00". Anything that is not
 *  a number at all is 0, which `splitBlock` then reports as a missing amount
 *  rather than treating as an allocation. */
export function rupeesToPaise(v: string): number {
  const cleaned = String(v).replace(/,/g, "").trim();
  if (cleaned === "") return 0;
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return 0;
  return Math.round(n * 100);
}

/** The legs the reader has actually started. A blank row at the bottom is an
 *  invitation, not an error, so it must not count towards "at least two" or
 *  towards the total. */
export function filledLegs(legs: SplitLeg[]): SplitLeg[] {
  return legs.filter((l) => l.account_id !== "" || l.amount.trim() !== "");
}

/** What is left to allocate. Positive = short, negative = over-allocated.
 *  Mirrors domain/banking/splits.unallocated_paise, so the figure on screen is
 *  the figure the server would refuse on. */
export function unallocatedPaise(legs: SplitLeg[], amountPaise: number): number {
  return amountPaise - legs.reduce((sum, l) => sum + rupeesToPaise(l.amount), 0);
}

export type SplitBlock =
  | { code: "no-amount" }
  | { code: "too-few" }
  | { code: "no-ledger" }
  | { code: "non-positive" }
  | { code: "short"; paise: number }
  | { code: "over"; paise: number };

/**
 * Why this allocation cannot be saved yet, or null when it can.
 *
 * Ordered so the reader is told the most basic thing wrong first: a half-filled
 * row should say "every line needs a ledger", not quote an unallocated figure
 * computed from it.
 */
export function splitBlock(legs: SplitLeg[], amountPaise: number): SplitBlock | null {
  if (amountPaise <= 0) return { code: "no-amount" };
  const filled = filledLegs(legs);
  // One "split" is an ordinary posting — MIN_SPLITS in domain/banking/splits.
  if (filled.length < 2) return { code: "too-few" };
  if (filled.some((l) => l.account_id === "")) return { code: "no-ledger" };
  // A negative or zero leg would let the total look right while describing a
  // movement the bank never made. Direction comes from the bank line, not from
  // the sign of a split.
  if (filled.some((l) => rupeesToPaise(l.amount) <= 0)) return { code: "non-positive" };

  const left = unallocatedPaise(filled, amountPaise);
  if (left > 0) return { code: "short", paise: left };
  if (left < 0) return { code: "over", paise: -left };
  return null;
}

/** What to put on the leg the reader asked to absorb the remainder — the
 *  arithmetic they would otherwise do on the last row, which is exactly where
 *  paise go missing. Returns null when there is nothing left to give it. */
export function takeTheRestPaise(legs: SplitLeg[], key: string, amountPaise: number): number | null {
  const others = legs.filter((l) => l.key !== key);
  const rest = amountPaise - others.reduce((s, l) => s + rupeesToPaise(l.amount), 0);
  return rest > 0 ? rest : null;
}
