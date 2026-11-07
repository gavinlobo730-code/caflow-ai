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
