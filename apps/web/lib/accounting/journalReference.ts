/**
 * A JOURNAL ENTRY'S REFERENCE IS CHANGED AND NEVER REMOVED (POST-A-399).
 *
 * Every manual journal carries a reference: the server gives one when none is typed on a new entry, and it is part of the key that
 * stops the same voucher being posted twice. So an edit that empties the box cannot mean "store no reference". It used to mean
 * nothing at all: the editor sent null, the server read that as "not sent", the old reference stayed and the screen said the entry
 * was corrected. The editor now says this sentence beside its button and sends nothing. The server refuses a blank reference in the
 * same words (`models.accounting.JOURNAL_REFERENCE_NOT_REMOVED`), and a test on the server side holds the two equal.
 *
 * A NEW entry is not judged here: an empty box there asks for a generated reference, as it always has.
 */
export const JOURNAL_REFERENCE_NOT_REMOVED =
  "A journal entry's reference can be changed but not removed: enter the new reference. " +
  "Every entry carries one (one is given when none is typed), and it is part of what stops the same voucher being posted twice.";

/** The sentence refusing an edit whose reference box is empty over a reference on file, or null. */
export function removedJournalReferenceProblem(onFile: string | null | undefined, now: string | null | undefined): string | null {
  if ((now ?? "").trim() || !(onFile ?? "").trim()) return null;
  return JOURNAL_REFERENCE_NOT_REMOVED;
}

/** What an edit sends for the reference: the typed one, or nothing when the box is empty (and there was none on file to remove). */
export function editedJournalReference(now: string | null | undefined): string | undefined {
  return (now ?? "").trim() || undefined;
}
