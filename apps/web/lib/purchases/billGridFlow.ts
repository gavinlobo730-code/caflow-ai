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
