/**
 * The keyboard flow of a journal's lines, as pure functions (accounting-08).
 *
 * TWO CONVENIENCES, BOTH ABOUT TYPING SPEED AND NEITHER ABOUT THE LEDGER:
 *
 *   * THE BALANCING LEG. A CA keying Dr 1,000 / Cr 600 has one number left to
 *     work out and the screen already knows it — the editor showed
 *     "Difference: ₹400.00" and then made them type it. A line added to an
 *     entry that does not balance now arrives carrying the amount that would,
 *     on the side that would.
 *
 *   * ENTER FINISHES A LINE. Tally-trained hands expect Enter to move on, not to
 *     do nothing. On the last line, with the entry still out of balance, Enter
 *     adds the next line (carrying its balancing leg); with the entry balanced
 *     it stays put, because a CA who has balanced the entry is done and a
 *     blank line they did not ask for is one they have to delete.
 *
 * THIS IS INPUT ASSISTANCE, NOT BUSINESS LOGIC. It sums what is typed and
 * offers the difference, exactly as the "Difference:" text already did. The
 * authority is `post_journal_atomic` / `edit_posted_journal`, which check Dr = Cr
 * again in integer paise and refuse an unbalanced entry whatever this offered —
 * a CA who overtypes the pre-filled amount, or who never looks at it, changes
 * nothing about what is accepted.
 *
 * Amounts are integer paise throughout and are read through
 * `lib/money/rupeeInput`, the one parser: nothing here multiplies by 100.
 */
import { paiseFromRupeeInput, rupeeInputFromPaise } from "../money/rupeeInput.ts";

/** A line as far as the flow cares: the two amount cells, as typed. */
export interface FlowLine {
  debit: string;
  credit: string;
}

export interface BalancingLeg {
  /** The side the new amount goes on — the one the entry is short of. */
  side: "debit" | "credit";
  /** Rupees as an amount cell takes them back ("400.00"). */
  amount: string;
}

/**
 * The amount that would balance the lines, or null.
 *
 * Null when the lines already balance, AND when any amount cell is not an
 * amount: a figure built on text that does not parse would be a guess about
 * what the CA meant, and the editor already flags that cell. `excludeIndex`
 * leaves one line out of the sum — the blank line the leg is being offered TO.
 */
export function balancingLeg(
  lines: readonly FlowLine[], excludeIndex?: number,
): BalancingLeg | null {
  let debit = 0;
  let credit = 0;
  for (let i = 0; i < lines.length; i++) {
    if (i === excludeIndex) continue;
    const d = paiseFromRupeeInput(lines[i].debit);
    const c = paiseFromRupeeInput(lines[i].credit);
    if (d === null || c === null) return null;
    debit += d;
    credit += c;
  }
  if (debit === credit) return null;
  return debit > credit
    ? { side: "credit", amount: rupeeInputFromPaise(debit - credit) }
    : { side: "debit", amount: rupeeInputFromPaise(credit - debit) };
}

/** Whether a line has no amount on either side — the only kind a balancing leg
 *  is ever written onto. A line the CA has already put a figure on is theirs. */
export function isAmountless(line: FlowLine): boolean {
  return paiseFromRupeeInput(line.debit) === 0 && paiseFromRupeeInput(line.credit) === 0;
}

export type AfterEnter =
  | { kind: "focus"; row: number }
  | { kind: "add" }
  | { kind: "stay" };

/**
 * Where Enter in a line's amount or narration cell goes.
 *
 * `balanced` is the editor's own verdict (all cells parse, total > 0, Dr = Cr).
 * Enter on any line but the last moves to the next line; on the last it adds one
 * only while the entry is still short of balance.
 */
export function afterEnter(rowIndex: number, rowCount: number, balanced: boolean): AfterEnter {
  if (rowIndex < rowCount - 1) return { kind: "focus", row: rowIndex + 1 };
  return balanced ? { kind: "stay" } : { kind: "add" };
}
