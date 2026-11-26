/**
 * Draw a full-window layer at the end of the document body, outside the page's own layout (PRE-A-022).
 *
 * The shared dialog's dark layer is `fixed inset-0`, and it was drawn where the page rendered it: on the Team
 * screen inside a container that spaces its children with `space-y-6`, whose 24 px top margin reached the
 * fixed layer too, so the layer started 24 px below the top of the window and cut the navy bar in two through
 * the PracticeSync name (the owner's screenshot of 15-11-2026, measured in Chromium the same night). Any parent's
 * spacing, transform or filter can move a fixed box the same way; a layer drawn in the body has no such parent.
 *
 * React still treats the layer as a child of the component that rendered it, so its events, its context and
 * its unmounting are unchanged. Where there is no document (the static export's prerender) the layer is
 * returned as is.
 *
 * A LAYER OPENED OVER ANOTHER STAYS IN FRONT OF IT. Drawn in the place it was rendered, a dialog opened from
 * inside another full-window layer was painted above that layer whatever its own level; drawn in the body, its
 * own level is compared with the other's, and the New Product/Service dialog (level 70) opened from the product
 * and service manager (level 80) went behind the panel that opened it, where nobody could click it. So the layer
 * is wrapped, and when it opens while another full-window layer is open the wrapper takes the level just above the
 * highest of them (`layerStack.ts`). With none open the wrapper is a plain block and the layer keeps its own level,
 * exactly as before. The level is set before the first paint, so the layer is never seen behind.
 */
import { createElement, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { coversTheWindow, levelAboveOpenLayers } from "./layerStack";

/** The level an element is painted at in the page's own stacking: the outermost positioned ancestor (or itself) with a level. */
function paintedLevel(el: Element): number | null {
  let level: number | null = null;
  for (let n: Element | null = el; n && n !== document.body; n = n.parentElement) {
    const s = getComputedStyle(n);
    if (s.position !== "static" && s.zIndex !== "auto") {
      const z = Number.parseInt(s.zIndex, 10);
      if (Number.isFinite(z)) level = z;
    }
  }
  return level;
}

/** The levels of the full-window layers open now, other than `mine`. */
function openLayerLevels(mine: Element): number[] {
  const view = { width: innerWidth, height: innerHeight };
  const levels: number[] = [];
  for (const el of Array.from(document.querySelectorAll<HTMLElement>(".fixed"))) {
    if (mine.contains(el)) continue;
    const s = getComputedStyle(el);
    if (s.position !== "fixed" || s.display === "none" || s.visibility === "hidden") continue;
    if (!coversTheWindow(el.getBoundingClientRect(), view)) continue;
    levels.push(paintedLevel(el) ?? 0);
  }
  return levels;
}

function StackedLayer({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [level, setLevel] = useState<number | null>(null);
  useLayoutEffect(() => {
    const mine = ref.current;
    if (!mine) return;
    const layer = mine.firstElementChild;
    setLevel(levelAboveOpenLayers(layer ? paintedLevel(layer) : null, openLayerLevels(mine)));
  }, []);
  return createElement(
    "div",
    { ref, "data-layer-stack": "", style: level === null ? undefined : { position: "relative", zIndex: level } },
    children,
  );
}

export function inBody(layer: ReactNode): ReactNode {
  return typeof document === "undefined"
    ? layer
    : createPortal(createElement(StackedLayer, null, layer), document.body);
}
