/**
 * WHICH TIP IS SHOWN, WHERE IT IS DRAWN, AND WHERE THE TOUR GOES NEXT (POST-A-531). No React and no DOM: every function here
 * is given what it needs, so the rules are tested as plain code (`engine.test.ts`) and the component only wires them.
 *
 * ONE TIP AT A TIME. A screen may carry several; the first one, in the registry's order, that the person has not closed and
 * whose anchor is on the page is the one shown. A tip whose anchor is NOT on the page (the button is drawn only for another
 * role, or the screen has not finished loading) is skipped and never marked closed: it is shown the day its anchor is there.
 *
 * AN UNKNOWN IS "NO TIPS". Tips are a prompt and not a statement, so a state that could not be read shows nothing: `on` must
 * be exactly `true`. A screen is never covered by a tip because a read failed.
 */
import type { UserRole } from "@/lib/auth/permissions";
import { TIPS, TOUR, type Tip } from "./registry.ts";

/** A screen's address as the registry writes it: no trailing slash, no query, and "/" for the dashboard. */
export function screenOf(pathname: string): string {
  const path = (pathname || "/").split(/[?#]/)[0];
  return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path || "/";
}

function forRole(tip: Tip, role: UserRole | null): boolean {
  return !tip.roles || (role !== null && tip.roles.includes(role));
}

/** The tips of one screen that are for this person and that they have not closed, in the registry's order. */
export function openTipsOn(pathname: string, role: UserRole | null, seen: readonly string[], tips: readonly Tip[] = TIPS): Tip[] {
  const screen = screenOf(pathname);
  return tips.filter((t) => t.path === screen && forRole(t, role) && !seen.includes(t.id));
}

/** The tip to show now: the first open tip of the screen whose anchor is on the page, or null. */
export function tipToShow(
  pathname: string,
  role: UserRole | null,
  state: { on: boolean; seen: readonly string[] } | null,
  isOnPage: (anchor: string) => boolean,
  tips: readonly Tip[] = TIPS,
): Tip | null {
  if (!state || state.on !== true) return null;
  return openTipsOn(pathname, role, state.seen, tips).find((t) => isOnPage(t.anchor)) ?? null;
}

/**
 * Where "Next" leads from this screen: the next screen of the tour, after this one, that still has an open tip for this
 * person once `closing` is closed too. Null at the end of the tour, and on a screen that is not part of it.
 */
export function nextStop(
  pathname: string,
  role: UserRole | null,
  seen: readonly string[],
  closing: string | null = null,
  tips: readonly Tip[] = TIPS,
  tour: readonly string[] = TOUR,
): string | null {
  const here = tour.indexOf(screenOf(pathname));
  if (here < 0) return null;
  const closed = closing ? [...seen, closing] : seen;
  // A second tip on THIS screen comes before any other screen.
  if (openTipsOn(pathname, role, closed, tips).length > 0) return null;
  for (const stop of tour.slice(here + 1)) {
    if (openTipsOn(stop, role, closed, tips).length > 0) return stop;
  }
  return null;
}

export interface Box { top: number; left: number; width: number; height: number }
export interface Placement { top: number; left: number; side: "below" | "above"; arrowLeft: number }

export const TIP_GAP = 10;
export const TIP_MARGIN = 12;

/**
 * Where the pop-up sits: below the anchor when it fits, above when it does not, and kept inside the window sideways. Null
 * when the anchor is not in view (scrolled away, or zero-sized because it is hidden): a tip that floats beside nothing
 * explains nothing, so it is not drawn until the anchor is back.
 */
export function placeTip(anchor: Box, tip: { width: number; height: number }, win: { width: number; height: number }): Placement | null {
  if (anchor.width <= 0 || anchor.height <= 0) return null;
  const visible = anchor.top < win.height && anchor.top + anchor.height > 0 && anchor.left < win.width && anchor.left + anchor.width > 0;
  if (!visible) return null;
  const below = anchor.top + anchor.height + TIP_GAP;
  const above = anchor.top - TIP_GAP - tip.height;
  const fitsBelow = below + tip.height <= win.height - TIP_MARGIN;
  const side: Placement["side"] = fitsBelow || above < TIP_MARGIN ? "below" : "above";
  const centre = anchor.left + anchor.width / 2;
  const maxLeft = Math.max(TIP_MARGIN, win.width - tip.width - TIP_MARGIN);
  const left = Math.min(Math.max(centre - tip.width / 2, TIP_MARGIN), maxLeft);
  // The arrow points at the anchor's centre, kept off the pop-up's rounded corners.
  const arrowLeft = Math.min(Math.max(centre - left, 18), tip.width - 18);
  return { top: side === "below" ? below : above, left, side, arrowLeft };
}

/** What the server said about this person's tips, or null when the answer is not one (an unknown is "no tips"). */
export function readTipsState(data: unknown): { on: boolean; chosen: boolean; seen: string[] } | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const d = data as Record<string, unknown>;
  if (typeof d.on !== "boolean") return null;
  const seen = Array.isArray(d.seen) ? d.seen.filter((x): x is string => typeof x === "string") : [];
  return { on: d.on, chosen: d.chosen === true, seen };
}
