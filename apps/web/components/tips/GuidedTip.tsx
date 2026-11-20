"use client";

/**
 * THE POP-UP THAT EXPLAINS ONE THING ON THE SCREEN (POST-A-531).
 *
 * WHAT IT IS. A small panel beside the thing it explains (`data-tip="…"` in the page), with a ring round that thing. One at a
 * time, the first tip of the screen the person has not closed (`lib/tips/engine.ts` decides; `lib/tips/registry.ts` is every
 * tip). "Got it" closes it for good, for this person, on every device. "Turn off tips" is the switch in Settings.
 *
 * IT IS NOT A MODAL AND NOT AN OVERLAY. Nothing behind it is dimmed, locked or made inert; the page stays usable and the
 * person can ignore the tip for as long as they like. So it does not take the focus when it appears (taking it would pull a
 * person out of the field they were typing in), it does not trap Tab, and Escape closes it only while the focus is inside it.
 *
 * A KEYBOARD AND A SCREEN READER CAN REACH IT. It is drawn by position (`fixed`) but it lives in the document straight after
 * the skip link, ahead of the navigation, so it is the second stop of a Tab from the top of the page however far down the
 * screen its anchor is. When it appears its words are put in a polite live region that was already on the page, and the
 * thing it explains is given `aria-describedby` to its text for as long as it is shown.
 *
 * IT IS NEVER DRAWN BESIDE NOTHING. An anchor that is not on the page yet (the screen is still loading, or the button is not
 * drawn for this role) shows no tip and closes none; an anchor scrolled out of view hides the pop-up until it is back. A
 * dialog, a side panel or the open menu covers the page, so the pop-up waits while one is open.
 */
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { Lightbulb } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { useGuidedTips } from "@/lib/tips/GuidedTipsContext";
import { nextStop, openTipsOn, placeTip, tipToShow, type Placement } from "@/lib/tips/engine";
import { TOUR_LABELS, type Tip } from "@/lib/tips/registry";
import { Button } from "@/components/ui/button";
import { coversTheWindow } from "@/lib/ui/layerStack";
import { cn } from "@/lib/utils";

const RECHECK_MS = 500;

function anchorOf(anchor: string): HTMLElement | null {
  if (typeof document === "undefined") return null;
  // The first one that is drawn: a screen may carry the same anchor in its header and in its empty state.
  for (const el of Array.from(document.querySelectorAll<HTMLElement>(`[data-tip="${anchor}"]`))) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return el;
  }
  return null;
}

/**
 * Something is open over the page: a dialog, a side panel, the workspace menu. Read the way `lib/ui/inBody.ts` reads the open
 * layers, by what is DRAWN (a fixed box covering half the window or more) and not by a role: a hundred hand-built overlays in
 * this product say neither `dialog` nor `aria-modal`, and the first drive of this found the tip sitting on top of the Add
 * Client form, which is one of them.
 */
function pageIsCovered(): boolean {
  const view = { width: window.innerWidth, height: window.innerHeight };
  for (const el of Array.from(document.querySelectorAll<HTMLElement>(".fixed"))) {
    if (el.closest("[data-guided-tip]")) continue;
    const s = getComputedStyle(el);
    if (s.position !== "fixed" || s.display === "none" || s.visibility === "hidden") continue;
    if (coversTheWindow(el.getBoundingClientRect(), view)) return true;
  }
  return false;
}

export function GuidedTip({ pathname }: { pathname: string }) {
  const { state, close, setOn } = useGuidedTips();
  const { userRole } = useAuth();
  const [tip, setTip] = useState<Tip | null>(null);
  const [where, setWhere] = useState<{ place: Placement; ring: { top: number; left: number; width: number; height: number } } | null>(null);
  const [said, setSaid] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const bodyId = useId();

  const waiting = state?.on === true && openTipsOn(pathname, userRole, state.seen).length > 0;

  // Which tip, asked again on a short beat while this screen still has one to show: an anchor arrives when the screen's own
  // read lands, and leaves when a dialog opens over it.
  useEffect(() => {
    if (!waiting) { setTip(null); return; }
    const decide = () => setTip(pageIsCovered() ? null : tipToShow(pathname, userRole, state, (a) => anchorOf(a) !== null));
    decide();
    const beat = window.setInterval(decide, RECHECK_MS);
    return () => window.clearInterval(beat);
  }, [waiting, pathname, userRole, state]);

  const measure = useCallback(() => {
    const el = tip ? anchorOf(tip.anchor) : null;
    const box = panel.current;
    if (!el || !box) { setWhere(null); return; }
    const r = el.getBoundingClientRect();
    const place = placeTip(
      { top: r.top, left: r.left, width: r.width, height: r.height },
      { width: box.offsetWidth, height: box.offsetHeight },
      { width: window.innerWidth, height: window.innerHeight },
    );
    setWhere(place ? { place, ring: { top: r.top, left: r.left, width: r.width, height: r.height } } : null);
  }, [tip]);

  // Where it sits: measured before the first paint, and again when the window, a scrolling region or the layout moves.
  useLayoutEffect(() => {
    if (!tip) { setWhere(null); return; }
    measure();
    const beat = window.setInterval(measure, RECHECK_MS);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.clearInterval(beat);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [tip, measure]);

  // The thing it explains is described by it, for as long as it is shown; the words are announced once.
  useEffect(() => {
    if (!tip) { setSaid(""); return; }
    setProblem(null);
    setSaid(`Tip: ${tip.title}. ${tip.body}`);
    const el = anchorOf(tip.anchor);
    if (!el) return;
    const before = el.getAttribute("aria-describedby");
    el.setAttribute("aria-describedby", before ? `${before} ${bodyId}` : bodyId);
    return () => {
      if (before) el.setAttribute("aria-describedby", before); else el.removeAttribute("aria-describedby");
    };
  }, [tip, bodyId]);

  const turnOff = async () => {
    setBusy(true);
    try {
      setProblem(await setOn(false));
    } finally {
      setBusy(false);
    }
  };

  const next = tip && state ? nextStop(pathname, userRole, state.seen, tip.id) : null;

  return (
    <>
      {/* On the page before any tip is, so that what is put in it is announced. */}
      <p aria-live="polite" className="sr-only print:hidden">{said}</p>
      {tip && (
        <>
          {where && (
            <div
              aria-hidden="true"
              className="pointer-events-none fixed z-[45] rounded-lg ring-2 ring-gold ring-offset-2 print:hidden"
              style={{ top: where.ring.top, left: where.ring.left, width: where.ring.width, height: where.ring.height }}
            />
          )}
          <div
            ref={panel}
            role="dialog"
            aria-modal="false"
            aria-labelledby={titleId}
            aria-describedby={bodyId}
            data-guided-tip={tip.id}
            onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); close(tip.id); } }}
            // Measured while invisible, then placed: it never flashes in a corner first.
            className={cn("fixed z-[46] w-80 max-w-[calc(100vw-1.5rem)] rounded-xl border border-ps-border bg-white p-4 shadow-xl print:hidden", !where && "invisible")}
            style={where ? { top: where.place.top, left: where.place.left } : { top: 0, left: 0 }}
          >
            {where && (
              <span
                aria-hidden="true"
                className={cn("absolute h-3 w-3 rotate-45 border-ps-border bg-white", where.place.side === "below" ? "-top-1.5 border-l border-t" : "-bottom-1.5 border-b border-r")}
                style={{ left: where.place.arrowLeft - 6 }}
              />
            )}
            <p className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-ps-label">
              <Lightbulb size={12} aria-hidden="true" className="text-gold" /> Tip
            </p>
            <h2 id={titleId} className="mt-1 text-sm font-semibold text-ps-ink">{tip.title}</h2>
            <p id={bodyId} className="mt-1 text-sm leading-relaxed text-ps-body">{tip.body}</p>
            {problem && <p role="alert" className="mt-2 text-xs text-state-problem">{problem}</p>}
            <div className="mt-3 flex items-center justify-between gap-3">
              <Button variant="plain" size="none" disabled={busy} onClick={turnOff}
                className="text-xs text-ps-label underline underline-offset-2 hover:text-ps-ink disabled:opacity-50">
                Turn off tips
              </Button>
              <div className="flex items-center gap-3">
                {next && (
                  <Link href={next} onClick={() => close(tip.id)} className="text-xs font-medium text-brand underline underline-offset-2">
                    Next: {TOUR_LABELS[next] ?? "the next screen"}
                  </Link>
                )}
                <Button variant="plain" size="none" onClick={() => close(tip.id)}
                  className="rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark">
                  Got it
                </Button>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
