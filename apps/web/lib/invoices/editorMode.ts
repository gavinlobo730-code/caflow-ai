/**
 * Which parts of the sales-invoice editor are still the NEW invoice's, once a draft exists on the server (POST-A-125).
 *
 * The editor used to mean "this document exists" by `isEdit`, which is true only for an invoice opened from the list. A new invoice
 * that was created and then refused at the issue (a locked period, a missing chart of accounts) is ALSO a draft on the server, and the
 * editor now keeps its id and saves to it. Everything that was decided by `isEdit` because "the document already exists" must follow
 * that, or the screen says one thing and the save does another:
 *
 *   * the currency and the exchange rate are written by the CREATE alone (the update takes neither), so once a draft exists they are
 *     frozen: left editable, a corrected rate was shown on the screen, ignored by the update, and the issue then posted at the old one;
 *   * the series suggestion fills the number box of a new invoice only. A draft that exists already holds a number of its own, and the
 *     suggestion counts that draft, so replacing the number would renumber it and leave a hole in the series (Rule 46(b)).
 *
 * `isEdit` itself stays what it was: an invoice opened for editing (its title, its breadcrumbs, its issued-state lock).
 */
export type EditorMode = {
  /** A draft or an invoice exists on the server for what is on the screen. */
  draftExists: boolean;
  /** The currency and exchange rate can no longer be changed here. */
  currencyIsFrozen: boolean;
  /** The series may still fill the number box. */
  mayFillTheNumber: boolean;
};

export function editorMode(isEdit: boolean, createdDraftId: string | null): EditorMode {
  const draftExists = isEdit || Boolean(createdDraftId);
  return { draftExists, currencyIsFrozen: draftExists, mayFillTheNumber: !draftExists };
}
