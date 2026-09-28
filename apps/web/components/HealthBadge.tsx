"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import { gradeOf, type HealthGrade } from "@/lib/health/vocabulary";

/**
 * The client health score, as a pill.
 *
 * TWO THINGS THIS COMPONENT USED TO GET WRONG
 *
 * 1. IT WAS UNREADABLE, because it carried a palette for a dark background.
 *    `bg-yellow-500/15 text-yellow-300` is a 15%-opacity wash under 300-weight
 *    text: legible on a dark panel, a pale smudge on white. Every surface that
 *    renders it — the client header, the Overview card, the clients list — is
 *    white. So the dark palette was correct nowhere, and the file carried a
 *    second, correct "Light" copy alongside it that only one of the three call
 *    sites used. Reported as "what is on the top right corner": the score was
 *    there the whole time and could not be read.
 *
 *    There is now ONE palette, the readable one. Both exported names remain so
 *    call sites did not have to move at once, and both render identically.
 *
 * 2. IT LOOKED CLICKABLE AND WAS NOT. A bare <span> with no handler, next to a
 *    trend arrow, in the corner where controls live. Reported as "i tried
 *    clicking it it was nothing" — which was exactly true. There is a full
 *    Health page for every client, so the badge now links to it when given an
 *    href. Without one it stays a span rather than a link that goes nowhere:
 *    a dead control is worse than a plain label.
 *
 * The trend arrow is unlabelled by design — it is reinforced by the title and
 * by colour, and a word for it would crowd a 10px pill — but "73 →" alone is
 * cryptic, so `showLabel` puts the band next to the number where there is room.
 *
 * 3. IT GRADED ON ITS OWN LADDER (sweep-client-purchases-05). The band came
 *    from a browser helper — 80 / 60 / 40, four words — while the Health page
 *    one click away shows the ENGINE's grade — 80 / 65 / 50 / 35, five words
 *    (`domain/health/scoring.GRADE_BANDS`). So 73 read "Fair" on this pill and
 *    "Good" on the page it links to. The badge now shows the server's `grade`
 *    wherever the caller has one, and otherwise the pinned mirror of the same
 *    table (`lib/health/vocabulary.gradeOf`).
 */

interface HealthBadgeProps {
  score: number;
  size?: "sm" | "md";
  showLabel?: boolean;
  trend?: "improving" | "stable" | "declining" | null;
  /** Where the badge navigates. Omit to render a plain, non-interactive span. */
  href?: string;
  /** The SERVER's grade for this score, when the caller fetched one. Rendered
   *  in preference to the fallback band, so the pill and the Health page it
   *  links to can never disagree. */
  grade?: string | null;
}

const TREND_ARROW = {
  improving: "↑",
  stable:    "→",
  declining: "↓",
};

const TREND_COLOR = {
  improving: "text-emerald-600",
  stable:    "text-ps-hint",
  declining: "text-red-600",
};

const TREND_WORD = {
  improving: "improving",
  stable:    "stable",
  declining: "declining",
};

/** One palette, for the white surfaces this badge is actually rendered on —
 *  one entry per engine band, the same steps the Health pages' grade chips use. */
const RING_COLOR: Record<HealthGrade, string> = {
  Healthy:           "bg-sev-ok-surface text-sev-ok ring-sev-ok-border",
  Good:              "bg-sev-low-surface text-sev-low ring-sev-low-border",
  "Needs Attention": "bg-sev-medium-surface text-sev-medium ring-sev-medium-border",
  "At Risk":         "bg-sev-high-surface text-sev-high ring-sev-high-border",
  Critical:          "bg-sev-critical-surface text-sev-critical ring-sev-critical-border",
};

export function HealthBadge({ score, size = "sm", showLabel = false, trend, href, grade }: HealthBadgeProps) {
  const label = gradeOf(grade, score);
  const title = `Health score: ${score}/100 — ${label}`
    + (trend ? `, ${TREND_WORD[trend]}` : "")
    + (href ? ". Open the Health tab." : "");

  const body = (
    <>
      <span>{score}</span>
      {showLabel && <span className="opacity-70">{label}</span>}
      {trend && (
        <span className={cn("text-3xs", TREND_COLOR[trend])} aria-hidden="true">
          {TREND_ARROW[trend]}
        </span>
      )}
    </>
  );

  const shape = cn(
    "inline-flex items-center gap-1 rounded-full font-semibold ring-1",
    RING_COLOR[label],
    size === "sm" ? "px-2 py-0.5 text-3xs" : "px-2.5 py-1 text-2xs",
  );

  if (!href) {
    return <span className={cn(shape, "select-none")} title={title}>{body}</span>;
  }
  return (
    <Link
      href={href}
      title={title}
      aria-label={title}
      className={cn(shape, "transition-colors hover:ring-2 focus:outline-none focus:ring-2 focus:ring-brand")}
    >
      {body}
    </Link>
  );
}

/**
 * Kept as a distinct export for the clients list, where each row is already a
 * navigation target and a link inside it would fight the row's own click.
 */
export function HealthBadgeLight({ score, trend, grade }: { score: number; trend?: string | null; grade?: string | null }) {
  const label = gradeOf(grade, score);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-3xs font-semibold ring-1 select-none",
        RING_COLOR[label],
      )}
      title={`Health: ${score}/100 — ${label}`}
    >
      {score}
      {trend === "improving" && <span className="text-emerald-600" aria-hidden="true">↑</span>}
      {trend === "declining" && <span className="text-red-600" aria-hidden="true">↓</span>}
    </span>
  );
}
