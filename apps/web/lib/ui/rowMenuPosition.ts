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
  if (!opensUpward(rect, viewport.height, ROW_MENU_ROOM)) return { top: rect.bottom + ROW_MENU_GAP, left };
  return { bottom: viewport.height - rect.top + ROW_MENU_GAP, left };
}

/** The one vertical rule: open upwards only when there is less than `room` below the anchor AND more room above than below. */
export function opensUpward(rect: { top: number; bottom: number }, viewportHeight: number, room: number): boolean {
  const below = viewportHeight - rect.bottom;
  return !(below >= room || below >= rect.top);
}

/** Where a picker's list is drawn, and how tall it may be (POST-A-471). */
export interface ListPlace { top?: number; bottom?: number; left: number; maxHeight: number }

/** The window margin a picker's list keeps from the window's top and foot. */
export const LIST_EDGE = 8;

/**
 * The shared picker (`components/ui/combobox.tsx`) places its list by the row menus' rule: under its box, or above it when the box is
 * near the foot of the window. Unlike a row menu it is aligned to the box's LEFT edge (it is as wide as the box or wider), and its
 * height is capped at the room on the side it opens, so its first and last rows are inside the window wherever the box is: the list
 * scrolls inside itself instead of running off the window. `room` is the list's own tallest height.
 */
export function listPosition(
  rect: { top: number; bottom: number; left: number },
  width: number,
  viewport: { width: number; height: number },
  room: number,
): ListPlace {
  const left = Math.max(LIST_EDGE, Math.min(rect.left, viewport.width - width - LIST_EDGE));
  if (!opensUpward(rect, viewport.height, room)) {
    return { top: rect.bottom + ROW_MENU_GAP, left, maxHeight: Math.max(0, viewport.height - rect.bottom - ROW_MENU_GAP - LIST_EDGE) };
  }
  return { bottom: viewport.height - rect.top + ROW_MENU_GAP, left, maxHeight: Math.max(0, rect.top - ROW_MENU_GAP - LIST_EDGE) };
}

/** The same, read off the click's button and the window. */
export function rowMenuAt(e: { currentTarget: EventTarget }, width: number): RowMenuPlace {
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
  return rowMenuPosition(r, width, { width: window.innerWidth, height: window.innerHeight });
}
