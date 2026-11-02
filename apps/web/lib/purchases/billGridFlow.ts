/**
 * Where a keystroke in the purchase bill's line grid goes (POST-A-128, the bill half of the Tally habit).
 *
 * Enter has moved down a column and added a line since the grid got key handling. The hand that Tabs gets the same answer: Tab from a line's
 * LAST data cell (the one after which the browser would walk to the Remove button, past a read-only Amount) goes to the NEXT line's first cell,
 * and on the last line it adds one, but only when that line has something on it. A blank last line leaves Tab alone, so the keyboard is never a
 * way to grow a bill nobody asked to grow, and the Remove button stays reachable (Shift+Tab, which is never intercepted).
 *
 * The rule is pure so the page can be thin and the cases can be written down; the page owns the DOM facts (which input is a row's last data cell)
 * and the line facts (does the last line carry anything).
 */
export type AfterTab = { kind: "default" } | { kind: "next" } | { kind: "add" };

export function afterTab(args: { isLastDataCell: boolean; rowIndex: number; rowCount: number; lastLineHasContent: boolean }): AfterTab {
  const { isLastDataCell, rowIndex, rowCount, lastLineHasContent } = args;
  if (!isLastDataCell) return { kind: "default" };
  if (rowIndex < rowCount - 1) return { kind: "next" };
  return lastLineHasContent ? { kind: "add" } : { kind: "default" };
}

/**
 * A copy of a bill line for Ctrl+D (POST-A-128): the same fields under a new key, with the not-stated flags KEPT.
 *
 * `unread` lists the fields an extraction left for the CA because the document did not state them (AI-01), and the flag is what makes the save
 * refuse a line whose rate or quantity nobody chose; `gst_rate: 0` on such a line is a placeholder and not a 0% rate. Typing into the field
 * is what clears the flag, so a copy, which types nothing, carries it (as its own array: the two lines clear their flags independently).
 */
export function copyOfLine<T extends { _k: number; unread?: readonly string[] }>(line: T, key: number): T {
  return { ...line, _k: key, unread: line.unread ? [...line.unread] : undefined };
}
