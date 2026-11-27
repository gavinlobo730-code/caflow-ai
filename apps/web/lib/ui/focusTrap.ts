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

/** What the first-field rule reads of a form control: the three facts a person cannot focus a control without. */
export interface FieldFacts {
  disabled: boolean;
  type?: string;
  /** null when the control (or an ancestor) is `display: none`, which cannot take focus. */
  offsetParent: unknown;
}

/**
 * Whether a dialog may move focus to this form control when it opens. A hidden control cannot take focus, so `.focus()` on it does nothing and
 * focus stays on whatever was behind the dialog: the bank's entry dialog opens with a hidden file input (`class="hidden"`) before its first
 * visible field, so focus stayed on the table row, whose arrow keys then moved the row behind the dialog and whose Enter opened another entry.
 */
export function canTakeFocusOnOpen(f: FieldFacts): boolean {
  return !f.disabled && f.type !== "hidden" && f.offsetParent !== null;
}

/** The first form control of `root` a dialog can really move focus to, or null (the dialog then focuses its own panel). */
export function firstFormField(root: HTMLElement | null): HTMLElement | null {
  if (!root) return null;
  const all = Array.from(root.querySelectorAll<HTMLInputElement>("input, select, textarea"));
  return all.find((el) => canTakeFocusOnOpen({ disabled: el.disabled, type: el.type, offsetParent: el.offsetParent })) ?? null;
}

/**
 * THE LAST CONTROL A PERSON PRESSED, KEPT FOR A DIALOG WHOSE OPENER LOST THE FOCUS BEFORE IT WAS DRAWN (POST-A-568).
 *
 * A button that is DISABLED while its dialog's data is fetched loses the keyboard focus (a disabled button cannot hold it), so by the time
 * the dialog is drawn nothing holds the focus and there is nobody to hand it back to: the page's top took it on close. The inventory
 * screen's Physical count button had it and refocused itself; the same is true of any button that is disabled while a request runs and
 * opens a dialog after it. The element the person PRESSED is the opener whatever happened to the focus since, so the page remembers it
 * (a click, or Enter or Space on a focused control) and the dialog falls back to it when the focus holds nobody, within `PRESS_MEMORY_MS`
 * so an old press cannot claim a dialog that something else opened.
 */
export const PRESS_MEMORY_MS = 20_000;
const PRESSABLE = 'button, a[href], [role="button"], [role="menuitem"], summary, input[type="button"], input[type="submit"]';

let lastPressed: { el: HTMLElement; at: number } | null = null;

/** Start remembering pressed controls on `doc`; returns the function that stops it. Called once, at import, in a browser. */
export function rememberPressedControls(doc: Document): () => void {
  const note = (e: Event) => {
    const hit = (e.target as Element | null)?.closest?.(PRESSABLE) as HTMLElement | null;
    if (hit) lastPressed = { el: hit, at: Date.now() };
  };
  const key = (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") note(e); };
  doc.addEventListener("click", note, true);
  doc.addEventListener("keydown", key, true);
  return () => { doc.removeEventListener("click", note, true); doc.removeEventListener("keydown", key, true); };
}

/** The control pressed within the last `PRESS_MEMORY_MS`, or null. */
export function lastPressedControl(now: number = Date.now()): HTMLElement | null {
  return lastPressed && now - lastPressed.at <= PRESS_MEMORY_MS ? lastPressed.el : null;
}

if (typeof document !== "undefined") rememberPressedControls(document);

const isThePage = (el: HTMLElement | null) => typeof document !== "undefined" && el === document.body;

/**
 * WHO OPENED A DIALOG: the element that held the focus when it was first DRAWN, unless that is gone by the time it is mounted (POST-A-555).
 *
 * A dialog has to read its opener twice, because two things happen in the same commit and each hides the opener from one reading.
 * A field inside it that takes the focus itself (`autoFocus`) does so BEFORE the dialog's effect runs, so the focused element at effect time
 * is that field, which closes with the dialog: the render before the commit is the last moment the opener still holds the focus. But a menu
 * or a placeholder dialog that is REPLACED by this one in the same commit holds the focus at render time and hands it back to its own
 * opener when it unmounts, so the element read in the render is gone at effect time and the focused element then is the right one.
 *
 * So: the element read in the render, if it is still on the page and is not inside the dialog; otherwise whatever holds the focus now,
 * unless that is inside the dialog (an autofocused field); otherwise the control last pressed (POST-A-568, an opener that lost the focus
 * because it was disabled while the dialog's data was fetched); and if there is none of those, nobody but the page.
 */
export function whoOpenedTheDialog(
  readInTheRender: HTMLElement | null, panel: HTMLElement | null,
  now: HTMLElement | null = typeof document === "undefined" ? null : (document.activeElement as HTMLElement | null),
  pressed: HTMLElement | null = lastPressedControl(),
): HTMLElement | null {
  const outside = (x: HTMLElement | null): x is HTMLElement => !!x && !(panel && panel.contains(x));
  if (readInTheRender && readInTheRender.isConnected && outside(readInTheRender) && !isThePage(readInTheRender)) return readInTheRender;
  if (outside(now) && !isThePage(now)) return now;
  if (pressed && pressed.isConnected && outside(pressed)) return pressed;
  if (readInTheRender && readInTheRender.isConnected && outside(readInTheRender)) return readInTheRender;
  if (outside(now)) return now;
  return readInTheRender;
}
