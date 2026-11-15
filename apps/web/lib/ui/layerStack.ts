/**
 * Which stacking level a full-window layer takes when it opens over others (PRE-A-022, follow-up of 16-11-2026).
 *
 * The shared dialog, side panel and confirm box draw their layer in the document body so no parent's spacing can
 * move it. Before that, a dialog opened from INSIDE another full-window layer (the product and service manager,
 * drawn at level 80, opens the New Product/Service dialog, drawn at 70) sat inside that layer and so was painted
 * above it whatever its own level. Drawn in the body, its own level is compared with the layer it came from, and 70
 * under 80 put the dialog BEHIND the panel that opened it, where nobody can click it (the browser drive's two
 * catalogue scenarios found it). So a layer opening while another full-window layer is open takes the level just
 * above the highest one already open; with none open it keeps its own, and nothing changes.
 *
 * Pure, so the rule is tested without a browser; `inBody.ts` reads the page and applies it.
 */

/**
 * The level a layer opening now must take: one above the highest full-window layer already open, or null when its
 * own level is already above every one of them (or none is open) and it should keep it.
 */
export function levelAboveOpenLayers(own: number | null, open: readonly number[]): number | null {
  if (open.length === 0) return null;
  const top = Math.max(...open);
  if (own !== null && own > top) return null;
  return top + 1;
}

/** Whether a box covers enough of the window to be a layer something else opens over (a panel or a dialog's backdrop). */
export function coversTheWindow(box: { width: number; height: number }, window: { width: number; height: number }): boolean {
  return box.width >= window.width * 0.5 && box.height >= window.height * 0.5;
}
