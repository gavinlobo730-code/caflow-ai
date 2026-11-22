/**
 * A piece of evidence in TEXT that was on file when an edit screen opened and is not in its box now (POST-A-399, the remainder).
 *
 * The shipping bill number and port code of an export invoice, the supplier's own invoice number on a bill, and a bill's Form 15CA
 * acknowledgement number and Form 15CB UDIN are the evidence of the document: customs matches the refund against the first two (CGST
 * Rule 96(1)), section 16(2)(aa) and the GSTR-2B match read the third, and Rule 37BB's remittance rests on the last two. The server
 * reads a null for each as "not sent" on purpose (`models/clearable.py`: evidence is corrected and not removed by an edit), and the
 * screens send an emptied box as nothing. So a person who emptied one and pressed Save was told the document was saved while the
 * stored value stayed. The dates among the evidence were closed by POST-A-388 (`lib/dates/removedDate`); these are the texts, and the
 * answer is the same one: the screen does not offer taking evidence away, and says so beside the button instead of saying "saved"
 * over a request that changed nothing.
 *
 * The sentence is a pure function of what was on file (the snapshot the form opened with, or last saved) and the box now, so it is
 * DERIVED and said through the form's latch (`useDateRefusal`, which latches any derived sentence), never copied into the form's
 * error, where it would stay after the value was put back.
 *
 *     removedEvidenceProblem("The shipping bill number", initialSnapshot.current.shippingBillNo, shippingBillNo, "number")
 *
 * Nothing on file, or text in the box, is no problem: a new document, and an edit that keeps or corrects the value, are not this rule's.
 */

/**
 * The sentence for a box that held evidence when the form opened and is blank now, or null.
 *
 * @param what       The evidence as the sentence names it, with its article: "The shipping bill number".
 * @param onFile     What the form opened with, or last saved; blank or absent when there was none.
 * @param now        What the box holds.
 * @param corrected  The noun the way out names: "number", "code", "UDIN".
 */
export function removedEvidenceProblem(what: string, onFile: string | null | undefined, now: string, corrected: string): string | null {
  if (!onFile || !onFile.trim()) return null;
  if (now.trim()) return null;
  return `${what} on file can be corrected but not removed: enter the corrected ${corrected}.`;
}
