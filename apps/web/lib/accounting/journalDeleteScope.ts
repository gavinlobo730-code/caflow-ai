/**
 * WHAT THE JOURNAL LIST'S BULK DELETE MAY ACT ON IS THE SERVER'S ANSWER (POST-A-462).
 *
 * Where a firm has a Partner approve every manual journal, deleting an entry already on the books is held to the posting rule
 * (`services/journal_approval_rule.assert_may_change_posted`, POST-A-456), and `GET /api/accounting/journal-approval` serves
 * that rule's answer for the person asking as `may_post`. This reads it and nothing else: no copy of the firm's setting, the
 * roles or the grid is kept in the browser.
 *
 *   * `false`: the server will refuse every POSTED entry, so the Delete acts on drafts only and is not offered for a selection of
 *     posted entries alone.
 *   * `true`, or `null` (still being read, or could not be read): every entry is offered and the server decides, with its own
 *     sentence for each it refuses.
 */
export type HasPostedFlag = { is_posted?: boolean | null };

export function deleteActsOn(mayPost: boolean | null): (entry: HasPostedFlag) => boolean {
  return mayPost === false ? (entry) => !entry.is_posted : () => true;
}

/** Whether a selection gives the bulk Delete anything to do under that answer. */
export function deleteAppliesTo(mayPost: boolean | null, rows: readonly HasPostedFlag[]): boolean {
  return rows.some(deleteActsOn(mayPost));
}

/** What the confirm says when posted entries in the selection will be left alone. */
export const POSTED_LEFT_ALONE =
  "Delete the selected drafts? This firm has a Partner approve every manual journal and you may not approve, so posted " +
  "entries in the selection stay on the books and are counted as skipped. Deleted drafts leave every screen and stay in " +
  "Settings → Audit Log with their lines.";
