/**
 * Closing an overlay that asks first, while a date box still holds typing (POST-A-126, item 5).
 *
 * A typed-date box commits on BLUR, not per keystroke (components/ui/date-input.tsx). An overlay that hears Escape and asks "you have
 * unsaved changes" reads its dirty flag from the render it is in, and that render has not yet seen a date that is still sitting in the box:
 * the question would be skipped and the date lost. The employee drawer was fixed by hand. The shared Modal and Drawer, which the hand-built
 * overlays are moving onto (POST-A-130), do it here, once, so an overlay that asks before closing does not have to remember. The fixed-asset
 * Add and Correct drawers are the first on the shared Drawer that ask, and the browser drive of Add Asset holds it end to end (Escape over a
 * half-typed purchase date asks first; a Drawer that skips this closes with no question); the unit tests hold the order (leave the box, then
 * close on the next tick).
 *
 * WHAT IT DOES. If the focused element is a typed-date box (it carries `TYPED_DATE_MARKER`), the box is left first, which commits it to
 * its parent, and the close runs on the NEXT tick, by the closure that has seen the commit. Anything else closes at once: a plain input
 * reports every keystroke already, and a close that waits a tick for no reason is a close that can be pressed twice.
 *
 * `close` must read its parent's LATEST callback when it runs (the Modal and the Drawer pass `() => onCloseRef.current()`), because the
 * point of waiting is that the callback has changed.
 */
import { TYPED_DATE_MARKER } from "./typedDate.ts";

/** What this needs of the focused element: the two DOM calls, so a test can hand it a stand-in. */
export interface FocusedElement {
  hasAttribute(name: string): boolean;
  blur(): void;
}

export function closeAfterTheFocusedDateCommits(
  close: () => void,
  active: FocusedElement | null = typeof document === "undefined" ? null : (document.activeElement as FocusedElement | null),
  later: (run: () => void) => void = (run) => { setTimeout(run, 0); },
): void {
  if (active && typeof active.hasAttribute === "function" && active.hasAttribute(TYPED_DATE_MARKER)) {
    active.blur();
    later(close);
    return;
  }
  close();
}
