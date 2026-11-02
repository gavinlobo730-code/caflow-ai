/**
 * The key that copies the line a person is on, as a pure rule (POST-A-128).
 *
 * A spreadsheet's fill-down is Ctrl+D, and the bill and journal grids are what a Tally-trained hand uses as one. The key was left unchosen
 * because Ctrl+D is also the browser's bookmark key, and on a Mac it is the text field's own forward-delete. It is chosen here:
 *
 *   * Windows and Linux: Ctrl+D, and only in a line's cell. The browser's bookmark shortcut does not run when a page cancels the key (the
 *     grid does, as Google Sheets does for the same chord); outside a grid nothing here is read, so the bookmark key is untouched.
 *   * Mac: Command+D and NOT Control+D, because Control+D deletes the character after the cursor in every text field there.
 *   * Never with Shift or Alt held, so Ctrl+Shift+D (bookmark all tabs) and the chords layouts use for typing characters are left alone.
 *
 * The page owns the facts this does not know (which line, what a copy of it is); the rule is the key and where the copy goes.
 */
export interface ChordLike {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
}

/** Whether the machine is a Mac, from what the browser says about itself. False where there is no browser (the build, a test). */
export function isMacPlatform(nav: { platform?: string; userAgent?: string } | undefined =
  typeof navigator === "undefined" ? undefined : navigator): boolean {
  if (!nav) return false;
  return /mac|iphone|ipad|ipod/i.test(nav.platform || nav.userAgent || "");
}

/** Whether this keystroke asks for a copy of the current line. */
export function isDuplicateLineKey(e: ChordLike, mac: boolean): boolean {
  if (e.key.toLowerCase() !== "d" || e.altKey || e.shiftKey) return false;
  return mac ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey;
}

/** The rows with a copy of the one at `index` placed right after it. An index outside the rows copies nothing. */
export function withCopyAfter<T>(rows: readonly T[], index: number, copy: (row: T) => T): T[] {
  if (!Number.isInteger(index) || index < 0 || index >= rows.length) return [...rows];
  return [...rows.slice(0, index + 1), copy(rows[index]), ...rows.slice(index + 1)];
}
