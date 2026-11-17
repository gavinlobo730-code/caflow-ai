/**
 * What an EDIT sends for an optional free-text box the person may empty (POST-A-399).
 *
 * An edit screen used to send a box as `value.trim() || undefined`. `JSON.stringify` drops an undefined key, and the PATCH routes read their body as "what was sent", so a note or a
 * reference the person had EMPTIED reached the server as nothing at all: the stored value stayed, and the screen said the document was saved. The routes now take an explicit null as
 * "clear this" for the few soft free-text fields a model names (`models.clearable.patch_dict`), and this function is how a screen says it:
 *
 *   - the box holds text         -> that text (trimmed): a new value, or the same one again;
 *   - the box is empty and the document had a value when the form opened (or was last saved)
 *                                 -> null: the person took it away, and the request says so;
 *   - the box is empty and there was nothing on file
 *                                 -> undefined: there is nothing to say, and the key stays out of the request.
 *
 * THE LAST CASE IS WHY A FORM'S STARTING VALUE IS PASSED IN, AND NOT JUST "EMPTY MEANS NULL". A screen that did not load a field (a column its read leaves out, a value held in another
 * state) has an empty box that the person never touched, and sending null for it would ERASE a value the screen never showed. A null goes only where the person is known to have
 * removed something they were shown.
 *
 * WHAT IT IS NOT FOR. A DATE the document is expected to carry (a due date: a create that names none resolves one) and the EVIDENCE of a document (a shipping bill, a Form 15CA
 * acknowledgement) are not cleared by a screen: an emptied box over a date that is on file is refused beside the button (`lib/dates/removedDate`, POST-A-388 for the evidence dates and
 * the due date here), and the server's models do not list those fields as clearable, so a null for one would read "not sent" there too.
 */

/** The text to send for an optional text box on an edit: the text, `null` to clear what was on file, or `undefined` for nothing to say. */
export function editedText(now: string | null | undefined, onFile: string | null | undefined): string | null | undefined {
  const text = (now ?? "").trim();
  if (text) return text;
  return (onFile ?? "").trim() ? null : undefined;
}

/**
 * What an EDIT sends for an optional box whose value is not text (a figure, a picked answer), on the same three cases as `editedText`: the value, `null` to clear what
 * was on file, or `undefined` when the box is empty and nothing was on file. The caller has already read the box (a figure through the money parser, a choice as it is).
 */
export function editedChoice<T>(now: T | null | undefined, onFile: T | null | undefined): T | null | undefined {
  const empty = (v: T | null | undefined) => v === null || v === undefined || (typeof v === "string" && !v.trim());
  if (!empty(now)) return typeof now === "string" ? ((now as string).trim() as unknown as T) : now;
  return empty(onFile) ? undefined : null;
}

/**
 * The sentence refusing an edit that EMPTIES a tax identifier on file that a return reads (a party's GSTIN or state code, a vendor's PAN or foreign tax number), or null (POST-A-399).
 *
 * An identifier is corrected and not removed: every GST return not yet filed reads a party's GSTIN and state code live for the documents already issued to it, so emptying
 * one would move those documents between the tables of a return. The server refuses the same edit in the same words (`models.clearable.removed_identifier_problem`);
 * this says it beside the button before anything is sent.
 */
export function removedIdentifierProblem(label: string, onFile: string | null | undefined, now: string | null | undefined): string | null {
  if ((now ?? "").trim() || !(onFile ?? "").trim()) return null;
  return `The ${label} on file can be corrected but not removed: enter the corrected ${label}. `
    + "Every return not yet filed reads it for the documents already issued to this party.";
}
