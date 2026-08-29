"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import { scoreToLabel } from "@/lib/services/health-engine";

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
 */

interface HealthBadgeProps {
  score: number;
  size?: "sm" | "md";
  showLabel?: boolean;
  trend?: "improving" | "stable" | "declining" | null;
  /** Where the badge navigates. Omit to render a plain, non-interactive span. */
  href?: string;
}

const TREND_ARROW = {
  improving: "↑",
  stable:    "→",
  declining: "↓",
};

const TREND_COLOR = {
  improving: "text-emerald-600",
  stable:    "text-[#94A3B8]",
  declining: "text-red-600",
};

const TREND_WORD = {
  improving: "improving",
  stable:    "stable",
  declining: "declining",
};

/** One palette, for the white surfaces this badge is actually rendered on. */
const RING_COLOR = {
  Healthy:   "bg-emerald-50 text-emerald-700 ring-emerald-200",
  Fair:      "bg-yellow-50 text-yellow-700 ring-yellow-200",
  "At Risk": "bg-orange-50 text-orange-700 ring-orange-200",
  Critical:  "bg-red-50 text-red-700 ring-red-200",
};

function ringFor(score: number): string {
  const label = scoreToLabel(score);
  return RING_COLOR[label as keyof typeof RING_COLOR] ?? RING_COLOR.Fair;
}

export function HealthBadge({ score, size = "sm", showLabel = false, trend, href }: HealthBadgeProps) {
  const label = scoreToLabel(score);
  const title = `Health score: ${score}/100 — ${label}`
    + (trend ? `, ${TREND_WORD[trend]}` : "")
    + (href ? ". Open the Health tab." : "");

  const body = (
    <>
      <span>{score}</span>
      {showLabel && <span className="opacity-70">{label}</span>}
      {trend && (
        <span className={cn("text-[9px]", TREND_COLOR[trend])} aria-hidden="true">
          {TREND_ARROW[trend]}
        </span>
      )}
    </>
  );

  const shape = cn(
    "inline-flex items-center gap-1 rounded-full font-semibold ring-1",
    ringFor(score),
    size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-[11px]",
  );

  if (!href) {
    return <span className={cn(shape, "select-none")} title={title}>{body}</span>;
  }
  return (
    <Link
      href={href}
      title={title}
      aria-label={title}
      className={cn(shape, "transition-colors hover:ring-2 focus:outline-none focus:ring-2 focus:ring-blue-500")}
    >
      {body}
    </Link>
  );
}

/**
 * Kept as a distinct export for the clients list, where each row is already a
 * navigation target and a link inside it would fight the row's own click.
 */
export function HealthBadgeLight({ score, trend }: { score: number; trend?: string | null }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 select-none",
        ringFor(score),
      )}
      title={`Health: ${score}/100 — ${scoreToLabel(score)}`}
    >
      {score}
      {trend === "improving" && <span className="text-emerald-600" aria-hidden="true">↑</span>}
      {trend === "declining" && <span className="text-red-600" aria-hidden="true">↓</span>}
    </span>
  );
}
