/**
 * Where Tab goes inside a dialog that declares itself modal (POST-A-130).
 *
 * A dialog with `aria-modal="true"` tells a screen reader that everything behind it is inert; it does not make it so for the keyboard. The
 * shared `Modal` trapped Tab and the shared `Drawer` did not, so Tab walked out of an open drawer into the page behind it, which a sighted
 * keyboard user sees as focus vanishing and a screen-reader user hears as the dialog's own claim being false. Both now ask this one rule.
 *
 * `tabTarget` is the rule and reads nothing (it takes the focusable elements in order and the active one); `trapTabKey` is the thin DOM
 * wiring both components call from their keydown listener.
 */

/** Exactly the selector the Modal used before this was shared, so what counts as focusable is unchanged. */
const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

export type TabMove = "first" | "last" | null;

/**
 * Where Tab must be sent instead of the browser's own step, or null when the browser's own step stays inside the dialog.
 *
 *  - no focusable element: nothing to trap (null);
 *  - focus is NOT on one of the dialog's focusable elements (it is on the panel itself, which is focused on open, or it has escaped to the
 *    page behind): Shift+Tab from the panel would leave for the page, so it goes to the last element, and Tab goes to the first;
 *  - Shift+Tab on the first element wraps to the last, and Tab on the last wraps to the first;
 *  - anywhere else the browser's own step is inside the dialog already.
 */
export function tabTarget<T>(items: readonly T[], active: T | null, shift: boolean): TabMove {
  if (items.length === 0) return null;
  const at = active === null ? -1 : items.indexOf(active);
  if (at === -1) return shift ? "last" : "first";
  if (shift && at === 0) return "last";
  if (!shift && at === items.length - 1) return "first";
  return null;
}

/** The elements of `root` a person can Tab to, in document order. */
export function focusables(root: HTMLElement | null): HTMLElement[] {
  if (!root) return [];
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (n) => n.offsetParent !== null || n === document.activeElement,
  );
}

/**
 * Apply the rule to a keydown on `panel`: moves focus and cancels the browser's step when Tab would leave, and returns whether it did.
 *
 * A dialog opened OVER this one (a Modal inside a Drawer, or beside it) traps its own Tab, so a Tab whose focus is inside a different
 * `aria-modal` dialog is left alone, and so is one a nested handler has already taken (`defaultPrevented`).
 */
export function trapTabKey(e: KeyboardEvent, panel: HTMLElement | null): boolean {
  if (e.key !== "Tab" || e.defaultPrevented || !panel) return false;
  const active = document.activeElement as HTMLElement | null;
  const owner = active?.closest?.('[aria-modal="true"]') ?? null;
  if (owner && owner !== panel) return false;
  const items = focusables(panel);
  const move = tabTarget(items, active, e.shiftKey);
  if (!move) return false;
  e.preventDefault();
  (move === "first" ? items[0] : items[items.length - 1]).focus();
  return true;
}
