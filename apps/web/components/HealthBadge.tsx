"use client";

import { cn } from "@/lib/utils";
import { scoreToLabel } from "@/lib/services/health-engine";

interface HealthBadgeProps {
  score: number;
  size?: "sm" | "md";
  showLabel?: boolean;
  trend?: "improving" | "stable" | "declining" | null;
}

const TREND_ARROW = {
  improving: "↑",
  stable:    "→",
  declining: "↓",
};

const TREND_COLOR = {
  improving: "text-emerald-400",
  stable:    "text-white/30",
  declining: "text-red-400",
};

const RING_COLOR = {
  Healthy:  "bg-emerald-500/15 text-emerald-300 ring-emerald-500/20",
  Fair:     "bg-yellow-500/15 text-yellow-300 ring-yellow-500/20",
  "At Risk":"bg-orange-500/15 text-orange-300 ring-orange-500/20",
  Critical: "bg-red-500/15 text-red-300 ring-red-500/20",
};

export function HealthBadge({ score, size = "sm", showLabel = false, trend }: HealthBadgeProps) {
  const label = scoreToLabel(score);
  const ring = RING_COLOR[label as keyof typeof RING_COLOR] ?? RING_COLOR.Fair;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full font-semibold ring-1 select-none",
        ring,
        size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-[11px]"
      )}
      title={`Health score: ${score}/100`}
    >
      <span>{score}</span>
      {showLabel && <span className="opacity-70">{label}</span>}
      {trend && (
        <span className={cn("text-[9px]", TREND_COLOR[trend])}>
          {TREND_ARROW[trend]}
        </span>
      )}
    </span>
  );
}

/** Light version for the white clients list (non-dark background) */
const RING_COLOR_LIGHT = {
  Healthy:  "bg-emerald-50 text-emerald-700 ring-emerald-200",
  Fair:     "bg-yellow-50 text-yellow-700 ring-yellow-200",
  "At Risk":"bg-orange-50 text-orange-700 ring-orange-200",
  Critical: "bg-red-50 text-red-700 ring-red-200",
};

export function HealthBadgeLight({ score, trend }: { score: number; trend?: string | null }) {
  const label = scoreToLabel(score);
  const ring = RING_COLOR_LIGHT[label as keyof typeof RING_COLOR_LIGHT] ?? RING_COLOR_LIGHT.Fair;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 select-none",
        ring
      )}
      title={`Health: ${score}/100 — ${label}`}
    >
      {score}
      {trend === "improving" && <span className="text-emerald-500">↑</span>}
      {trend === "declining" && <span className="text-red-500">↓</span>}
    </span>
  );
}
