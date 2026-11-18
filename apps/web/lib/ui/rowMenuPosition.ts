/**
 * Where a list row's "more" menu is drawn: under its button, or ABOVE it when the row is near the foot of the window (POST-A-395).
 *
 * The menus are `position: fixed` so the table's own scroll box cannot clip them. Drawn always under the button, a row near the foot
 * of the window put its menu partly below the window, and its last items (a vendor's Edit, a bill's Delete) could not be reached
 * without first scrolling the row up. The menu's height is not known before it is drawn, so the rule asks for a fixed ROOM: when there is
 * less than that below the button and more room above than below, the menu opens upwards, anchored by its bottom edge to the button's top.
 */
export const ROW_MENU_GAP = 4;
/** Room a row menu is given before it opens upwards: the tallest of the list menus (six items) is about this tall. */
export const ROW_MENU_ROOM = 240;

export interface RowMenuPlace { top?: number; bottom?: number; left: number }

/** `rect` is the button's `getBoundingClientRect()`, `width` the menu's own width, `viewport` the window's inner width and height. */
export function rowMenuPosition(
  rect: { top: number; bottom: number; right: number },
  width: number,
  viewport: { width: number; height: number },
): RowMenuPlace {
  const left = Math.max(8, Math.min(rect.right - width, viewport.width - width - 8));
  const below = viewport.height - rect.bottom;
  if (below >= ROW_MENU_ROOM || below >= rect.top) return { top: rect.bottom + ROW_MENU_GAP, left };
  return { bottom: viewport.height - rect.top + ROW_MENU_GAP, left };
}

/** The same, read off the click's button and the window. */
export function rowMenuAt(e: { currentTarget: EventTarget }, width: number): RowMenuPlace {
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
  return rowMenuPosition(r, width, { width: window.innerWidth, height: window.innerHeight });
}
