"use client";

import { useEffect, useState } from "react";
import { usePrefersReducedMotion } from "../motion";

/**
 * The hero's rotating keyword.
 *
 * The brief makes this non-negotiable (§2: "The large editorial hero word must
 * rotate continuously… Do not remove, simplify away, or make this rotation
 * optional. It is a core part of the first-impression experience."), and the
 * page it replaces already rotated — the change is the sequence, the cadence
 * and, mainly, the TRANSITION. The old one swapped `textContent` on an
 * interval with no transition at all: the word simply blinked from one to the
 * next, which is the "gimmicky" effect §2 rules out rather than the "premium
 * fade/vertical transition" it asks for.
 *
 * ONE VISITOR DOES NOT GET THE ROTATION, and that is deliberate rather than an
 * exception carved out of §2. The same brief requires (§12) that
 * prefers-reduced-motion be respected and (§15) that the page be accessible;
 * text that auto-updates indefinitely beside other content is exactly what
 * WCAG 2.2.2 is about. So a visitor who has asked their operating system for
 * reduced motion sees the opening word, held. Everyone who has not — which is
 * effectively every prospect — sees the rotation. It is the default, not an
 * option someone has to switch on.
 *
 * LAYOUT CANNOT SHIFT AS THE WORD CHANGES. "Intelligence." is half again as
 * wide as "Payroll.", and a hero headline that re-flows five times a minute
 * would fail §15's "avoid layout shifts" on its own and drag the paragraph
 * below it around as well. Every word is therefore rendered stacked in the
 * same box, and an invisible sizer holding the LONGEST of them fixes the box's
 * width once.
 *
 * The whole visual is aria-hidden; the headline's real text is carried by a
 * visually-hidden sibling in the hero, so a screen reader gets one coherent
 * sentence instead of a word that changes underneath it.
 */

/** The sequence from the brief, in its order, opening on "Automation." */
export const HERO_WORDS = [
  "Automation.",
  "Compliance.",
  "Accounting.",
  "Payroll.",
  "Intelligence.",
] as const;

/** Inside the brief's 1.5–3s window; slow enough to read, not a carousel. */
const HOLD_MS = 2400;

export function RotatingWord({ className = "" }: { className?: string }) {
  const reduced = usePrefersReducedMotion();
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (reduced) {
      setIndex(0);
      return;
    }
    const id = window.setInterval(() => {
      setIndex((i) => (i + 1) % HERO_WORDS.length);
    }, HOLD_MS);
    return () => window.clearInterval(id);
  }, [reduced]);

  const longest = HERO_WORDS.reduce((a, b) => (b.length > a.length ? b : a));

  return (
    <span className={`relative inline-block align-top ${className}`} aria-hidden="true">
      {/* Sizer: never seen, but it is what stops the headline re-flowing. */}
      <span className="invisible block whitespace-nowrap">{longest}</span>
      {HERO_WORDS.map((word, i) => {
        const active = i === index;
        return (
          <span
            key={word}
            className="absolute inset-0 block whitespace-nowrap"
            style={{
              opacity: active ? 1 : 0,
              transform: active
                ? "translateY(0)"
                : i === (index - 1 + HERO_WORDS.length) % HERO_WORDS.length
                  ? "translateY(-0.26em)"
                  : "translateY(0.26em)",
              transition: reduced
                ? "none"
                : "opacity 700ms cubic-bezier(0.16,1,0.3,1), transform 700ms cubic-bezier(0.16,1,0.3,1)",
              willChange: "opacity, transform",
            }}
          >
            {word}
          </span>
        );
      })}
    </span>
  );
}
