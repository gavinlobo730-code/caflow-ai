/**
 * A date that was on file when an edit screen opened and is not in its box now (POST-A-388).
 *
 * An edit screen sends a box's date as `date || undefined` (the bank account's as `date || null`), and the PATCH routes read their body with `exclude_none`: a box the person has
 * emptied sends NOTHING, so the stored date stays exactly as it was, and the screen said it was saved. That was the shipping bill date, the Form 15CA date, a supplier's no-PE
 * declaration date and a bank account's opening-balance date. A shipping bill, a Form 15CA acknowledgement and a signed declaration are evidence, and taking one away is not an
 * everyday edit, so the screen does not offer it: a date on file is replaced by the corrected date and is not emptied, and the screen says so beside the button instead of saying
 * "saved" over a request that changed nothing. (The server's own contract is plain and is not changed: an omitted date is unchanged, and a blank one is refused on an update.)
 *
 * The sentence is a pure function of two things the form holds, the date it opened with (or last saved) and the box now, so it is DERIVED and said through the form's
 * `useDateRefusal` latch and never copied into the form's error, where it would stay after the date was put back. A box whose text cannot be read hands its parent "" too, and it has
 * its own sentence (`useDateProblems`); the caller asks that one first and passes this one only when the box is genuinely blank.
 *
 *     const cleared = removedDateProblem("The shipping bill date", initialSnapshot.current.shippingBillDate, shippingBillDate);
 *
 * Nothing on file, or a date in the box, is no problem: a new record, and an edit that keeps or corrects the date, are not this rule's.
 */

/**
 * The sentence for a date box that held a day when the form opened and is blank now, or null.
 *
 * @param what    The date as the sentence names it, with its article: "The shipping bill date".
 * @param onFile  The date the form opened with, or last saved; blank or absent when there was none.
 * @param now     What the box holds.
 * @param orElse  The other way out, where the screen has one (a declaration is withdrawn by unticking it): "untick the declaration if there is none".
 */
export function removedDateProblem(what: string, onFile: string | null | undefined, now: string, orElse?: string): string | null {
  if (!onFile || !onFile.trim()) return null;
  if (now.trim()) return null;
  const way = orElse ? `enter the corrected date, or ${orElse}` : "enter the corrected date";
  return `${what} on file can be corrected but not removed: ${way}.`;
}
