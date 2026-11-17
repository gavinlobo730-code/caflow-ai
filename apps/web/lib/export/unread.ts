/**
 * A READ THAT FAILED IS NOT A FILE OF ZEROS (POST-A-464).
 *
 * POST-A-360 made the client's trial balance, P&L and balance sheet workbooks refuse a failed read instead of exporting nil
 * figures. The multi-period CSVs beside them kept one failed period as a column of 0.00 under that period's own heading,
 * because each period is read on its own and a failed one is kept, tagged `error: true`, with no figures. A file leaves the
 * building under the client's name and somebody foots it, so an unread period is refused in words rather than written.
 *
 * This module only words the refusal; which column was read is the screen's own tag, set where the answer was read.
 */
export type MaybeUnreadColumn = { label: string; error?: boolean };

function listed(labels: readonly string[]): string {
  if (labels.length <= 1) return labels.join("");
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}

/** The sentence refusing an export that would carry an unread period, or null when every period was read. */
export function unreadColumnsSentence(columns: readonly MaybeUnreadColumn[], what: string): string | null {
  const unread = columns.filter((c) => c.error).map((c) => c.label);
  if (!unread.length) return null;
  return `The ${what} for ${listed(unread)} could not be read, so nothing was exported. `
    + `Retry ${unread.length === 1 ? "that period" : "those periods"}, then export again.`;
}

/** The sentence refusing an export whose one read failed, or null when it did not. */
export function unreadSentence(what: string, error: string | null | undefined): string | null {
  return error ? `The ${what} could not be read (${error}), so nothing was exported. Try again in a moment.` : null;
}
