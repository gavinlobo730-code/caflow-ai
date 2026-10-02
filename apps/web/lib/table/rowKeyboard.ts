/**
 * What a key press does on a clickable DataTable row (frontend_ux-16).
 *
 * A clickable row was a `<tr onClick>` with a pointer cursor and nothing else:
 * no tab stop, no key handling, no focus ring. Nine screens use it — including
 * the ledger drill-through that opens the document behind a journal line
 * (ACC-22) — so a keyboard user could not open a row at all. This is the rule
 * for what the keys do, kept apart from the component so it is tested by plain
 * `node --test`; `components/ui/data-table.tsx` renders the row and calls it.
 *
 * THE RULES
 *   * Enter and Space ACTIVATE the row, as a click does — and only when the key
 *     went to the ROW. A row holds controls of its own (a checkbox, a link, a
 *     select): Space on a checkbox toggles the checkbox, and a keydown that
 *     bubbled up from it must not also open the document. `fromRow` is
 *     `event.target === event.currentTarget`.
 *   * ArrowDown and ArrowUp move to the next and previous clickable row and
 *     CLAMP at the ends. Wrapping from the last row to the first is
 *     disorienting on a ledger, and Tally's own lists stop.
 *   * Anything with Ctrl, Meta or Alt held is left to the browser and to
 *     shortcuts the page may own (Ctrl+Enter, Alt+ArrowDown).
 *   * A key a handler has already taken (`defaultPrevented`) is not taken twice.
 *
 * The same ELEMENT rule applies to the mouse. A click that lands on a link,
 * button or input inside a row is that control's click, not the row's: opening
 * the document AND following the link is two actions from one gesture.
 * `isFromInteractiveControl` is the one place that says which elements those
 * are.
 */

export type RowKeyAction = "activate" | "next" | "previous" | null;

export interface RowKeyInput {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  defaultPrevented?: boolean;
  /** `event.target === event.currentTarget`: the key went to the row itself. */
  fromRow: boolean;
}

export function rowKeyAction(e: RowKeyInput): RowKeyAction {
  if (!e.fromRow || e.defaultPrevented) return null;
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  switch (e.key) {
    case "Enter":
    case " ":
    case "Spacebar": // older engines
      return "activate";
    case "ArrowDown":
    case "Down": // older engines
      return "next";
    case "ArrowUp":
    case "Up":
      return "previous";
    default:
      return null;
  }
}

/** The index a step lands on, clamped to the rows that exist. `current` of -1
 *  (the row is not in the list, which should not happen) lands on the first. */
export function stepIndex(current: number, count: number, step: "next" | "previous"): number {
  if (count <= 0) return -1;
  if (current < 0) return 0;
  const target = step === "next" ? current + 1 : current - 1;
  return Math.min(count - 1, Math.max(0, target));
}

/** Elements that have a click of their own. A row's click does not fire for a
 *  press that began on one of these. */
export const INTERACTIVE_SELECTOR = [
  "a[href]", "button", "input", "select", "textarea", "label", "summary",
  "[contenteditable='']", "[contenteditable='true']",
  "[role='button']", "[role='link']", "[role='checkbox']", "[role='switch']",
  "[role='menuitem']", "[role='tab']", "[role='combobox']", "[role='textbox']",
  "[role='option']",
].join(",");

/** The slice of an Element this reads — a fake satisfies it in a test. */
export interface ElementLike {
  closest(selector: string): ElementLike | null;
  contains(other: unknown): boolean;
}

/** Did the event originate on a control INSIDE `row`, rather than on the row's
 *  own cells? The row itself never counts, even if it carried a role. */
export function isFromInteractiveControl(target: ElementLike | null | undefined, row: ElementLike): boolean {
  if (!target) return false;
  const hit = target.closest(INTERACTIVE_SELECTOR);
  return !!hit && hit !== row && row.contains(hit);
}
